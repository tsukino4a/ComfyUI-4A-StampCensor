"""Stamp Censor: scatter prepared stamps over a mask."""

from __future__ import annotations

import random

import numpy as np
import torch

from ..stamp_engine import image_tensor_to_rgba, stamp_censor_image
from .common import slider_float


def _resolve_seed(seed) -> int:
    if seed is None:
        return random.randint(0, 0xFFFFFFFF)
    try:
        value = int(seed)
    except (TypeError, ValueError):
        return random.randint(0, 0xFFFFFFFF)
    if value < 0:
        return random.randint(0, 0xFFFFFFFF)
    return value & 0xFFFFFFFF


class StampCensor4A:
    NAME = "StampCensor4A"
    CATEGORY = "4A/StampCensor"
    DESCRIPTION = "Scatter stamps over masked regions. Connect Stamp from Stamp Load or Stamp Custom Load."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": (
                    "IMAGE",
                    {"tooltip": "Source image to stamp over."},
                ),
                "mask": (
                    "MASK",
                    {"tooltip": "White areas are stamped. Each connected region is handled separately."},
                ),
                "stamp": (
                    "STAMP",
                    {"tooltip": "Connect Stamp Load or Stamp Custom Load."},
                ),
                "auto_rotate": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "On: align to each mask region's long axis, then add the Stamp Load angle. Off: use the Stamp Load angle only.",
                    },
                ),
                "min_size": (
                    "INT",
                    {
                        "default": 24,
                        "min": 4,
                        "max": 1024,
                        "step": 1,
                        "tooltip": "Smallest stamp size in pixels.",
                    },
                ),
                "max_size": (
                    "INT",
                    {
                        "default": 512,
                        "min": 8,
                        "max": 2048,
                        "step": 1,
                        "tooltip": "Largest stamp size in pixels. Size Ratio usually hits first.",
                    },
                ),
                "size_ratio": slider_float(
                    0.28, 0.02, 1.0, 0.01,
                    "Stamp size as a fraction of the region's longer side, before min/max clamp.",
                ),
                "target_coverage": slider_float(
                    0.8, 0.05, 1.0, 0.01,
                    "Stop placing stamps in a region when this fraction of its mask is covered.",
                ),
                "spacing_factor": slider_float(
                    0.3, 0.0, 2.0, 0.01,
                    "Collision size of each stamp. 0 = allow full overlap. 1.0 = oriented boxes just touch.",
                ),
                "size_jitter": slider_float(
                    0.15, 0.0, 0.9, 0.01,
                    "Random size variation around the base size.",
                ),
                "angle_jitter": slider_float(
                    0.0, 0.0, 180.0, 0.5,
                    "Extra random rotation in degrees, added after auto-rotate or the load angle.",
                ),
                "stamp_angle": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": -180.0,
                        "max": 180.0,
                        "step": 1.0,
                        "tooltip": "Copied from Stamp Load. Added on top of auto-rotate when it is on.",
                    },
                ),
            },
            "optional": {
                "seed": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 0xFFFFFFFF,
                        "forceInput": True,
                        "tooltip": "Optional. Connected: use this seed. Empty: randomize each queue.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "run"

    def run(
        self,
        image,
        mask,
        stamp,
        target_coverage,
        size_ratio,
        min_size,
        max_size,
        size_jitter,
        angle_jitter,
        auto_rotate,
        spacing_factor=0.3,
        stamp_angle=0.0,
        seed=None,
        **_unused,
    ):
        stamp_pil = image_tensor_to_rgba(stamp[0].detach().cpu().numpy())
        base_seed = _resolve_seed(seed)

        if min_size > max_size:
            min_size, max_size = max_size, min_size

        imgs = image.detach().cpu().numpy()
        masks = mask.detach().cpu().numpy()

        if masks.ndim == 2:
            masks = masks[None, ...]
        if imgs.ndim != 4:
            raise ValueError("image must be [B,H,W,C]")

        b = imgs.shape[0]
        if masks.shape[0] == 1 and b > 1:
            masks = np.repeat(masks, b, axis=0)
        if masks.shape[0] != b:
            raise ValueError(f"Batch mismatch: image B={b}, mask B={masks.shape[0]}")

        out_frames = []
        for i in range(b):
            frame, _cov = stamp_censor_image(
                imgs[i],
                masks[i],
                stamp_pil,
                target_coverage=float(target_coverage),
                size_ratio=float(size_ratio),
                min_size=int(min_size),
                max_size=int(max_size),
                spacing_factor=float(spacing_factor),
                size_jitter=float(size_jitter),
                angle_jitter=float(angle_jitter),
                auto_rotate=bool(auto_rotate),
                stamp_angle=float(stamp_angle),
                seed=base_seed + i,
            )
            out_frames.append(frame)

        out = torch.from_numpy(np.stack(out_frames, axis=0).astype(np.float32))
        return (out,)
