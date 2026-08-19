"""Stamp Load: built-in stamp + color tint."""

from __future__ import annotations

from ..stamp_engine import PRESET_NAMES, prepare_stamp
from .common import rgba_to_stamp_tensor, slider_float


class StampLoad4A:
    NAME = "StampLoad4A"
    CATEGORY = "4A/StampCensor"
    DESCRIPTION = "Pick a built-in stamp and tint color for Stamp Censor."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "stamp_preset": (
                    PRESET_NAMES,
                    {
                        "default": "heart_wobbly_a",
                        "tooltip": "Built-in stamp shape.",
                    },
                ),
                "stamp_color": (
                    "COLORCODE",
                    {
                        "default": "#000000",
                        "tooltip": "Tint color for built-in stamps (white+transparent or black ink on white).",
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

    def run(self, stamp_preset, stamp_color, stamp_angle=0.0):
        stamp_pil = prepare_stamp(stamp_preset, stamp_color)
        return (rgba_to_stamp_tensor(stamp_pil),)
