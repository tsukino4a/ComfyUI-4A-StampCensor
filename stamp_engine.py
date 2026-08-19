"""Core stamp placement / compositing for 4A StampCensor."""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Iterable

import numpy as np
from PIL import Image

logger = logging.getLogger("ComfyUI-4A-StampCensor")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
DEMO_SCENE_NAME = "demo_scene.png"
DEMO_SCENE_PATH = os.path.join(ASSETS_DIR, DEMO_SCENE_NAME)

_PRESET_ORDER = [
    "heart_standard",
    "heart_wobbly_a",
    "heart_soft",
    "bar_h_scribble",
    "bar_h_thick",
    "star_wobbly",
    "circle_scribble",
    "cross_x",
]


_NEAR_WHITE = 250
_NEAR_BLACK = 5
_CHROMA_MAX = 12
_STAMP_KINDS = {"white_alpha", "black_alpha", "black_on_white"}


def _has_embedded_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


def _luma(rgb: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _inspect_stamp(im: Image.Image) -> tuple[str, np.ndarray]:
    """Classify a stamp as white_alpha / black_alpha / black_on_white / other."""
    arr = np.asarray(im.convert("RGBA"))
    rgb = arr[..., :3]
    alpha = arr[..., 3]
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    lum = _luma(rgb)
    useful_alpha = _has_embedded_alpha(im) and bool((alpha == 0).any()) and bool((alpha > 0).any())
    if useful_alpha:
        visible = alpha > 0
        vis_rgb = rgb[visible]
        if vis_rgb.size == 0 or int(chroma[visible].max()) > _CHROMA_MAX:
            return "other", arr
        if bool((vis_rgb.min(axis=1) >= _NEAR_WHITE).all()):
            return "white_alpha", arr
        if bool((vis_rgb.max(axis=1) <= _NEAR_BLACK).all()):
            return "black_alpha", arr
        vis_lum = lum[visible]
        if (
            int(chroma.max()) <= _CHROMA_MAX
            and bool((vis_lum <= _NEAR_BLACK).any())
            and bool((vis_lum >= _NEAR_WHITE).any())
        ):
            return "black_on_white", arr
        return "other", arr
    if int(chroma.max()) > _CHROMA_MAX:
        return "other", arr
    if bool((lum >= _NEAR_WHITE).any()) and bool((lum <= _NEAR_BLACK).any()):
        return "black_on_white", arr
    return "other", arr


def _to_white_alpha(kind: str, arr: np.ndarray) -> Image.Image:
    out = np.empty(arr.shape, dtype=np.uint8)
    out[..., :3] = 255
    if kind in ("white_alpha", "black_alpha"):
        out[..., 3] = arr[..., 3]
        return Image.fromarray(out, mode="RGBA")
    # Black ink on white paper: keep dark pixels, drop white.
    ink = np.clip(255.0 - _luma(arr[..., :3]), 0.0, 255.0)
    out[..., 3] = np.round(ink * (arr[..., 3].astype(np.float32) / 255.0)).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def normalize_stamp_rgba(im: Image.Image) -> Image.Image:
    """Turn allowed drawings into white RGB + alpha. Other RGBA images pass through."""
    kind, arr = _inspect_stamp(im)
    if kind not in _STAMP_KINDS:
        return im.convert("RGBA")
    return _to_white_alpha(kind, arr)


def _is_allowed_builtin_stamp(path: str) -> bool:
    try:
        im = Image.open(path)
    except OSError:
        return False
    kind, _ = _inspect_stamp(im)
    return kind in _STAMP_KINDS


def _assets_signature() -> tuple:
    if not os.path.isdir(ASSETS_DIR):
        return ()
    items = []
    for name in os.listdir(ASSETS_DIR):
        if name.lower() == DEMO_SCENE_NAME or not name.lower().endswith(".png"):
            continue
        path = os.path.join(ASSETS_DIR, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        items.append((name, st.st_mtime_ns, st.st_size))
    items.sort()
    return tuple(items)


def _scan_builtin_stamps() -> dict[str, str]:
    found: dict[str, str] = {}
    if os.path.isdir(ASSETS_DIR):
        for name in os.listdir(ASSETS_DIR):
            stem, ext = os.path.splitext(name)
            if ext.lower() != ".png" or name.lower() == DEMO_SCENE_NAME:
                continue
            path = os.path.join(ASSETS_DIR, name)
            if not _is_allowed_builtin_stamp(path):
                logger.warning(
                    "Skip stamp asset %s: use white+transparent or black ink on white",
                    name,
                )
                continue
            found[stem] = name
    ordered: dict[str, str] = {}
    for key in _PRESET_ORDER:
        if key in found:
            ordered[key] = found.pop(key)
    for key in sorted(found):
        ordered[key] = found[key]
    return ordered


BUILTIN_STAMPS: dict[str, str] = _scan_builtin_stamps()
PRESET_NAMES = list(BUILTIN_STAMPS.keys())
_ASSET_SIG = _assets_signature()


def refresh_builtin_stamps() -> list[str]:
    """Rescan assets/. Used on page load and Comfy.RefreshNodeDefinitions (R)."""
    global _ASSET_SIG
    sig = _assets_signature()
    if sig == _ASSET_SIG:
        return list(PRESET_NAMES)
    found = _scan_builtin_stamps()
    keep = set(found)
    for key in list(_BUILTIN_STAMP_CACHE):
        if key not in keep:
            _BUILTIN_STAMP_CACHE.pop(key, None)
    for key in list(_TINTED_STAMP_CACHE):
        if key[0] not in keep:
            _TINTED_STAMP_CACHE.pop(key, None)
    BUILTIN_STAMPS.clear()
    BUILTIN_STAMPS.update(found)
    PRESET_NAMES[:] = list(found.keys())
    _ASSET_SIG = sig
    return list(PRESET_NAMES)


def parse_hex_color(text: str) -> tuple[int, int, int]:
    raw = (text or "").strip()
    if not raw:
        return (0, 0, 0)
    if raw.startswith("#"):
        raw = raw[1:]
    if re.fullmatch(r"[0-9a-fA-F]{3}", raw):
        raw = "".join(ch * 2 for ch in raw)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError(f"Invalid hex color: {text!r}")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def parse_comfy_image_ref(value: str) -> tuple[str, str, str]:
    """Parse a Comfy image combo value into (filename, subfolder, type)."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return "", "", "input"
    type_name = "input"
    annotated = re.match(r"^(.*) \[(input|output|temp)\]$", raw, flags=re.I)
    if annotated:
        raw = annotated.group(1).strip()
        type_name = annotated.group(2).lower()
    slash = raw.rfind("/")
    if slash < 0:
        return raw, "", type_name
    return raw[slash + 1 :], raw[:slash], type_name


def resolve_comfy_image_path(filename: str, subfolder: str = "", type_name: str = "input") -> str:
    """Resolve a Comfy input/output/temp image path. Raises ValueError on traversal."""
    try:
        import folder_paths
    except ImportError as exc:
        raise RuntimeError("folder_paths is required") from exc

    name = str(filename or "").replace("\\", "/").lstrip("/")
    if not name or ".." in name.split("/"):
        raise ValueError("invalid filename")
    sub = str(subfolder or "").replace("\\", "/").strip("/")
    if ".." in sub.split("/"):
        raise ValueError("invalid subfolder")
    if type_name == "output":
        root = folder_paths.get_output_directory()
    elif type_name == "temp":
        root = folder_paths.get_temp_directory()
    else:
        root = folder_paths.get_input_directory()
    root = os.path.abspath(root)
    rel = os.path.join(sub, name) if sub else name
    path = os.path.abspath(os.path.join(root, rel))
    if path != root and not path.startswith(root + os.sep):
        raise ValueError("invalid path")
    return path


def open_comfy_image(filename: str, subfolder: str = "", type_name: str = "input") -> Image.Image:
    """Open a Comfy input/output/temp image as RGBA. No matting."""
    return Image.open(resolve_comfy_image_path(filename, subfolder, type_name)).convert("RGBA")


def comfy_image_mtime(image_name) -> str:
    """mtime marker for IS_CHANGED. Empty string if the file is missing or invalid."""
    filename, subfolder, type_name = parse_comfy_image_ref(image_name)
    if not filename:
        return ""
    try:
        return str(os.path.getmtime(resolve_comfy_image_path(filename, subfolder, type_name)))
    except (OSError, ValueError, RuntimeError):
        return ""


_BUILTIN_STAMP_CACHE: dict[str, Image.Image] = {}
_TINTED_STAMP_CACHE: dict[tuple[str, str], Image.Image] = {}
_TINTED_STAMP_CACHE_LIMIT = 32


def _fallback_preset() -> str:
    if not BUILTIN_STAMPS:
        raise FileNotFoundError("No built-in stamp assets")
    if "heart_wobbly_a" in BUILTIN_STAMPS:
        return "heart_wobbly_a"
    return next(iter(BUILTIN_STAMPS))


def _forget_preset(preset: str) -> None:
    BUILTIN_STAMPS.pop(preset, None)
    try:
        PRESET_NAMES.remove(preset)
    except ValueError:
        pass
    _BUILTIN_STAMP_CACHE.pop(preset, None)
    for key in list(_TINTED_STAMP_CACHE):
        if key[0] == preset:
            _TINTED_STAMP_CACHE.pop(key, None)


def load_builtin_stamp(preset: str, *, copy: bool = True) -> Image.Image:
    preset = str(preset or "")
    filename = BUILTIN_STAMPS.get(preset)
    path = os.path.join(ASSETS_DIR, filename) if filename else ""
    if not filename or not os.path.isfile(path):
        if filename:
            _forget_preset(preset)
        preset = _fallback_preset()
        filename = BUILTIN_STAMPS[preset]
        path = os.path.join(ASSETS_DIR, filename)
    if os.path.normcase(os.path.basename(path)) == os.path.normcase(DEMO_SCENE_NAME):
        raise ValueError("demo_scene.png is an internal preview plate, not a stamp")
    hit = _BUILTIN_STAMP_CACHE.get(preset)
    if hit is None:
        hit = normalize_stamp_rgba(Image.open(path))
        _BUILTIN_STAMP_CACHE[preset] = hit
    return hit.copy() if copy else hit


def image_tensor_to_rgba(image_hwc: np.ndarray) -> Image.Image:
    """Comfy IMAGE frame [H,W,C] float 0..1 -> PIL RGBA."""
    arr = np.asarray(image_hwc)
    if arr.ndim != 3:
        raise ValueError("Expected HWC image")
    h, w, c = arr.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    if c == 1:
        ch = np.clip(arr[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 0] = ch
        out[..., 1] = ch
        out[..., 2] = ch
        out[..., 3] = 255
    elif c == 3:
        out[..., :3] = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 3] = 255
    elif c == 4:
        out[:] = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"Unsupported channel count: {c}")
    return Image.fromarray(out, mode="RGBA")


def rgba_to_image_tensor(img: Image.Image) -> np.ndarray:
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    rgb *= 1.0 / 255.0
    return rgb


def tint_stamp(stamp: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    """Tint a white+alpha stamp. Shape comes from alpha only."""
    src = stamp if stamp.mode == "RGBA" else stamp.convert("RGBA")
    arr = np.asarray(src)
    out = np.empty(arr.shape, dtype=np.uint8)
    out[..., 0] = rgb[0]
    out[..., 1] = rgb[1]
    out[..., 2] = rgb[2]
    out[..., 3] = arr[..., 3]
    return Image.fromarray(out, mode="RGBA")


def harden_alpha(stamp: Image.Image, cutoff: int = 72) -> Image.Image:
    """Drop faint anti-aliased fringe so a white stamp does not show a dark halo on dark UI."""
    arr = np.array(stamp.convert("RGBA"))
    arr[..., 3] = np.where(arr[..., 3] >= cutoff, 255, 0)
    return Image.fromarray(arr, mode="RGBA")


def crop_opaque(stamp: Image.Image, pad_ratio: float = 0.04) -> Image.Image:
    """Crop transparent padding so the stamp fills the preview."""
    rgba = stamp.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return rgba
    l, t, r, b = bbox
    pad = max(2, int(max(r - l, b - t) * pad_ratio))
    l = max(0, l - pad)
    t = max(0, t - pad)
    r = min(rgba.width, r + pad)
    b = min(rgba.height, b + pad)
    return rgba.crop((l, t, r, b))


def prepare_stamp(preset: str, color_hex: str) -> Image.Image:
    """Tint a built-in preset. Custom stamps go through Stamp Custom Load, not this."""
    cache_key = (str(preset), str(color_hex or "").strip().lower())
    hit = _TINTED_STAMP_CACHE.get(cache_key)
    if hit is None:
        stamp = load_builtin_stamp(preset, copy=False)
        hit = tint_stamp(stamp, parse_hex_color(color_hex))
        _TINTED_STAMP_CACHE[cache_key] = hit
        while len(_TINTED_STAMP_CACHE) > _TINTED_STAMP_CACHE_LIMIT:
            _TINTED_STAMP_CACHE.pop(next(iter(_TINTED_STAMP_CACHE)))
    return hit.copy()


def rotate_stamp(stamp: Image.Image, angle_deg: float) -> Image.Image:
    """Rotate a stamp in degrees, expanding the canvas so corners are not clipped."""
    rgba = stamp if stamp.mode == "RGBA" else stamp.convert("RGBA")
    if abs(float(angle_deg)) < 0.01:
        return rgba
    return rgba.rotate(-float(angle_deg), expand=True, resample=Image.Resampling.BICUBIC)


def _resize_stamp(stamp: Image.Image, size: int) -> Image.Image:
    """Scale stamp so the long side equals size, keeping aspect ratio."""
    w, h = stamp.size
    if w <= 0 or h <= 0:
        return stamp
    size = max(4, int(size))
    if w >= h:
        nw, nh = size, max(1, int(round(h * size / w)))
    else:
        nh, nw = size, max(1, int(round(w * size / h)))
    return stamp.resize((nw, nh), Image.Resampling.LANCZOS)


def _opaque_size(stamp: Image.Image) -> tuple[float, float]:
    """Tight alpha bbox of the unrotated stamp. Used as OBB width/height, not a circle."""
    alpha = stamp.getchannel("A") if stamp.mode in ("RGBA", "LA") else stamp.convert("RGBA").getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        w, h = stamp.size
        return float(max(1, w)), float(max(1, h))
    return float(max(1, bbox[2] - bbox[0])), float(max(1, bbox[3] - bbox[1]))


def _obb_axes_from_cs(c: float, s: float) -> tuple[tuple[float, float], tuple[float, float]]:
    return (c, s), (-s, c)


def _obb_overlap_axes(
    c1x: float,
    c1y: float,
    hw1: float,
    hh1: float,
    u1: tuple[float, float],
    v1: tuple[float, float],
    c2x: float,
    c2y: float,
    hw2: float,
    hh2: float,
    u2: tuple[float, float],
    v2: tuple[float, float],
) -> bool:
    """True if two stamp OBBs overlap. Half-extents are already scaled."""
    dx, dy = c2x - c1x, c2y - c1y
    for ux, uy in (u1, v1, u2, v2):
        r1 = hw1 * abs(u1[0] * ux + u1[1] * uy) + hh1 * abs(v1[0] * ux + v1[1] * uy)
        r2 = hw2 * abs(u2[0] * ux + u2[1] * uy) + hh2 * abs(v2[0] * ux + v2[1] * uy)
        if abs(dx * ux + dy * uy) >= r1 + r2:
            return False
    return True


_DEMO_SCENE_RGB: np.ndarray | None = None
_DEMO_SCENE_WH: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}


def _load_demo_scene_rgb() -> np.ndarray:
    global _DEMO_SCENE_RGB
    if _DEMO_SCENE_RGB is None:
        if not os.path.isfile(DEMO_SCENE_PATH):
            raise FileNotFoundError(f"Missing demo scene: {DEMO_SCENE_PATH}")
        _DEMO_SCENE_RGB = np.asarray(Image.open(DEMO_SCENE_PATH).convert("RGB"), dtype=np.uint8)
    return _DEMO_SCENE_RGB


def make_demo_scene(width: int = 384, height: int = 384) -> tuple[np.ndarray, np.ndarray]:
    """Load the hand-made square demo bars, then scale to the preview size."""
    key = (int(width), int(height))
    hit = _DEMO_SCENE_WH.get(key)
    if hit is None:
        rgb = _load_demo_scene_rgb()
        if rgb.shape[0] != height or rgb.shape[1] != width:
            rgb = np.asarray(
                Image.fromarray(rgb, mode="RGB").resize((width, height), Image.Resampling.NEAREST),
                dtype=np.uint8,
            )
        image = rgb.astype(np.float32) / 255.0
        mask = (image.mean(axis=2) < 0.5).astype(np.float32)
        image[mask > 0.5] = (0.08, 0.08, 0.08)
        hit = (image, mask)
        _DEMO_SCENE_WH[key] = hit
        while len(_DEMO_SCENE_WH) > 4:
            _DEMO_SCENE_WH.pop(next(iter(_DEMO_SCENE_WH)))
    return hit[0], hit[1]


def _mask_bool(mask_hw: np.ndarray, threshold: float = 0.05) -> np.ndarray:
    m = mask_hw.astype(np.float32)
    if m.ndim == 3:
        m = m[..., 0]
    return m > threshold


def iter_connected_regions(mask_bool: np.ndarray) -> Iterable[np.ndarray]:
    """Yield boolean masks for each connected component (4-connected)."""
    try:
        import cv2

        n, labels = cv2.connectedComponents(mask_bool.astype(np.uint8), connectivity=4)
        for i in range(1, n):
            yield labels == i
        return
    except Exception:
        pass

    # Fallback: whole mask as one region
    if mask_bool.any():
        yield mask_bool


# Image space: origin top-left, +x right, +y down.
# Built-in stamps face "up" the image, i.e. from bottom toward top.
STAMP_UP_DIR = (0.0, -1.0)


def _dir_angle_deg(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dy, dx))


def _long_edge_from_points(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    n = int(xs.size)
    if n < 2:
        return (0.0, -1.0)
    if n > 2048:
        step = n // 2048
        xs = xs[::step]
        ys = ys[::step]
        n = int(xs.size)

    pts = np.stack((xs.astype(np.float64, copy=False), ys.astype(np.float64, copy=False)), axis=1)
    centered = pts - pts.mean(axis=0, keepdims=True)
    cov = (centered.T @ centered) / float(max(1, n - 1))
    evals, evecs = np.linalg.eigh(cov)
    if float(evals[-1]) <= 1e-8:
        return (0.0, -1.0)

    dx, dy = float(evecs[0, -1]), float(evecs[1, -1])
    if abs(dx) >= abs(dy):
        if dx < 0.0:
            dx, dy = -dx, -dy
    elif dy > 0.0:
        dx, dy = -dx, -dy
    return (dx, dy)


def _stamp_align_from_points(
    xs: np.ndarray,
    ys: np.ndarray,
    stamp_dir: tuple[float, float] = STAMP_UP_DIR,
) -> float:
    dx, dy = _long_edge_from_points(xs, ys)
    if dx == 0.0 and dy == 0.0:
        return 0.0
    return _dir_angle_deg(dx, dy) - _dir_angle_deg(stamp_dir[0], stamp_dir[1])


def _paste_rgba(base: Image.Image, overlay: Image.Image, cx: int, cy: int) -> None:
    w, h = overlay.size
    x = int(cx - w / 2)
    y = int(cy - h / 2)
    bx1, by1 = max(0, x), max(0, y)
    bx2, by2 = min(base.size[0], x + w), min(base.size[1], y + h)
    if bx1 >= bx2 or by1 >= by2:
        return
    ox1, oy1 = bx1 - x, by1 - y
    crop_over = overlay.crop((ox1, oy1, ox1 + (bx2 - bx1), oy1 + (by2 - by1)))
    crop_base = base.crop((bx1, by1, bx2, by2))
    base.paste(Image.alpha_composite(crop_base, crop_over), (bx1, by1))


def _stamp_alpha(img: Image.Image) -> np.ndarray:
    alpha = np.asarray(img.getchannel("A"), dtype=np.float32)
    alpha *= 1.0 / 255.0
    return alpha


def _overlay_window(
    base_w: int,
    base_h: int,
    sw: int,
    sh: int,
    cx: int,
    cy: int,
) -> tuple[int, int, int, int, int, int] | None:
    x0 = int(cx - sw / 2)
    y0 = int(cy - sh / 2)
    x1 = max(0, x0)
    y1 = max(0, y0)
    x2 = min(base_w, x0 + sw)
    y2 = min(base_h, y0 + sh)
    if x1 >= x2 or y1 >= y2:
        return None
    return x0, y0, x1, y1, x2, y2


def _stamp_coverage_gain(
    coverage: np.ndarray,
    alpha: np.ndarray,
    cx: int,
    cy: int,
    region: np.ndarray,
    region_area: float,
) -> tuple[float, tuple[int, int, int, int, np.ndarray] | None]:
    """New mask coverage (0..1) and the window needed to apply it."""
    if region_area <= 0:
        return 0.0, None
    sh, sw = alpha.shape
    H, W = coverage.shape
    win = _overlay_window(W, H, sw, sh, cx, cy)
    if win is None:
        return 0.0, None
    x0, y0, x1, y1, x2, y2 = win
    sa = alpha[y1 - y0 : y2 - y0, x1 - x0 : x2 - x0]
    newly = (sa > 0.15) & region[y1:y2, x1:x2] & (coverage[y1:y2, x1:x2] < 0.15)
    return float(newly.sum()) / region_area, (y1, y2, x1, x2, sa)


def _apply_coverage_slice(
    coverage: np.ndarray,
    y1: int,
    y2: int,
    x1: int,
    x2: int,
    sa: np.ndarray,
) -> None:
    crop = coverage[y1:y2, x1:x2]
    coverage[y1:y2, x1:x2] = np.maximum(crop, sa)


_DEFAULT_SPACING = 0.3
_DEMO_LAYOUT_CACHE: dict[str, list] = {}
_DEMO_LAYOUT_CACHE_LIMIT = 16


def _stamp_at(
    stamp_rgba: Image.Image,
    size: int,
    angle: float,
    cache: dict,
) -> tuple[Image.Image, np.ndarray]:
    key = (int(size), round(float(angle), 1))
    hit = cache.get(key)
    if hit is None:
        fitted = _resize_stamp(stamp_rgba, size)
        if abs(angle) > 0.01:
            fitted = rotate_stamp(fitted, angle)
        hit = (fitted, _stamp_alpha(fitted))
        cache[key] = hit
    return hit


def replay_stamp_placements(
    canvas: Image.Image,
    stamp_rgba: Image.Image,
    placements: list,
    stamp_angle: float,
    auto_rotate: bool = False,
    stamp_cache: dict | None = None,
) -> None:
    cache = stamp_cache if stamp_cache is not None else {}
    for cx, cy, size, rel_jitter, region_angle, _used_auto in placements:
        extra = float(stamp_angle) + rel_jitter
        angle = (region_angle + extra) if auto_rotate else extra
        stamp, _alpha = _stamp_at(stamp_rgba, int(size), angle, cache)
        _paste_rgba(canvas, stamp, int(round(cx)), int(round(cy)))


def fill_region_with_stamps(
    canvas: Image.Image,
    region: np.ndarray,
    stamp_rgba: Image.Image,
    *,
    target_coverage: float,
    size_ratio: float,
    min_size: int,
    max_size: int,
    spacing_factor: float,
    size_jitter: float,
    angle_jitter: float,
    auto_rotate: bool,
    stamp_angle: float,
    rng: np.random.Generator,
    max_stamps: int = 400,
    max_attempts: int = 2500,
    stamp_cache: dict | None = None,
    out_placements: list | None = None,
) -> float:
    ys, xs = np.where(region)
    region_area = float(xs.size)
    if region_area < 16:
        return 0.0
    long_side = max(int(xs.max()) - int(xs.min()) + 1, int(ys.max()) - int(ys.min()) + 1)
    lo = max(4, int(min_size))
    hi = max(lo, int(max_size))
    base_size = int(round(long_side * float(size_ratio)))
    base_size = lo if base_size < lo else (hi if base_size > hi else base_size)

    # Always keep the mask long-axis so toggling auto_rotate can replay without re-layout.
    region_angle = _stamp_align_from_points(xs, ys)
    base_angle = (region_angle + float(stamp_angle)) if auto_rotate else float(stamp_angle)

    src_w, src_h = _opaque_size(stamp_rgba)
    src_long = max(src_w, src_h, 1.0)
    cache = stamp_cache if stamp_cache is not None else {}

    H, W = region.shape
    coverage = np.zeros((H, W), dtype=np.float32)
    placed_boxes: list[tuple[float, float, float, float, tuple, tuple]] = []
    placed = 0
    attempts = 0
    covered = 0.0
    target = target_coverage if 0.05 <= target_coverage <= 1.0 else min(1.0, max(0.05, float(target_coverage)))

    jitter = max(0.0, float(size_jitter))
    ang_j = max(0.0, float(angle_jitter))
    spacing_k = max(0.0, float(spacing_factor))
    n_pts = xs.size

    while placed < max_stamps and attempts < max_attempts:
        attempts += 1
        scale = 1.0
        if jitter > 0:
            scale = float(rng.uniform(max(0.05, 1.0 - jitter), 1.0 + jitter))
        size = int(round(base_size * scale))
        if size < 4:
            size = 4
        elif size > hi:
            size = hi
        angle = base_angle
        if ang_j > 0:
            angle = base_angle + float(rng.uniform(-ang_j, ang_j))

        idx = int(rng.integers(0, n_pts))
        cx, cy = int(xs[idx]), int(ys[idx])

        ratio = size / src_long
        cw, ch = src_w * ratio + 1.0, src_h * ratio + 1.0

        if spacing_k > 0.0:
            rad = math.radians(angle)
            u, v = _obb_axes_from_cs(math.cos(rad), math.sin(rad))
            hw, hh = 0.5 * cw * spacing_k, 0.5 * ch * spacing_k
            blocked = False
            for px, py, phw, phh, pu, pv in placed_boxes:
                if _obb_overlap_axes(cx, cy, hw, hh, u, v, px, py, phw, phh, pu, pv):
                    blocked = True
                    break
            if blocked:
                continue
        else:
            u = v = None
            hw = hh = 0.0

        stamp, alpha = _stamp_at(stamp_rgba, size, angle, cache)
        gain, slice_win = _stamp_coverage_gain(coverage, alpha, cx, cy, region, region_area)
        if gain <= 0 and placed > 0:
            continue

        _paste_rgba(canvas, stamp, cx, cy)
        if slice_win is not None:
            _apply_coverage_slice(coverage, *slice_win)
        if spacing_k > 0.0 and u is not None:
            placed_boxes.append((float(cx), float(cy), hw, hh, u, v))
        if out_placements is not None:
            out_placements.append((
                float(cx),
                float(cy),
                int(size),
                float(angle - base_angle),
                float(region_angle),
                bool(auto_rotate),
            ))
        placed += 1
        covered += gain
        if covered >= target:
            break

    return covered


def stamp_censor_image(
    image_hwc: np.ndarray,
    mask_hw: np.ndarray,
    stamp: Image.Image,
    *,
    target_coverage: float = 0.8,
    size_ratio: float = 0.28,
    min_size: int = 24,
    max_size: int = 512,
    spacing_factor: float = _DEFAULT_SPACING,
    size_jitter: float = 0.15,
    angle_jitter: float = 0.0,
    auto_rotate: bool = True,
    stamp_angle: float = 0.0,
    seed: int = 0,
    preview: bool = False,
    out_placements: list | None = None,
) -> tuple[np.ndarray, float]:
    base = image_tensor_to_rgba(image_hwc)
    stamp_rgba = stamp if stamp.mode == "RGBA" else stamp.convert("RGBA")

    mask_bool = _mask_bool(mask_hw)
    if not mask_bool.any():
        return rgba_to_image_tensor(base), 0.0

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    stamp_cache: dict = {}
    limits = (80, 500) if preview else (400, 2500)
    target = float(target_coverage)
    if target < 0.05:
        target = 0.05
    elif target > 1.0:
        target = 1.0
    coverages: list[float] = []
    for region in iter_connected_regions(mask_bool):
        cov = fill_region_with_stamps(
            base,
            region,
            stamp_rgba,
            target_coverage=target,
            size_ratio=size_ratio,
            min_size=min_size,
            max_size=max_size,
            spacing_factor=spacing_factor,
            size_jitter=size_jitter,
            angle_jitter=angle_jitter,
            auto_rotate=bool(auto_rotate),
            stamp_angle=float(stamp_angle),
            rng=rng,
            max_stamps=limits[0],
            max_attempts=limits[1],
            stamp_cache=stamp_cache,
            out_placements=out_placements,
        )
        coverages.append(cov)

    avg = float(np.mean(coverages)) if coverages else 0.0
    return rgba_to_image_tensor(base), avg


def render_demo_preview(
    stamp: Image.Image,
    *,
    target_coverage: float = 0.8,
    size_ratio: float = 0.28,
    min_size: int = 24,
    max_size: int = 512,
    spacing_factor: float = _DEFAULT_SPACING,
    size_jitter: float = 0.15,
    angle_jitter: float = 0.0,
    auto_rotate: bool = True,
    stamp_angle: float = 0.0,
    seed: int = 0,
    width: int = 384,
    height: int = 384,
    layout_key: str = "",
    reuse_layout: bool = False,
) -> np.ndarray:
    """White background + black bar mask with stamps applied (preview helper)."""
    image, mask = make_demo_scene(width, height)
    cached = _DEMO_LAYOUT_CACHE.get(layout_key) if reuse_layout and layout_key else None
    if cached is not None:
        canvas = image_tensor_to_rgba(image)
        replay_stamp_placements(
            canvas,
            stamp if stamp.mode == "RGBA" else stamp.convert("RGBA"),
            cached,
            stamp_angle,
            auto_rotate=bool(auto_rotate),
        )
        return rgba_to_image_tensor(canvas)

    placements: list = []
    out, _ = stamp_censor_image(
        image,
        mask,
        stamp,
        target_coverage=target_coverage,
        size_ratio=size_ratio,
        min_size=min_size,
        max_size=max_size,
        spacing_factor=spacing_factor,
        size_jitter=size_jitter,
        angle_jitter=angle_jitter,
        auto_rotate=auto_rotate,
        stamp_angle=stamp_angle,
        seed=seed,
        preview=True,
        out_placements=placements,
    )
    if layout_key:
        if layout_key in _DEMO_LAYOUT_CACHE:
            _DEMO_LAYOUT_CACHE.pop(layout_key, None)
        _DEMO_LAYOUT_CACHE[layout_key] = placements
        while len(_DEMO_LAYOUT_CACHE) > _DEMO_LAYOUT_CACHE_LIMIT:
            _DEMO_LAYOUT_CACHE.pop(next(iter(_DEMO_LAYOUT_CACHE)))
    return out
