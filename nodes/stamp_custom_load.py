"""Stamp Custom Load: drop or pick a PNG and keep its alpha."""

from __future__ import annotations

import os

from ..stamp_engine import comfy_image_mtime, normalize_stamp_rgba, open_comfy_image, parse_comfy_image_ref
from .common import rgba_to_stamp_tensor, slider_float


_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif",
}


def _input_image_files() -> list[str]:
    try:
        import folder_paths
    except ImportError:
        return [""]
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return [""]
    files = sorted(
        name
        for name in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, name))
        and os.path.splitext(name)[1].lower() in _IMAGE_EXTENSIONS
    )
    return files or [""]


class StampCustomLoad4A:
    NAME = "StampCustomLoad4A"
    CATEGORY = "4A/StampCensor"
    DESCRIPTION = "Drop or pick a custom stamp. White+transparent or black-on-white drawings are normalized. No tinting."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": (
                    _input_image_files(),
                    {
                        "image_upload": True,
                        "tooltip": "Drag a PNG onto the node. White+transparent is kept; black ink on white is keyed. Colored RGBA is used as-is.",
                    },
                ),
                "stamp_angle": slider_float(
                    0.0, -180.0, 180.0, 1.0,
                    "Initial angle used by Stamp Censor when Auto Rotate is off. Preview rotates; the output stamp does not.",
                ),
            },
        }

    RETURN_TYPES = ("STAMP",)
    RETURN_NAMES = ("stamp",)
    FUNCTION = "run"
    OUTPUT_NODE = False

    @classmethod
    def VALIDATE_INPUTS(cls, **_kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, image, stamp_angle=0.0, **_unused):
        return f"{image}|{stamp_angle}|{comfy_image_mtime(image)}"

    def run(self, image, stamp_angle=0.0):
        filename, subfolder, type_name = parse_comfy_image_ref(image)
        if not filename:
            raise ValueError("Select or drop a custom stamp image.")
        stamp_pil = normalize_stamp_rgba(open_comfy_image(filename, subfolder, type_name))
        return (rgba_to_stamp_tensor(stamp_pil),)
