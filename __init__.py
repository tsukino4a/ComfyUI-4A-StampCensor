"""
@author: tsukino4a
@title: ComfyUI-4A-StampCensor
@nickname: 4A Stamp Censor
@description: Pattern/stamp censoring over masks (hearts, scribble bars, custom stickers) instead of mosaic.
"""

from __future__ import annotations

import logging

from .nodes.stamp_censor import StampCensor4A
from .nodes.stamp_custom_load import StampCustomLoad4A
from .nodes.stamp_load import StampLoad4A
from .server_routes import register_routes

logger = logging.getLogger("ComfyUI-4A-StampCensor")

NODE_CLASS_MAPPINGS = {
    StampLoad4A.NAME: StampLoad4A,
    StampCustomLoad4A.NAME: StampCustomLoad4A,
    StampCensor4A.NAME: StampCensor4A,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    StampLoad4A.NAME: "Stamp Load",
    StampCustomLoad4A.NAME: "Stamp Custom Load",
    StampCensor4A.NAME: "Stamp Censor",
}

WEB_DIRECTORY = "./web"

try:
    register_routes()
except Exception:
    logger.exception("Failed to register 4A Stamp Censor routes")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
