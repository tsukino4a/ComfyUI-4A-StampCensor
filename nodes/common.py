"""Shared Comfy widget / tensor helpers for StampCensor nodes."""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image


def slider_float(default, min_v, max_v, step, tooltip):
    return (
        "FLOAT",
        {
            "default": default,
            "min": min_v,
            "max": max_v,
            "step": step,
            "display": "slider",
            "tooltip": tooltip,
        },
    )


def rgba_to_stamp_tensor(pil: Image.Image) -> torch.Tensor:
    arr = np.asarray(pil.convert("RGBA"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr[None, ...].astype(np.float32))
