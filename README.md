# ComfyUI-4A-StampCensor

[中文说明](README.zh-CN.md)

Scatter stamp / sticker shapes over a mask instead of mosaic. Built-in white (or black-on-white) presets can be tinted from a color picker; custom PNGs keep their own alpha. Detection and mask grow are left to SAM / Impact / Grow Mask.

**Current release: 0.1.0** — Stamp Load, Stamp Custom Load, and Stamp Censor with live node previews.

![Hero overview](docs/images/hero.png)

## Highlights

### Stamp Load + color tint

Pick a built-in shape, tint it with the color picker, and set a base angle. The node preview rotates with the angle; the `STAMP` output stays unrotated so Stamp Censor can apply auto-rotate / jitter on top.

![Stamp Load](docs/images/stamp_load.png)

### Custom drawings (no tint)

Drop or pick your own PNG. Two drawing styles are normalized automatically:

- **White shape + transparent background** — used as-is
- **Black ink on white paper** — black pixels become the stamp, white is discarded

Colored RGBA stickers pass through without tinting.

![Stamp Custom Load](docs/images/stamp_custom.png)

### Mask scatter with coverage / spacing

Connect `image` + `mask` + `stamp`. Each connected mask region gets its own long-axis heading (optional), random sizes, and oriented-box packing until **target coverage**. Stamps may overflow the mask. An in-node demo preview updates when the stamp is connected.

![Stamp Censor](docs/images/stamp_censor.png)

### Result instead of mosaic

Hearts, scribble bars, stars, crosses, or your own sticker — same mask pipeline, no pixelation.

![Before / after](docs/images/result.png)

## Install

### ComfyUI-Manager (recommended)

Search for **4A Stamp Censor** / `ComfyUI-4A-StampCensor` and install.

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/tsukino4a/ComfyUI-4A-StampCensor.git ComfyUI-4A-StampCensor
```

No extra pip packages. Restart ComfyUI after install. After changing Python or locale files, restart again; after JS-only edits, hard-refresh the browser (Ctrl+F5).

## Quick start

1. Add **Stamp Load** and **Stamp Censor** from `4A/StampCensor`.
2. Connect `stamp` → `stamp`. Feed `image` and a white-on-black `mask` (YOLO / SAM / Impact / Grow Mask).
3. Queue once. Tweak coverage, size ratio, spacing, and auto-rotate; the bottom demo preview follows when a Stamp Load is connected.
4. Optional: use **Stamp Custom Load** instead of Stamp Load if you have your own PNG.

This plugin does **not** detect NSFW or grow masks. Wire those nodes yourself.

## Nodes

| Node | Role |
|------|------|
| Stamp Load | Built-in preset + color + angle → `STAMP` |
| Stamp Custom Load | Drop / pick a PNG → `STAMP` (no tint) |
| Stamp Censor | Scatter the connected stamp over `mask`; optional seed input |

## Stamp assets

| Path | Purpose |
|------|---------|
| [`assets/`](assets/) | Built-in presets. Every `.png` except `demo_scene.png` is scanned on startup |
| [`assets/demo_scene.png`](assets/demo_scene.png) | Internal demo plate only — never listed as a stamp |

Accepted preset drawings:

- Pure white RGB + real transparency
- Pure black ink on a white background (converted at load)

Add or delete a file, then press **R** (Refresh Node Definitions) or reload the page. Name the file the preset id you want in the dropdown.

Shipped shapes (order is fixed; extra files sort after them): `heart_standard`, `heart_wobbly_a`, `heart_soft`, `bar_h_scribble`, `bar_h_thick`, `star_wobbly`, `circle_scribble`, `cross_x`.

## Dependencies

- Pillow and NumPy are provided by ComfyUI; this node adds no extra pip packages

## License

This project is released under the [MIT License](LICENSE).
