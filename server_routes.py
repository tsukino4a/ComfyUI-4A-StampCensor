"""HTTP helpers for live stamp / demo previews."""

from __future__ import annotations

import io
import logging

from aiohttp import web

logger = logging.getLogger("ComfyUI-4A-StampCensor")


def _png_response(pil_image):
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return web.Response(body=buf.getvalue(), content_type="image/png")


def _open_custom_stamp(filename, subfolder="", type_name="input"):
    from .stamp_engine import as_is_stamp_rgba, open_comfy_image

    return as_is_stamp_rgba(open_comfy_image(filename, subfolder or "", type_name or "input"))


def register_routes():
    try:
        from server import PromptServer
    except Exception:
        logger.warning("PromptServer unavailable; preview routes not registered")
        return

    routes = PromptServer.instance.routes

    @routes.get("/4a_stampcensor/presets")
    async def stamp_presets(request):
        from .stamp_engine import PRESET_NAMES, refresh_builtin_stamps

        refresh = request.rel_url.query.get("refresh", "").lower() in ("1", "true", "yes")
        names = refresh_builtin_stamps() if refresh else list(PRESET_NAMES)
        return web.json_response({"presets": names})

    @routes.get("/4a_stampcensor/stamp_preview")
    async def stamp_preview(request):
        preset = request.rel_url.query.get("preset", "heart_solid")
        color = request.rel_url.query.get("color", "#000000")
        try:
            from PIL import Image

            custom_name = request.rel_url.query.get("custom_filename")
            if custom_name:
                stamp = _open_custom_stamp(
                    custom_name,
                    request.rel_url.query.get("custom_subfolder") or "",
                    request.rel_url.query.get("custom_type") or "input",
                )
            else:
                from .stamp_engine import crop_opaque, harden_alpha, prepare_stamp

                stamp = prepare_stamp(preset, color)
                stamp = crop_opaque(stamp.convert("RGBA"), pad_ratio=0)
                stamp = harden_alpha(stamp)
            stamp.thumbnail((256, 256), Image.Resampling.LANCZOS)
            return _png_response(stamp)
        except Exception as e:
            logger.exception("stamp_preview failed")
            return web.json_response({"error": str(e)}, status=400)

    @routes.post("/4a_stampcensor/demo_preview")
    async def demo_preview(request):
        from .stamp_engine import normalize_stamp_rgba, prepare_stamp, render_demo_preview
        from PIL import Image
        import base64
        import numpy as np

        try:
            data = await request.json()
        except Exception:
            data = {}

        preset = data.get("preset", "heart_solid")
        color = data.get("color", "#000000")
        stamp_b64 = data.get("stamp_png_base64")

        try:
            custom_name = data.get("custom_filename")
            if custom_name:
                stamp = _open_custom_stamp(
                    custom_name,
                    data.get("custom_subfolder") or "",
                    data.get("custom_type") or "input",
                )
            elif stamp_b64:
                raw = base64.b64decode(stamp_b64.split(",")[-1])
                stamp = normalize_stamp_rgba(Image.open(io.BytesIO(raw)))
            else:
                stamp = prepare_stamp(preset, color)

            demo = render_demo_preview(
                stamp,
                target_coverage=float(data.get("target_coverage", 0.8)),
                size_ratio=float(data.get("size_ratio", 0.28)),
                min_size=int(data.get("min_size", 24)),
                max_size=int(data.get("max_size", 512)),
                spacing_factor=float(data.get("spacing_factor", 0.3)),
                size_jitter=float(data.get("size_jitter", 0.15)),
                angle_jitter=float(data.get("angle_jitter", 0.0)),
                auto_rotate=bool(data.get("auto_rotate", True)),
                uniform_pack=bool(data.get("uniform_pack", False)),
                stamp_angle=float(data.get("stamp_angle", 0.0) or 0),
                seed=int(data.get("seed", 0)),
                width=int(data.get("width", 384)),
                height=int(data.get("height", 384)),
            )
            img = Image.fromarray((np.clip(demo, 0, 1) * 255).astype(np.uint8))
            return _png_response(img)
        except Exception as e:
            logger.exception("demo_preview failed")
            return web.json_response({"error": str(e)}, status=400)
