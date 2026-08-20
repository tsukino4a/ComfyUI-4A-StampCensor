"""Core stamp placement / compositing for 4A StampCensor."""

from __future__ import annotations

import logging
import math
import os
import re
from contextlib import contextmanager
from typing import Iterable

import numpy as np
from PIL import Image

logger = logging.getLogger("ComfyUI-4A-StampCensor")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
DEMO_SCENE_NAME = "demo_scene.png"
DEMO_SCENE_PATH = os.path.join(ASSETS_DIR, DEMO_SCENE_NAME)

_PRESET_ORDER = [
    "heart_solid",
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
    """Turn folder presets into white RGB + alpha. Other RGBA images pass through."""
    kind, arr = _inspect_stamp(im)
    if kind not in _STAMP_KINDS:
        return im.convert("RGBA")
    return _to_white_alpha(kind, arr)


def as_is_stamp_rgba(im: Image.Image) -> Image.Image:
    """Custom Load: keep the dropped image unchanged, including white backgrounds."""
    return im.convert("RGBA")


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
    for name in ("heart_solid", "heart_wobbly_a"):
        if name in BUILTIN_STAMPS:
            return name
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


class _RegionAxes:
    """PCA frame of a mask component: long axis u, short axis v."""

    __slots__ = (
        "ux", "uy", "vx", "vy", "cx0", "cy0",
        "du", "dv", "u_min", "u_max", "v_min", "v_max",
        "length", "width", "region_angle",
    )

    def __init__(self, xs: np.ndarray, ys: np.ndarray):
        dx, dy = _long_edge_from_points(xs, ys)
        nrm = math.hypot(dx, dy) or 1.0
        self.ux, self.uy = dx / nrm, dy / nrm
        self.vx, self.vy = -self.uy, self.ux
        xf = xs.astype(np.float64)
        yf = ys.astype(np.float64)
        self.cx0 = float(xf.mean())
        self.cy0 = float(yf.mean())
        self.du = (xf - self.cx0) * self.ux + (yf - self.cy0) * self.uy
        self.dv = (xf - self.cx0) * self.vx + (yf - self.cy0) * self.vy
        self.u_min = float(self.du.min())
        self.u_max = float(self.du.max())
        self.v_min = float(self.dv.min())
        self.v_max = float(self.dv.max())
        self.length = (self.u_max - self.u_min) + 1.0
        self.width = (self.v_max - self.v_min) + 1.0
        self.region_angle = _dir_angle_deg(dx, dy) - _dir_angle_deg(
            STAMP_UP_DIR[0], STAMP_UP_DIR[1]
        )

    @property
    def aspect(self) -> float:
        return self.length / max(self.width, 1.0)

    def to_xy(self, u: float, v: float) -> tuple[int, int]:
        return (
            int(round(self.cx0 + u * self.ux + v * self.vx)),
            int(round(self.cy0 + u * self.uy + v * self.vy)),
        )


def _stamp_align_from_points(
    xs: np.ndarray,
    ys: np.ndarray,
    stamp_dir: tuple[float, float] = STAMP_UP_DIR,
) -> float:
    dx, dy = _long_edge_from_points(xs, ys)
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
_MIN_REGION_RATIO = 0.00025
_MIN_REGION_FLOOR = 16
_ORGANIC_SLICE_PX = 3.5
_ORGANIC_MIN_ASPECT = 2.0
_GAP_WIDTH_SCALE = 1.5
_COVER_SLACK = 0.20
_OPAQUE = 0.15
_END_OUTSIDE = 0.15


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


def _distance_transform(region: np.ndarray) -> np.ndarray:
    """Euclidean distance from each mask pixel to the background."""
    mask_u8 = region.astype(np.uint8)
    try:
        import cv2

        return cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5).astype(np.float32)
    except Exception:
        pass
    try:
        from scipy.ndimage import distance_transform_edt

        return distance_transform_edt(mask_u8).astype(np.float32)
    except Exception:
        pass
    # Coarse fallback: downsample, nearest-background, upsample.
    H, W = region.shape
    step = max(1, int(round(min(H, W) / 160)))
    small = region[::step, ::step]
    sh, sw = small.shape
    bg = np.column_stack(np.where(~small))
    if bg.size == 0:
        return np.full((H, W), float(min(H, W)), dtype=np.float32)
    out = np.zeros((sh, sw), dtype=np.float32)
    fg = np.column_stack(np.where(small))
    for y, x in fg:
        d = (bg[:, 0] - y) ** 2 + (bg[:, 1] - x) ** 2
        out[y, x] = math.sqrt(float(d.min())) * step
    return np.asarray(
        Image.fromarray(out, mode="F").resize((W, H), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )


def _stamp_place_stats(
    alpha: np.ndarray,
    cx: int,
    cy: int,
    region: np.ndarray,
    coverage: np.ndarray,
) -> tuple[float, float, int, tuple[int, int, int, int, np.ndarray] | None]:
    """Return (outside_frac, overlap_frac, newly_px, slice) for a candidate paste."""
    full_n = int((alpha > _OPAQUE).sum())
    if full_n <= 0:
        return 1.0, 1.0, 0, None
    sh, sw = alpha.shape
    H, W = region.shape
    win = _overlay_window(W, H, sw, sh, cx, cy)
    if win is None:
        return 1.0, 1.0, 0, None
    x0, y0, x1, y1, x2, y2 = win
    sa = alpha[y1 - y0 : y2 - y0, x1 - x0 : x2 - x0]
    opaque = sa > _OPAQUE
    vis_n = int(opaque.sum())
    inside = opaque & region[y1:y2, x1:x2]
    inside_n = int(inside.sum())
    outside_frac = float(full_n - inside_n) / float(full_n)
    if vis_n <= 0 or inside_n <= 0:
        return outside_frac, 1.0, 0, (y1, y2, x1, x2, sa)
    already = int((opaque & (coverage[y1:y2, x1:x2] > _OPAQUE)).sum())
    newly = inside_n - int((inside & (coverage[y1:y2, x1:x2] > _OPAQUE)).sum())
    overlap_frac = float(already) / float(vis_n)
    return outside_frac, overlap_frac, newly, (y1, y2, x1, x2, sa)


def _v_groups(dv: np.ndarray, gap: float = 8.0) -> list[np.ndarray]:
    """Split a scan band into blobs along the short axis."""
    if dv.size == 0:
        return []
    order = np.argsort(dv, kind="mergesort")
    v_sorted = dv[order]
    cuts = [0]
    for i in range(1, int(v_sorted.size)):
        if float(v_sorted[i] - v_sorted[i - 1]) > gap:
            cuts.append(i)
    cuts.append(int(v_sorted.size))
    groups = []
    for a, b in zip(cuts, cuts[1:]):
        if b > a:
            groups.append(order[a:b])
    return groups


def _scan_groups(du: np.ndarray, dv: np.ndarray, t: float, slice_h: float) -> list[np.ndarray]:
    idx = np.flatnonzero((du >= t - slice_h) & (du < t + slice_h))
    if idx.size == 0:
        return []
    return [idx[g] for g in _v_groups(dv[idx], gap=6.0)]


def _group_width(dv: np.ndarray, g_i: np.ndarray) -> float:
    if g_i.size == 0:
        return 0.0
    return float(dv[g_i].max() - dv[g_i].min()) + 1.0


def _long_end_inward(fu: float, axes: _RegionAxes) -> tuple[float, float] | None:
    if fu <= 0.04:
        return (axes.ux, axes.uy)
    if fu >= 0.96:
        return (-axes.ux, -axes.uy)
    return None


def _gap_u_sites(hits: list[float]) -> list[float]:
    if not hits:
        return []
    hs = sorted(hits)
    sites = [0.5 * (a + b) for a, b in zip(hs, hs[1:]) if (b - a) >= 6.0]
    if len(hs) == 1:
        sites.append(hs[0])
    return sites


def _gap_sides(
    g: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    dv: np.ndarray,
    coverage: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    v_c = float(dv[g].mean())
    uncovered = coverage[ys[g], xs[g]] < _OPAQUE
    return g[uncovered & (dv[g] < v_c)], g[uncovered & (dv[g] > v_c)]


def _pick_spread_site(remaining: list[float], placed: list[float], mid: float) -> float:
    """Next candidate: closest to mid if empty, else farthest from already placed sites."""
    if not placed:
        return min(remaining, key=lambda t: abs(t - mid))
    return max(remaining, key=lambda t: min(abs(t - p) for p in placed))


def _pack_axis_fracs(n: int) -> list[float]:
    """1: mid. 2: half-split. Odd: 0.5 then 0/1 then gap mids. Even >=4: include both ends."""
    n = max(1, int(n))
    if n == 1:
        return [0.5]
    if n == 2:
        return [0.25, 0.75]
    if n % 2 == 0:
        return [i / float(n - 1) for i in range(n)]
    pts = [0.5, 0.0, 1.0]
    while len(pts) < n:
        ordered = sorted(pts)
        mids = [0.5 * (ordered[i] + ordered[i + 1]) for i in range(len(ordered) - 1)]
        need = n - len(pts)
        if len(mids) <= need:
            pts.extend(mids)
            continue
        take: list[float] = []
        i, j = 0, len(mids) - 1
        while len(take) < need and i < j:
            take.append(mids[i])
            take.append(mids[j])
            i += 1
            j -= 1
        pts.extend(take[:need])
    return sorted(pts)


def _equal_axis_stations(u_min: float, u_max: float, n: int, half: float) -> list[float]:
    """Pack n sites along the long axis, inset by half a stamp."""
    start = u_min + half
    end = u_max - half
    mid = 0.5 * (u_min + u_max)
    n = max(1, int(n))
    if n == 1 or end <= start + 1e-6:
        return [mid]
    span = end - start
    return [start + f * span for f in _pack_axis_fracs(n)]


def _pick_spread_uv(
    remaining: list[tuple[float, float]],
    placed: list[tuple[float, float]],
) -> tuple[float, float]:
    if not placed:
        return min(remaining, key=lambda p: math.hypot(p[0] - 0.5, p[1] - 0.5))
    return max(
        remaining,
        key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in placed),
    )


def _area_grid_shape(n: int, aspect: float) -> tuple[int, int]:
    """(rows, cols) with cols along the long axis. Allows a slightly larger grid."""
    aspect = max(1.0, float(aspect))
    best = (1, n)
    best_score = 1e9
    for rows in range(1, n + 1):
        for cols in range(1, n + 1):
            prod = rows * cols
            if prod < n:
                continue
            ratio = cols / float(rows)
            score = abs(math.log(max(ratio, 1e-6) / aspect)) + 0.35 * (prod - n)
            if cols < rows:
                score += 1.5
            if score < best_score:
                best_score = score
                best = (rows, cols)
    return best


def _take_symmetric_fracs(
    pts: list[tuple[float, float]],
    n: int,
) -> list[tuple[float, float]]:
    remaining = list(pts)
    placed: list[tuple[float, float]] = []
    n = max(1, min(int(n), len(pts)))

    def _next() -> tuple[float, float]:
        if not placed:
            if n % 2 == 1:
                return min(remaining, key=lambda q: math.hypot(q[0] - 0.5, q[1] - 0.5))
            return max(remaining, key=lambda q: math.hypot(q[0] - 0.5, q[1] - 0.5))
        return _pick_spread_uv(remaining, placed)

    while remaining and len(placed) < n:
        p = _next()
        remaining.remove(p)
        placed.append(p)
        if len(placed) >= n or not remaining:
            break
        twin_t = (1.0 - p[0], 1.0 - p[1])
        twin = min(remaining, key=lambda q: math.hypot(q[0] - twin_t[0], q[1] - twin_t[1]))
        if math.hypot(twin[0] - twin_t[0], twin[1] - twin_t[1]) <= 0.15:
            remaining.remove(twin)
            placed.append(twin)
    return placed[:n]


def _area_frac_sites(n: int, aspect: float) -> list[tuple[float, float]]:
    """2D pack in [0, 1]^2 (u along long axis). 1:1 uses corners / plus, not a 1D row."""
    n = max(1, int(n))
    if n == 1:
        return [(0.5, 0.5)]
    if n == 2:
        return [(0.25, 0.5), (0.75, 0.5)]
    if n == 3:
        return [(0.0, 0.5), (0.5, 0.5), (1.0, 0.5)]
    if n == 4:
        return [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    if n == 5:
        return [(0.5, 0.5), (0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)]
    rows, cols = _area_grid_shape(n, aspect)
    pts = [(u, v) for v in _pack_axis_fracs(rows) for u in _pack_axis_fracs(cols)]
    if len(pts) == n:
        return pts
    if n == 8 and (0.5, 0.5) in pts and len(pts) == 9:
        return [p for p in pts if p != (0.5, 0.5)]
    return _take_symmetric_fracs(pts, n)


def _area_candidate_fracs(aspect: float) -> list[tuple[float, float]]:
    seen: set[tuple[float, float]] = set()
    out: list[tuple[float, float]] = []
    for k in (1, 2, 3, 4, 5, 6, 8, 9, 12, 16):
        for p in _area_frac_sites(k, aspect):
            key = (round(p[0], 4), round(p[1], 4))
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out


def _area_ring(u0: float, v0: float, eu: float, ev: float) -> list[tuple[float, float]]:
    return [
        (u0 + eu, v0),
        (u0 - eu, v0),
        (u0 + 0.5 * eu, v0 + ev),
        (u0 - 0.5 * eu, v0 + ev),
        (u0 + 0.5 * eu, v0 - ev),
        (u0 - 0.5 * eu, v0 - ev),
    ]


def _clamp_coverage(target: float) -> float:
    t = float(target)
    if t < 0.05:
        return 0.05
    if t > 1.0:
        return 1.0
    return t


def _uniform_knobs(
    *,
    target_coverage: float,
    size_ratio: float,
    min_size: int,
    max_size: int,
    spacing_factor: float,
    size_jitter: float,
    angle_jitter: float,
) -> tuple[int, int, float, float, float, float, float, float]:
    lo = max(4, int(min_size))
    hi = max(lo, int(max_size))
    target = _clamp_coverage(target_coverage)
    jitter = max(0.0, float(size_jitter))
    ang_j = max(0.0, float(angle_jitter))
    width_ratio = min(2.0, max(0.0, float(size_ratio)))
    sp_k = min(2.5, max(0.0, float(spacing_factor)))
    overlap_lim = 0.0 if sp_k >= 1.0 else (1.0 - sp_k)
    sep_mul = sp_k if sp_k > 1.0 else 0.0
    return lo, hi, target, jitter, ang_j, width_ratio, overlap_lim, sep_mul


def _uniform_base_angle(axes: _RegionAxes, auto_rotate: bool, stamp_angle: float) -> float:
    extra = float(stamp_angle)
    return (axes.region_angle + extra) if auto_rotate else extra


def _src_metrics(stamp_rgba: Image.Image) -> tuple[float, float, float]:
    src_ow, src_oh = _opaque_size(stamp_rgba)
    src_cw, src_ch = stamp_rgba.size
    src_long = max(float(src_cw), float(src_ch), 1.0)
    return max(float(src_ow), 1.0), max(float(src_oh), 1.0), src_long


def _clip_stamp_size(raw: float, lo: int, hi: int) -> int:
    fit = min(raw, float(hi))
    cap = min(float(hi), max(4.0, raw * 1.02))
    size = int(round(min(max(fit, min(float(lo), cap)), cap)))
    return max(4, size)


def _stamp_extents(
    size: int,
    src_long: float,
    opaque_w: float,
    opaque_h: float,
    auto_rotate: bool,
) -> tuple[float, float]:
    ratio = float(max(4, int(size))) / src_long
    if auto_rotate:
        return opaque_h * ratio, opaque_w * ratio
    span = max(opaque_w, opaque_h) * ratio
    return span, span


class _StampPlacer:
    """Shared paste / coverage / overlap gate for even-pack layouts."""

    __slots__ = (
        "canvas", "region", "stamp_rgba", "region_area",
        "base_angle", "rng", "ang_j", "overlap_lim", "sep_mul",
        "max_stamps", "stamp_cache", "target",
        "coverage", "covered", "placed", "placed_xy", "extra_left", "layer_open",
    )

    def __init__(
        self,
        canvas: Image.Image,
        region: np.ndarray,
        stamp_rgba: Image.Image,
        region_area: float,
        *,
        base_angle: float,
        rng: np.random.Generator,
        ang_j: float,
        overlap_lim: float,
        sep_mul: float,
        max_stamps: int,
        stamp_cache: dict,
        target: float,
    ):
        self.canvas = canvas
        self.region = region
        self.stamp_rgba = stamp_rgba
        self.region_area = region_area
        self.base_angle = base_angle
        self.rng = rng
        self.ang_j = ang_j
        self.overlap_lim = overlap_lim
        self.sep_mul = float(sep_mul)
        self.max_stamps = max_stamps
        self.stamp_cache = stamp_cache
        self.target = target
        self.coverage = np.zeros(region.shape, dtype=np.float32)
        self.covered = 0.0
        self.placed = 0
        self.placed_xy: list[tuple[float, float, float]] = []
        self.extra_left = 0
        self.layer_open = False

    def can_place(self) -> bool:
        if self.placed >= self.max_stamps:
            return False
        return self.covered < self.target or self.extra_left > 0 or self.layer_open

    def maybe_bonus_stamp(self) -> bool:
        """One extra paste if a single stamp landed just over the coverage target."""
        if self.placed == 1 and self.target <= self.covered < self.target + _COVER_SLACK:
            self.extra_left = 1
            return True
        return False

    def commit(
        self,
        cx: int,
        cy: int,
        size: int,
        *,
        sep_ext: float | None = None,
        inward: tuple[float, float] | None = None,
    ) -> bool:
        if self.placed >= self.max_stamps:
            return False
        if self.covered >= self.target and self.extra_left <= 0 and not self.layer_open:
            return False
        ext = float(size) if sep_ext is None else max(1.0, float(sep_ext))
        if self.sep_mul > 1.0:
            for px, py, pext in self.placed_xy:
                need = 0.5 * (ext + pext) * self.sep_mul
                if math.hypot(float(cx) - px, float(cy) - py) < need - 1e-6:
                    return False
        angle = self.base_angle + (
            float(self.rng.uniform(-self.ang_j, self.ang_j)) if self.ang_j > 0 else 0.0
        )
        stamp, alpha = _stamp_at(self.stamp_rgba, size, angle, self.stamp_cache)
        outside_frac, overlap_frac, newly, slice_win = _stamp_place_stats(
            alpha, cx, cy, self.region, self.coverage
        )
        if inward is not None and outside_frac > _END_OUTSIDE:
            dx, dy = float(inward[0]), float(inward[1])
            nlen = math.hypot(dx, dy)
            if nlen > 1e-6:
                dx, dy = dx / nlen, dy / nlen
                H, W = self.region.shape
                max_d = max(12.0, 0.75 * ext)
                step = max(4.0, 0.10 * ext)
                best_xy = (cx, cy)
                best_out = outside_frac
                best_stats = (outside_frac, overlap_frac, newly, slice_win)
                travel = 0.0
                while travel + step <= max_d + 1e-6:
                    travel += step
                    nx = int(round(cx + dx * travel))
                    ny = int(round(cy + dy * travel))
                    if nx < 0 or ny < 0 or nx >= W or ny >= H or not self.region[ny, nx]:
                        continue
                    stats = _stamp_place_stats(alpha, nx, ny, self.region, self.coverage)
                    if stats[0] + 1e-6 < best_out:
                        best_out = stats[0]
                        best_xy = (nx, ny)
                        best_stats = stats
                    if best_out <= _END_OUTSIDE:
                        break
                cx, cy = best_xy
                outside_frac, overlap_frac, newly, slice_win = best_stats
        if outside_frac >= 1.0 - 1e-6:
            return False
        if newly <= 0 and self.overlap_lim <= 1e-6:
            return False
        if overlap_frac > self.overlap_lim + 1e-6:
            return False
        used_bonus = self.covered >= self.target and not self.layer_open
        _paste_rgba(self.canvas, stamp, cx, cy)
        if slice_win is not None:
            _apply_coverage_slice(self.coverage, *slice_win)
        self.placed_xy.append((float(cx), float(cy), ext))
        self.placed += 1
        self.covered += float(newly) / self.region_area
        if used_bonus:
            self.extra_left = max(0, self.extra_left - 1)
        return True

    @contextmanager
    def open_layer(self):
        self.layer_open = True
        try:
            yield
        finally:
            self.layer_open = False

    def jitter_size(self, base: int, lo: int, hi: int, jitter: float) -> int:
        fit = float(base)
        if jitter > 0:
            fit *= float(self.rng.uniform(max(0.08, 1.0 - jitter), 1.0 + jitter))
        cap = min(float(hi), max(4.0, float(base) * 1.08))
        size = int(round(min(max(fit, min(float(lo), cap)), cap)))
        return max(4, size)


def _probe_even_n(rng: np.random.Generator, make_placer, canvas: Image.Image, run) -> int:
    """Count stamps on a throwaway canvas, then restore rng so the real pass matches."""
    state = rng.bit_generator.state
    ghost = make_placer(Image.new("RGBA", canvas.size, (0, 0, 0, 0)))
    run(ghost)
    n = max(1, ghost.placed)
    if ghost.placed == 1 and ghost.target <= ghost.covered < ghost.target + _COVER_SLACK:
        n = 2
    rng.bit_generator.state = state
    return n


def _fill_region_organic(
    canvas: Image.Image,
    region: np.ndarray,
    stamp_rgba: Image.Image,
    xs: np.ndarray,
    ys: np.ndarray,
    region_area: float,
    axes: _RegionAxes,
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
    max_stamps: int,
    stamp_cache: dict,
) -> float:
    """Scan along the mask long axis; size from local width; stagger fill between hits."""
    lo, hi, target, jitter, ang_j, width_ratio, overlap_lim, sep_mul = _uniform_knobs(
        target_coverage=target_coverage,
        size_ratio=size_ratio,
        min_size=min_size,
        max_size=max_size,
        spacing_factor=spacing_factor,
        size_jitter=size_jitter,
        angle_jitter=angle_jitter,
    )
    base_angle = _uniform_base_angle(axes, auto_rotate, stamp_angle)

    def _make_placer(dest: Image.Image) -> _StampPlacer:
        return _StampPlacer(
            dest, region, stamp_rgba, region_area,
            base_angle=base_angle,
            rng=rng,
            ang_j=ang_j,
            overlap_lim=overlap_lim,
            sep_mul=sep_mul,
            max_stamps=max_stamps,
            stamp_cache=stamp_cache,
            target=target,
        )

    placer = _make_placer(canvas)
    du, dv = axes.du, axes.dv
    u_min, u_max = axes.u_min, axes.u_max
    slice_h = _ORGANIC_SLICE_PX
    opaque_w, opaque_h, src_long = _src_metrics(stamp_rgba)

    dist = _distance_transform(region)
    region_r = float(dist.max()) if dist.size else 1.0
    region_big = min(axes.width * src_long / opaque_w * width_ratio, float(hi))
    large_floor = max(12, int(round(0.45 * region_big))) if region_r < 42.0 else 12

    def _ext_u(size: int) -> float:
        return _stamp_extents(size, src_long, opaque_w, opaque_h, auto_rotate)[0]

    def _size_from_width(width: float) -> int:
        full = max(1.0, width) * src_long / opaque_w * width_ratio
        fit = min(full, float(hi))
        if jitter > 0:
            fit *= float(rng.uniform(max(0.08, 1.0 - jitter), 1.0 + jitter))
        cap = min(float(hi), max(4.0, full * 1.02))
        size = int(round(min(max(fit, min(float(lo), cap)), cap)))
        return max(4, size)

    def _size_for(g_i: np.ndarray) -> int:
        if g_i.size == 0:
            return max(4, min(lo, hi))
        return _size_from_width(_group_width(dv, g_i))

    def _medial(g_i: np.ndarray) -> tuple[int, int]:
        return int(round(float(xs[g_i].mean()))), int(round(float(ys[g_i].mean())))

    def _slide_place(p: _StampPlacer, g: np.ndarray, size: int) -> bool:
        n = int(g.size)
        if n <= 0:
            return False
        order = np.argsort(dv[g], kind="mergesort")
        n_s = max(7, min(17, n // 4 + 3))
        picks = np.linspace(0, n - 1, num=n_s).astype(np.int32)
        best = None
        best_ov = 1.0
        gi_x = xs[g]
        gi_y = ys[g]
        for k in picks:
            i = int(order[int(k)])
            px = int(gi_x[i])
            py = int(gi_y[i])
            stamp, alpha = _stamp_at(stamp_rgba, size, base_angle, stamp_cache)
            outside_frac, overlap_frac, newly, _sl = _stamp_place_stats(
                alpha, px, py, region, p.coverage
            )
            if outside_frac >= 1.0 - 1e-6:
                continue
            if newly <= 0 and overlap_lim <= 1e-6:
                continue
            if overlap_frac < best_ov:
                best_ov = overlap_frac
                best = (px, py)
        if best is not None and best_ov <= overlap_lim + 1e-6:
            return p.commit(best[0], best[1], size, sep_ext=_ext_u(size))
        return False

    def _place_group(
        p: _StampPlacer,
        g: np.ndarray,
        min_keep: int = 12,
        slide: bool = False,
        size: int | None = None,
        inward: tuple[float, float] | None = None,
    ) -> bool:
        if g.size < 12:
            return False
        if float(dist[ys[g], xs[g]].max()) < 5.0:
            return False
        use = int(size) if size is not None else _size_for(g)
        if use < max(12, int(min_keep)):
            return False
        cx, cy = _medial(g)
        if p.commit(cx, cy, use, sep_ext=_ext_u(use), inward=inward):
            return True
        if slide:
            return _slide_place(p, g, use)
        return False

    probe_groups = _scan_groups(du, dv, 0.5 * (u_min + u_max), slice_h)
    probe_size = _size_for(probe_groups[0]) if probe_groups else max(24, lo)
    probe_ext = max(8.0, _ext_u(probe_size))
    step0 = max(4.0, probe_ext)
    half = 0.5 * min(probe_ext, step0)
    start = u_min + half
    end = u_max - half
    if end <= start + 1e-6:
        stations = [0.5 * (u_min + u_max)]
    else:
        n_st = max(1, int(math.floor((end - start) / step0 + 1e-6)) + 1)
        if n_st == 1:
            stations = [0.5 * (u_min + u_max)]
        else:
            gap = (end - start) / float(n_st - 1)
            stations = [start + i * gap for i in range(n_st)]
    mid_u = 0.5 * (u_min + u_max)

    def _end_inward(t: float) -> tuple[float, float] | None:
        span = end - start
        if span <= 1e-6:
            return None
        return _long_end_inward((t - start) / span, axes)

    def _place_station(p: _StampPlacer, t: float) -> bool:
        groups = _scan_groups(du, dv, t, slice_h)
        inward = _end_inward(t)
        placed_here = False
        for g in groups:
            size = _size_for(g)
            n0 = p.placed
            _place_group(p, g, min_keep=large_floor, slide=False, size=size, inward=inward)
            if p.placed > n0:
                placed_here = True
        return placed_here

    def _probe(ghost: _StampPlacer) -> None:
        remaining = list(stations)
        placed_u: list[float] = []
        while remaining and ghost.placed < max_stamps and ghost.covered < target:
            t = _pick_spread_site(remaining, placed_u, mid_u)
            remaining.remove(t)
            if _place_station(ghost, t):
                placed_u.append(t)

    n_eq = _probe_even_n(rng, _make_placer, canvas, _probe)

    hits: list[float] = []
    eq_stations = _equal_axis_stations(u_min, u_max, n_eq, half)
    with placer.open_layer():
        for t in eq_stations:
            if placer.placed >= max_stamps:
                break
            if _place_station(placer, t):
                hits.append(t)

    def _gap_size(side: np.ndarray, cap_g: np.ndarray) -> int | None:
        if side.size < 12:
            return None
        cap_w = _group_width(dv, cap_g) if cap_g.size else _group_width(dv, side) * _GAP_WIDTH_SCALE
        gap_w = min(_group_width(dv, side) * _GAP_WIDTH_SCALE, cap_w)
        return _size_from_width(gap_w)

    def _fill_gaps_at(t: float) -> None:
        with placer.open_layer():
            for g in _scan_groups(du, dv, t, slice_h):
                for side in _gap_sides(g, xs, ys, dv, placer.coverage):
                    if placer.placed >= max_stamps:
                        return
                    sz = _gap_size(side, g)
                    if sz is None:
                        continue
                    _place_group(placer, side, min_keep=large_floor, slide=True, size=sz)

    gap_sites = _gap_u_sites(hits)
    if placer.covered < target and placer.placed < max_stamps:
        for t_gap in gap_sites:
            if placer.placed >= max_stamps or placer.covered >= target:
                break
            _fill_gaps_at(t_gap)

    if placer.maybe_bonus_stamp():
        bonus_sites = _equal_axis_stations(u_min, u_max, max(2, n_eq + 1), half)
        seen = set(round(x, 2) for x in hits)
        for t in bonus_sites:
            if placer.extra_left <= 0 or placer.placed >= max_stamps:
                break
            if round(t, 2) in seen:
                continue
            if _place_station(placer, t):
                hits.append(t)
        if placer.extra_left > 0:
            extra_sites = gap_sites if gap_sites else [mid_u]
            for t_gap in extra_sites:
                if placer.extra_left <= 0 or placer.placed >= max_stamps:
                    break
                _fill_gaps_at(t_gap)

    return placer.covered


def _fill_region_area(
    canvas: Image.Image,
    region: np.ndarray,
    stamp_rgba: Image.Image,
    xs: np.ndarray,
    ys: np.ndarray,
    region_area: float,
    axes: _RegionAxes,
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
    max_stamps: int,
    stamp_cache: dict,
) -> float:
    """Squat / 1:1 regions: size from the short axis, then 2D end-aware pack."""
    lo, hi, target, jitter, ang_j, width_ratio, overlap_lim, sep_mul = _uniform_knobs(
        target_coverage=target_coverage,
        size_ratio=size_ratio,
        min_size=min_size,
        max_size=max_size,
        spacing_factor=spacing_factor,
        size_jitter=size_jitter,
        angle_jitter=angle_jitter,
    )
    base_angle = _uniform_base_angle(axes, auto_rotate, stamp_angle)

    def _make_placer(dest: Image.Image) -> _StampPlacer:
        return _StampPlacer(
            dest, region, stamp_rgba, region_area,
            base_angle=base_angle,
            rng=rng,
            ang_j=ang_j,
            overlap_lim=overlap_lim,
            sep_mul=sep_mul,
            max_stamps=max_stamps,
            stamp_cache=stamp_cache,
            target=target,
        )

    placer = _make_placer(canvas)
    H, W = region.shape
    du, dv = axes.du, axes.dv
    u_min, u_max = axes.u_min, axes.u_max
    length, width = axes.length, axes.width
    opaque_w, opaque_h, src_long = _src_metrics(stamp_rgba)
    slice_h = _ORGANIC_SLICE_PX
    dist = _distance_transform(region)

    size_base = _clip_stamp_size(min(length, width) * src_long / opaque_w * width_ratio, lo, hi)
    eu, ev = _stamp_extents(size_base, src_long, opaque_w, opaque_h, auto_rotate)
    half_u = 0.35 * min(eu, length * 0.45)
    half_v = 0.35 * min(ev, width * 0.45)
    start_u = u_min + half_u
    end_u = u_max - half_u
    start_v = axes.v_min + half_v
    end_v = axes.v_max - half_v
    mid_u = 0.5 * (u_min + u_max)
    mid_v = 0.5 * (axes.v_min + axes.v_max)
    aspect = max(1.0, float(axes.aspect))

    def _frac_to_uv(fu: float, fv: float) -> tuple[float, float]:
        su = mid_u if end_u <= start_u + 1e-6 else start_u + fu * (end_u - start_u)
        sv = mid_v if end_v <= start_v + 1e-6 else start_v + fv * (end_v - start_v)
        return su, sv

    def _in_region(cx: int, cy: int) -> bool:
        return 0 <= cx < W and 0 <= cy < H and bool(region[cy, cx])

    def _try_at(
        p: _StampPlacer,
        u: float,
        v: float,
        size: int,
        inward: tuple[float, float] | None = None,
    ) -> bool:
        cx, cy = axes.to_xy(u, v)
        if not _in_region(cx, cy):
            return False
        ext_u, _ext_v = _stamp_extents(size, src_long, opaque_w, opaque_h, auto_rotate)
        return p.commit(cx, cy, size, sep_ext=ext_u, inward=inward)

    def _try_frac(p: _StampPlacer, fu: float, fv: float, size: int) -> bool:
        u, v = _frac_to_uv(fu, fv)
        return _try_at(p, u, v, size, inward=_long_end_inward(fu, axes))

    def _gap_size(side: np.ndarray) -> int | None:
        if side.size < 12:
            return None
        if float(dist[ys[side], xs[side]].max()) < 5.0:
            return None
        raw = min(_group_width(dv, side) * _GAP_WIDTH_SCALE, width) * src_long / opaque_w * width_ratio
        sz = min(_clip_stamp_size(raw, lo, hi), size_base)
        return placer.jitter_size(sz, lo, hi, jitter)

    def _fill_gaps_at(t: float) -> None:
        with placer.open_layer():
            for g in _scan_groups(du, dv, t, slice_h):
                for side in _gap_sides(g, xs, ys, dv, placer.coverage):
                    if placer.placed >= max_stamps:
                        return
                    sz = _gap_size(side)
                    if sz is None:
                        continue
                    u_c = float(du[side].mean())
                    v_s = float(dv[side].mean())
                    span = 0.3 * _group_width(dv, side)
                    for off in (0.0, span, -span):
                        if _try_at(placer, u_c, v_s + off, sz):
                            break

    def _probe(ghost: _StampPlacer) -> None:
        remaining = _area_candidate_fracs(aspect)
        placed_f: list[tuple[float, float]] = []
        while remaining and ghost.placed < max_stamps and ghost.covered < target:
            f = _pick_spread_uv(remaining, placed_f)
            remaining.remove(f)
            size = ghost.jitter_size(size_base, lo, hi, jitter)
            if _try_frac(ghost, f[0], f[1], size):
                placed_f.append(f)

    n_eq = _probe_even_n(rng, _make_placer, canvas, _probe)

    hits: list[float] = []
    sites = _area_frac_sites(n_eq, aspect)
    with placer.open_layer():
        for fu, fv in sites:
            if placer.placed >= max_stamps:
                break
            size = placer.jitter_size(size_base, lo, hi, jitter)
            if _try_frac(placer, fu, fv, size):
                hits.append(_frac_to_uv(fu, fv)[0])

    gap_sites = _gap_u_sites(hits)
    if placer.covered < target and placer.placed < max_stamps:
        for t_gap in gap_sites:
            if placer.placed >= max_stamps or placer.covered >= target:
                break
            _fill_gaps_at(t_gap)

    if placer.covered < target and placer.placed < max_stamps:
        u0 = 0.5 * (u_min + u_max)
        v0 = 0.5 * (axes.v_min + axes.v_max)
        ring = _area_ring(u0, v0, eu, ev)
        while ring and placer.placed < max_stamps and placer.covered < target:
            if not placer.placed_xy:
                u, v = ring.pop(0)
            else:
                def _ring_score(uv: tuple[float, float]) -> float:
                    x, y = axes.to_xy(uv[0], uv[1])
                    return min(
                        math.hypot(float(x) - px, float(y) - py)
                        for px, py, _ext in placer.placed_xy
                    )

                idx = max(range(len(ring)), key=lambda i: _ring_score(ring[i]))
                u, v = ring.pop(idx)
            size = placer.jitter_size(size_base, lo, hi, jitter)
            _try_at(placer, u, v, size)

    if placer.maybe_bonus_stamp():
        bonus_sites = _area_frac_sites(max(2, n_eq + 1), aspect)
        seen = {(round(fu, 3), round(fv, 3)) for fu, fv in sites}
        for fu, fv in bonus_sites:
            if placer.extra_left <= 0 or placer.placed >= max_stamps:
                break
            if (round(fu, 3), round(fv, 3)) in seen:
                continue
            size = placer.jitter_size(size_base, lo, hi, jitter)
            if _try_frac(placer, fu, fv, size):
                hits.append(_frac_to_uv(fu, fv)[0])
        if placer.extra_left > 0:
            extra_sites = gap_sites if gap_sites else [mid_u]
            for t_gap in extra_sites:
                if placer.extra_left <= 0 or placer.placed >= max_stamps:
                    break
                _fill_gaps_at(t_gap)
        if placer.extra_left > 0 and placer.placed < max_stamps:
            u0 = 0.5 * (u_min + u_max)
            v0 = 0.5 * (axes.v_min + axes.v_max)
            for u, v in _area_ring(u0, v0, eu, ev):
                if placer.extra_left <= 0 or placer.placed >= max_stamps:
                    break
                size = placer.jitter_size(size_base, lo, hi, jitter)
                _try_at(placer, u, v, size)

    return placer.covered


def fill_region_with_stamps(
    canvas: Image.Image,
    region: np.ndarray,
    stamp_rgba: Image.Image,
    *,
    target_coverage: float,
    size_ratio: float,
    min_size: int,
    max_size: int,
    min_region: int,
    spacing_factor: float,
    size_jitter: float,
    angle_jitter: float,
    auto_rotate: bool,
    stamp_angle: float,
    rng: np.random.Generator,
    max_stamps: int = 400,
    max_attempts: int = 2500,
    stamp_cache: dict | None = None,
    uniform_pack: bool = False,
) -> float:
    ys, xs = np.where(region)
    region_area = float(xs.size)
    if region_area < max(1, int(min_region)):
        return 0.0
    cache = stamp_cache if stamp_cache is not None else {}
    if uniform_pack:
        axes = _RegionAxes(xs, ys)
        packer = _fill_region_area if axes.width >= 1.0 and axes.aspect < _ORGANIC_MIN_ASPECT else _fill_region_organic
        return packer(
            canvas,
            region,
            stamp_rgba,
            xs,
            ys,
            region_area,
            axes,
            target_coverage=target_coverage,
            size_ratio=size_ratio,
            min_size=min_size,
            max_size=max_size,
            spacing_factor=spacing_factor,
            size_jitter=size_jitter,
            angle_jitter=angle_jitter,
            auto_rotate=bool(auto_rotate),
            stamp_angle=float(stamp_angle),
            rng=rng,
            max_stamps=max_stamps,
            stamp_cache=cache,
        )

    bbox_w = float(int(xs.max()) - int(xs.min()) + 1)
    bbox_h = float(int(ys.max()) - int(ys.min()) + 1)
    span = min(bbox_w, bbox_h)
    lo = max(4, int(min_size))
    hi = max(lo, int(max_size))
    opaque_w, opaque_h, src_long = _src_metrics(stamp_rgba)
    base_size = _clip_stamp_size(
        span * src_long / opaque_w * min(2.0, max(0.0, float(size_ratio))),
        lo,
        hi,
    )

    region_angle = _stamp_align_from_points(xs, ys)
    base_angle = (region_angle + float(stamp_angle)) if auto_rotate else float(stamp_angle)

    H, W = region.shape
    coverage = np.zeros((H, W), dtype=np.float32)
    placed_boxes: list[tuple[float, float, float, float, tuple, tuple]] = []
    placed = 0
    attempts = 0
    covered = 0.0
    target = _clamp_coverage(target_coverage)

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
        if size < lo:
            size = lo
        elif size > hi:
            size = hi
        angle = base_angle
        if ang_j > 0:
            angle = base_angle + float(rng.uniform(-ang_j, ang_j))

        idx = int(rng.integers(0, n_pts))
        cx, cy = int(xs[idx]), int(ys[idx])

        ratio = size / src_long
        cw, ch = opaque_w * ratio + 1.0, opaque_h * ratio + 1.0

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
        _outside, _overlap, newly, slice_win = _stamp_place_stats(
            alpha, cx, cy, region, coverage
        )
        gain = float(newly) / region_area if region_area > 0 else 0.0
        if gain <= 0 and placed > 0:
            continue

        _paste_rgba(canvas, stamp, cx, cy)
        if slice_win is not None:
            _apply_coverage_slice(coverage, *slice_win)
        if spacing_k > 0.0 and u is not None:
            placed_boxes.append((float(cx), float(cy), hw, hh, u, v))
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
    uniform_pack: bool = False,
    stamp_angle: float = 0.0,
    seed: int = 0,
    preview: bool = False,
) -> tuple[np.ndarray, float]:
    base = image_tensor_to_rgba(image_hwc)
    stamp_rgba = stamp if stamp.mode == "RGBA" else stamp.convert("RGBA")

    mask_bool = _mask_bool(mask_hw)
    if not mask_bool.any():
        return rgba_to_image_tensor(base), 0.0

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    stamp_cache: dict = {}
    if uniform_pack:
        limits = (220, 8000) if preview else (900, 28000)
    else:
        limits = (80, 500) if preview else (400, 2500)
    target = _clamp_coverage(target_coverage)
    coverages: list[float] = []
    min_region = max(_MIN_REGION_FLOOR, int(round(mask_bool.size * _MIN_REGION_RATIO)))
    for region in iter_connected_regions(mask_bool):
        cov = fill_region_with_stamps(
            base,
            region,
            stamp_rgba,
            target_coverage=target,
            size_ratio=size_ratio,
            min_size=min_size,
            max_size=max_size,
            min_region=min_region,
            spacing_factor=spacing_factor,
            size_jitter=size_jitter,
            angle_jitter=angle_jitter,
            auto_rotate=bool(auto_rotate),
            uniform_pack=bool(uniform_pack),
            stamp_angle=float(stamp_angle),
            rng=rng,
            max_stamps=limits[0],
            max_attempts=limits[1],
            stamp_cache=stamp_cache,
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
    uniform_pack: bool = False,
    stamp_angle: float = 0.0,
    seed: int = 0,
    width: int = 384,
    height: int = 384,
) -> np.ndarray:
    """White background + black bar mask with stamps applied (preview helper)."""
    image, mask = make_demo_scene(width, height)
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
        uniform_pack=uniform_pack,
        stamp_angle=stamp_angle,
        seed=seed,
        preview=True,
    )
    return out
