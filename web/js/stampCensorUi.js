/**
 * 4A StampCensor UI
 * - COLORCODE: RMBG-looking bar; one click opens a custom palette beside the button
 *   (native <input type=color> cannot be positioned on Windows — always jumps top-left)
 * - Preview: canvas in leftover space (Load Image style). computeSize only adds a
 *   minimum when an image exists — never leftover, never onResize setSize.
 */
import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

function getContrastTextColor(hexColor) {
    if (typeof hexColor !== "string" || !/^#?[0-9a-fA-F]{6}$/.test(hexColor)) {
        return "#cccccc";
    }
    const hex = hexColor.replace("#", "");
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.5 ? "#333333" : "#cccccc";
}

function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return {
        r: parseInt(h.slice(0, 2), 16),
        g: parseInt(h.slice(2, 4), 16),
        b: parseInt(h.slice(4, 6), 16),
    };
}

function rgbToHex(r, g, b) {
    const c = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, "0");
    return `#${c(r)}${c(g)}${c(b)}`;
}

function rgbToHsv(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const d = max - min;
    let h = 0;
    if (d !== 0) {
        if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        else if (max === g) h = ((b - r) / d + 2) / 6;
        else h = ((r - g) / d + 4) / 6;
    }
    return { h, s: max === 0 ? 0 : d / max, v: max };
}

function hsvToRgb(h, s, v) {
    const i = Math.floor(h * 6);
    const f = h * 6 - i;
    const p = v * (1 - s);
    const q = v * (1 - f * s);
    const t = v * (1 - (1 - f) * s);
    let r, g, b;
    switch (i % 6) {
        case 0:
            r = v;
            g = t;
            b = p;
            break;
        case 1:
            r = q;
            g = v;
            b = p;
            break;
        case 2:
            r = p;
            g = v;
            b = t;
            break;
        case 3:
            r = p;
            g = q;
            b = v;
            break;
        case 4:
            r = t;
            g = p;
            b = v;
            break;
        default:
            r = v;
            g = p;
            b = q;
    }
    return { r: Math.round(r * 255), g: Math.round(g * 255), b: Math.round(b * 255) };
}

const lastPointer = { x: 80, y: 80 };
if (typeof window !== "undefined" && !window.__4aStampPtrTracked) {
    window.__4aStampPtrTracked = true;
    window.addEventListener(
        "pointerdown",
        (e) => {
            if (Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) {
                lastPointer.x = e.clientX;
                lastPointer.y = e.clientY;
            }
        },
        true
    );
}

function eventClientXY(e) {
    if (!e) return null;
    if (Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) {
        return [e.clientX, e.clientY];
    }
    const src = e.changedTouches?.[0] || e.touches?.[0] || e.rootPointerEvent || e.originalEvent || e.sourceEvent;
    if (src && Number.isFinite(src.clientX) && Number.isFinite(src.clientY)) {
        return [src.clientX, src.clientY];
    }
    return null;
}

function graphPointToClient(gx, gy) {
    const canvas = app.canvas;
    const el = canvas?.canvas;
    if (!el) return [lastPointer.x, lastPointer.y];
    const rect = el.getBoundingClientRect();

    if (typeof canvas.convertOffsetToCanvas === "function") {
        const out = canvas.convertOffsetToCanvas([gx, gy]);
        if (out && Number.isFinite(out[0]) && Number.isFinite(out[1])) {
            const sx = el.clientWidth / (el.width || el.clientWidth);
            const sy = el.clientHeight / (el.height || el.clientHeight);
            return [rect.left + out[0] * sx, rect.top + out[1] * sy];
        }
    }

    const ds = canvas.ds || {};
    const scale = ds.scale || 1;
    const ox = ds.offset?.[0] || 0;
    const oy = ds.offset?.[1] || 0;
    // Current LiteGraph: offset is graph-space → client = (graph + offset) * scale + canvasRect
    return [rect.left + (gx + ox) * scale, rect.top + (gy + oy) * scale];
}

function paletteAnchor(node, widget, e, pos) {
    const clicked = eventClientXY(e);
    if (clicked) return clicked;
    if (lastPointer.x || lastPointer.y) return [lastPointer.x, lastPointer.y];

    const localX = Number.isFinite(pos?.[0]) ? pos[0] : 20;
    const localY = Number.isFinite(widget.last_y)
        ? widget.last_y + 22
        : Number.isFinite(widget.y)
          ? widget.y + 22
          : 40;
    return graphPointToClient((node.pos?.[0] || 0) + localX, (node.pos?.[1] || 0) + localY);
}

function placePanelBeside(sx, sy, panelW, panelH) {
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = sx - panelW - margin;
    if (left < margin) left = sx + margin;
    if (left + panelW > vw - margin) left = Math.max(margin, vw - panelW - margin);
    let top = sy - 16;
    if (top + panelH > vh - margin) top = Math.max(margin, vh - panelH - margin);
    if (top < margin) top = margin;
    return [Math.round(left), Math.round(top)];
}

/** Full palette beside the color bar — one click, no native top-left picker. */
function openPaletteBeside(widget, node, e, pos) {
    document.getElementById("4a-stamp-color-panel")?.remove();
    document.getElementById("4a-stamp-native-color")?.remove();

    const [sx, sy] = paletteAnchor(node, widget, e, pos);
    const panelW = 220;
    const panelH = 260;
    const [left, top] = placePanelBeside(sx, sy, panelW, panelH);

    const panel = document.createElement("div");
    panel.id = "4a-stamp-color-panel";
    panel.style.cssText = [
        "position:fixed",
        `left:${Math.round(left)}px`,
        `top:${Math.round(top)}px`,
        "z-index:100000",
        "background:#2b2b2b",
        "border:1px solid #666",
        "border-radius:10px",
        "padding:10px",
        "box-shadow:0 10px 28px rgba(0,0,0,.5)",
        "width:220px",
        "user-select:none",
        "font:12px sans-serif",
        "color:#ddd",
    ].join(";");

    const { r, g, b } = hexToRgb(widget.value || "#000000");
    let hsv = rgbToHsv(r, g, b);

    const sv = document.createElement("canvas");
    sv.width = 200;
    sv.height = 160;
    sv.style.cssText = "display:block;width:200px;height:160px;border-radius:6px;cursor:crosshair;";

    const hue = document.createElement("canvas");
    hue.width = 200;
    hue.height = 14;
    hue.style.cssText = "display:block;width:200px;height:14px;margin-top:8px;border-radius:7px;cursor:pointer;";

    const rgbRow = document.createElement("div");
    rgbRow.style.cssText = "display:flex;gap:6px;margin-top:8px;";
    const mkNum = (label, val) => {
        const wrap = document.createElement("label");
        wrap.style.cssText = "flex:1;display:flex;flex-direction:column;gap:2px;";
        wrap.textContent = label;
        const inp = document.createElement("input");
        inp.type = "number";
        inp.min = 0;
        inp.max = 255;
        inp.value = val;
        inp.style.cssText =
            "width:100%;box-sizing:border-box;background:#111;color:#eee;border:1px solid #555;border-radius:4px;padding:4px;";
        wrap.appendChild(inp);
        rgbRow.appendChild(wrap);
        return inp;
    };
    const inR = mkNum("R", r);
    const inG = mkNum("G", g);
    const inB = mkNum("B", b);

    const applyRgb = (rr, gg, bb, syncHsv = true) => {
        const hex = rgbToHex(rr, gg, bb);
        widget.value = hex;
        if (syncHsv) hsv = rgbToHsv(rr, gg, bb);
        inR.value = rr;
        inG.value = gg;
        inB.value = bb;
        node.graph._version++;
        node.setDirtyCanvas(true, true);
        node._4aPaintColorBar?.();
        rememberNodeParams(node);
        node._4aRefreshPreview?.();
        paint();
    };

    const paint = () => {
        const svctx = sv.getContext("2d");
        const hueRgb = hsvToRgb(hsv.h, 1, 1);
        // white -> hue
        const gradX = svctx.createLinearGradient(0, 0, sv.width, 0);
        gradX.addColorStop(0, "#fff");
        gradX.addColorStop(1, `rgb(${hueRgb.r},${hueRgb.g},${hueRgb.b})`);
        svctx.fillStyle = gradX;
        svctx.fillRect(0, 0, sv.width, sv.height);
        // transparent -> black
        const gradY = svctx.createLinearGradient(0, 0, 0, sv.height);
        gradY.addColorStop(0, "rgba(0,0,0,0)");
        gradY.addColorStop(1, "#000");
        svctx.fillStyle = gradY;
        svctx.fillRect(0, 0, sv.width, sv.height);
        // cursor
        const cx = hsv.s * sv.width;
        const cy = (1 - hsv.v) * sv.height;
        svctx.strokeStyle = "#fff";
        svctx.lineWidth = 2;
        svctx.beginPath();
        svctx.arc(cx, cy, 6, 0, Math.PI * 2);
        svctx.stroke();
        svctx.strokeStyle = "#000";
        svctx.lineWidth = 1;
        svctx.beginPath();
        svctx.arc(cx, cy, 6, 0, Math.PI * 2);
        svctx.stroke();

        const hctx = hue.getContext("2d");
        const hg = hctx.createLinearGradient(0, 0, hue.width, 0);
        for (let i = 0; i <= 6; i++) {
            const c = hsvToRgb(i / 6, 1, 1);
            hg.addColorStop(i / 6, `rgb(${c.r},${c.g},${c.b})`);
        }
        hctx.fillStyle = hg;
        hctx.fillRect(0, 0, hue.width, hue.height);
        const hx = hsv.h * hue.width;
        hctx.strokeStyle = "#fff";
        hctx.lineWidth = 2;
        hctx.strokeRect(hx - 2, 0, 4, hue.height);
    };

    const pickSV = (ev) => {
        const rect = sv.getBoundingClientRect();
        const x = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        const y = Math.max(0, Math.min(1, (ev.clientY - rect.top) / rect.height));
        hsv.s = x;
        hsv.v = 1 - y;
        const rgb = hsvToRgb(hsv.h, hsv.s, hsv.v);
        applyRgb(rgb.r, rgb.g, rgb.b, false);
    };
    const pickHue = (ev) => {
        const rect = hue.getBoundingClientRect();
        hsv.h = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        const rgb = hsvToRgb(hsv.h, hsv.s, hsv.v);
        applyRgb(rgb.r, rgb.g, rgb.b, false);
    };

    let dragging = null;
    sv.addEventListener("pointerdown", (ev) => {
        dragging = "sv";
        sv.setPointerCapture(ev.pointerId);
        pickSV(ev);
    });
    sv.addEventListener("pointermove", (ev) => {
        if (dragging === "sv") pickSV(ev);
    });
    sv.addEventListener("pointerup", () => {
        dragging = null;
    });
    hue.addEventListener("pointerdown", (ev) => {
        dragging = "hue";
        hue.setPointerCapture(ev.pointerId);
        pickHue(ev);
    });
    hue.addEventListener("pointermove", (ev) => {
        if (dragging === "hue") pickHue(ev);
    });
    hue.addEventListener("pointerup", () => {
        dragging = null;
    });

    const syncFromInputs = () => {
        applyRgb(+inR.value || 0, +inG.value || 0, +inB.value || 0, true);
    };
    inR.addEventListener("change", syncFromInputs);
    inG.addEventListener("change", syncFromInputs);
    inB.addEventListener("change", syncFromInputs);

    panel.appendChild(sv);
    panel.appendChild(hue);
    panel.appendChild(rgbRow);
    document.body.appendChild(panel);
    paint();

    const closePanel = () => {
        if (!panel.isConnected) return;
        panel.remove();
        window.removeEventListener("pointerdown", onOutside, true);
        window.removeEventListener("mousedown", onOutside, true);
        window.removeEventListener("keydown", onKey, true);
        app.canvas?.canvas?.removeEventListener("pointerdown", onOutside, true);
    };

    const onOutside = (ev) => {
        if (panel.contains(ev.target)) return;
        closePanel();
    };

    const onKey = (ev) => {
        if (ev.key === "Escape") closePanel();
    };

    // Opening click already happened; listen after this frame so it does not self-close.
    // Use window capture: Comfy canvas swallows bubble-phase mousedown.
    requestAnimationFrame(() => {
        window.addEventListener("pointerdown", onOutside, true);
        window.addEventListener("mousedown", onOutside, true);
        window.addEventListener("keydown", onKey, true);
        app.canvas?.canvas?.addEventListener("pointerdown", onOutside, true);
    });
}

function makeColorWidget(key, val) {
    const widget = {};
    widget.y = 0;
    widget.name = key;
    widget.type = "COLORCODE";
    widget.options = { default: "#000000" };

    let initialValue = "#000000";
    if (Array.isArray(val) && val.length > 1 && val[1]?.default) {
        initialValue = val[1].default;
    }
    if (typeof initialValue === "string" && /^#?[0-9a-fA-F]{6}$/.test(initialValue)) {
        widget.value = initialValue.startsWith("#") ? initialValue : `#${initialValue}`;
    } else {
        widget.value = "#000000";
    }

    widget.draw = function (ctx, node, widgetWidth, widgetY, height) {
        paintColorBar(ctx, this, node, widgetWidth, widgetY, height);
    };

    widget.mouse = function (e, pos, node) {
        if (e.type === "pointerdown") {
            const margin = 15;
            if (pos[0] >= margin && pos[0] <= node.size[0] - margin) {
                openPaletteBeside(this, node, e, pos);
                return true;
            }
        }
        return false;
    };

    widget.computeSize = function (width) {
        return [Math.min(width || 220, 220), 22];
    };
    return widget;
}

function hideCanvasTextInput(widget) {
    const els = [widget?.inputEl, widget?.element, widget?.inputEl?.parentElement];
    for (const el of els) {
        if (!el?.style) continue;
        el.style.display = "none";
        el.style.pointerEvents = "none";
        el.hidden = true;
    }
}

function isTextColorWidget(widget) {
    const t = String(widget?.type || "").toLowerCase();
    return t === "string" || t === "text" || t === "customtext";
}

function paintColorBar(ctx, widget, node, widgetWidth, widgetY, height) {
    const drawHeight = 22;
    const margin = 15;
    const radius = 10;
    const nodeW = node?.size?.[0] || widgetWidth;
    const x = margin;
    const y = widgetY + (Math.max(height, drawHeight) - drawHeight) / 2;
    const w = Math.max(80, Math.min(widgetWidth, nodeW) - margin * 2);
    const h = drawHeight;
    const value = widget.value || "#000000";

    ctx.fillStyle = value;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.arcTo(x + w, y, x + w, y + radius, radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius);
    ctx.lineTo(x + radius, y + h);
    ctx.arcTo(x, y + h, x, y + h - radius, radius);
    ctx.lineTo(x, y + radius);
    ctx.arcTo(x, y, x + radius, y, radius);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "#555";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = getContrastTextColor(value);
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    const label = widget.label || widget.name;
    ctx.fillText(`${label} (${value})`, x + w * 0.5, y + drawHeight * 0.65);
}

function bindColorPalette(widget, node) {
    widget.draw = function (ctx, n, widgetWidth, widgetY, height) {
        hideCanvasTextInput(this);
        paintColorBar(ctx, this, n, widgetWidth, widgetY, height);
    };
    widget.mouse = function (e, pos, n) {
        if (e.type === "pointerdown" || e.type === "mousedown") {
            const margin = 15;
            if (pos[0] >= margin && pos[0] <= (n.size?.[0] || 0) - margin) {
                openPaletteBeside(this, n, e, pos);
                return true;
            }
        }
        return false;
    };
    widget.onPointerDown = function (pointer) {
        const e = pointer?.eDown || pointer?.eMove || pointer;
        openPaletteBeside(this, node, e, [20, 20]);
        return true;
    };
    widget.computeSize = function () {
        return [220, 22];
    };
}

function attachDomColorBar(node, colorWidget) {
    if (node._4aColorDom) return;
    const btn = document.createElement("div");
    btn.style.cssText =
        "width:calc(100% - 30px);margin:0 15px;height:22px;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;font:12px sans-serif;border:1px solid #555;box-sizing:border-box;user-select:none;";
    const paint = () => {
        const v = colorWidget.value || "#000000";
        btn.style.background = v;
        btn.style.color = getContrastTextColor(v);
        const label = colorWidget.label || colorWidget.name || "stamp_color";
        btn.textContent = `${label} (${v})`;
    };
    paint();
    btn.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openPaletteBeside(colorWidget, node, e, [20, 20]);
    });
    const dom = node.addDOMWidget("4A_COLOR_DOM", "4a_color", btn, {
        serialize: false,
        hideOnZoom: false,
        hideInPanel: true,
        margin: 0,
        getHeight: () => COLOR_BAR_H,
        getMinHeight: () => COLOR_BAR_H,
        getMaxHeight: () => COLOR_BAR_H,
    });
    sizeDomWidget(dom, node, COLOR_BAR_H);
    const widgets = node.widgets || [];
    const colorIdx = widgets.findIndex((w) => w === colorWidget);
    const domIdx = widgets.indexOf(dom);
    if (colorIdx >= 0 && domIdx > colorIdx + 1) {
        widgets.splice(domIdx, 1);
        widgets.splice(colorIdx + 1, 0, dom);
    }
    node._4aColorDom = dom;
    node._4aPaintColorBar = paint;
}

function enhanceStampColorWidget(node, widget) {
    if (!widget) return;
    if (typeof widget.value === "string" && /^[0-9a-fA-F]{6}$/.test(widget.value)) {
        widget.value = `#${widget.value}`;
    }
    hideCanvasTextInput(widget);
    requestAnimationFrame(() => hideCanvasTextInput(widget));

    if (widget._4aColorEnhanced) {
        hideCanvasTextInput(widget);
        return;
    }
    widget._4aColorEnhanced = true;

    // STRING / text widgets open Comfy's "Value" hex dialog. Hide them and use a DOM bar.
    if (isTextColorWidget(widget) || widget.inputEl || widget.element) {
        hideWidgetSlot(widget);
        hideCanvasTextInput(widget);
        attachDomColorBar(node, widget);
        return;
    }

    widget.type = "COLORCODE";
    bindColorPalette(widget, node);
}

const SLIDER_FIELDS = new Set([
    "stamp_angle",
    "size_ratio",
    "target_coverage",
    "spacing_factor",
    "size_jitter",
    "angle_jitter",
]);
const SLIDER_ROW_H = 20;
const COLOR_BAR_H = 22;
const SEED_WIDGET_NAMES = new Set(["seed", "control_after_generate", "control_before_generate"]);

function ensureSliderStyles() {
    let style = document.getElementById("sc-stamp-slider-css");
    const css = `
.sc-sl{display:flex !important;flex-direction:row !important;align-items:center !important;gap:4px;width:100%;height:20px;box-sizing:border-box;padding:0 15px;user-select:none}
.sc-sl-lab{flex:0 0 auto;width:auto;font:12px/20px sans-serif;color:#d4d4d4;overflow:hidden;white-space:nowrap}
.sc-sl-track{position:relative;flex:1 1 auto;min-width:24px;height:12px;cursor:pointer}
.sc-sl-rail{position:absolute;left:0;right:0;top:4.5px;height:3px;border-radius:1px;background:rgba(255,255,255,.12)}
.sc-sl-fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:1px;background:#6b8fd6}
.sc-sl-thumb{position:absolute;top:0;left:0;width:4px;height:12px;margin-left:-2px;border-radius:1px;background:#ececec;box-shadow:0 0 0 1px rgba(0,0,0,.55);pointer-events:none}
.sc-sl-num{flex:0 0 32px;width:32px;height:18px;margin:0;padding:0 0 1px;border:1px solid rgba(255,255,255,.14);border-radius:2px;background:rgba(0,0,0,.28);color:#ddd;font:12px/18px sans-serif;text-align:center;box-sizing:border-box;vertical-align:middle;-moz-appearance:textfield}
.sc-sl-num:focus{outline:none;border-color:#6b8fd6}
.sc-sl-num::-webkit-inner-spin-button,.sc-sl-num::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
`;
    if (!style) {
        style = document.createElement("style");
        style.id = "sc-stamp-slider-css";
        document.head.appendChild(style);
    }
    style.textContent = css;
}

function sliderDecimals(step) {
    const s = String(step ?? 0.01);
    const i = s.indexOf(".");
    return i < 0 ? 0 : Math.min(4, s.length - i - 1);
}

function formatSliderValue(value, decimals) {
    const n = Number(value);
    if (!Number.isFinite(n)) return (0).toFixed(decimals);
    return n.toFixed(decimals);
}

const SLIDER_LABEL_FONT = "12px sans-serif";
const SLIDER_LABEL_MAX = 108;

function measureSliderLabelWidth(text) {
    const ctx =
        measureSliderLabelWidth.ctx ||
        (measureSliderLabelWidth.ctx = document.createElement("canvas").getContext("2d"));
    ctx.font = SLIDER_LABEL_FONT;
    return Math.ceil(ctx.measureText(text || "").width);
}

function isCensorNode(node) {
    return node?.comfyClass === "StampCensor4A" || node?.type === "StampCensor4A";
}

function collectSliderLabs(node) {
    const labs = [];
    for (const w of node.widgets || []) {
        if (!w?._4aSliderLab) continue;
        if (isCensorNode(node) && w.name === "stamp_angle") continue;
        labs.push(w._4aSliderLab);
    }
    node._4aSliderLabs = labs;
    return labs;
}

function syncNodeSliderLabels(node) {
    const labs = collectSliderLabs(node);
    if (!labs.length) return;
    let maxW = 0;
    for (const lab of labs) {
        maxW = Math.max(maxW, measureSliderLabelWidth(lab.textContent || ""));
    }
    const width = Math.min(SLIDER_LABEL_MAX, Math.max(0, maxW + 1));
    node._4aSliderLabelW = width;
    const flex = `0 0 ${width}px`;
    for (const lab of labs) {
        lab.style.flex = flex;
        lab.style.width = `${width}px`;
        lab.style.maxWidth = `${width}px`;
    }
}

function syncSliderLabelTexts(node) {
    for (const w of node.widgets || []) {
        const lab = w._4aSliderLab;
        if (!lab) continue;
        const text = w.label || w.name || "";
        if (lab.textContent !== text) {
            lab.textContent = text;
            lab.title = text;
        }
    }
    syncNodeSliderLabels(node);
}

function hideWidgetSlot(widget) {
    if (!widget) return;
    widget.hidden = true;
    widget.computeSize = () => [0, 0];
    widget.computeLayoutSize = () => ({ minHeight: 0, maxHeight: 0, minWidth: 0 });
    try {
        widget.computedHeight = 0;
    } catch {
        /* some frontend builds expose computedHeight as a getter */
    }
    widget.draw = () => {};
    widget.mouse = () => false;
    widget.onPointerDown = () => true;
}

function syncDomWidgetWidth(dom, node) {
    const width = Number(node?.size?.[0] || dom?.node?.size?.[0]);
    if (!dom || !(width > 0)) return;
    if (dom.width !== width) dom.width = width;
}

function sizeDomWidget(dom, node, height) {
    if (!dom) return;
    const opts = dom.options || (dom.options = {});
    opts.margin = 0;
    opts.hideInPanel = true;
    opts.getHeight = () => height;
    opts.getMinHeight = () => height;
    opts.getMaxHeight = () => height;
    const prevOnDraw = opts.onDraw;
    opts.onDraw = (widget) => {
        syncDomWidgetWidth(widget || dom, node);
        return prevOnDraw?.(widget);
    };
    const prevAfterResize = opts.afterResize;
    opts.afterResize = function (n) {
        syncDomWidgetWidth(this, n || node);
        return prevAfterResize?.call(this, n);
    };
    dom.computeSize = () => [node.size?.[0] || 200, height];
    dom.computeLayoutSize = () => ({ minHeight: height, maxHeight: height, minWidth: 0 });
    try {
        dom.computedHeight = height;
    } catch {
        /* some frontend builds expose computedHeight as a getter */
    }
    syncDomWidgetWidth(dom, node);
}

function hideNativeSliderWidget(widget) {
    hideWidgetSlot(widget);
}

function stripDomWidgetChrome(el) {
    const host = el.parentElement;
    if (!host) return;
    host.style.margin = "0";
    host.style.padding = "0";
    host.style.border = "none";
    host.style.background = "transparent";
    host.style.display = "block";
    for (const child of [...host.children]) {
        if (child !== el) child.style.display = "none";
    }
}

function enhanceCompactSlider(node, widget) {
    if (!widget || widget._4aSliderEnhanced) return;
    widget._4aSliderEnhanced = true;
    ensureSliderStyles();
    hideNativeSliderWidget(widget);
    if (!Number.isFinite(Number(widget._4aValue))) {
        const raw = Number(widget.value);
        widget._4aValue = Number.isFinite(raw) ? raw : Number.isFinite(widget.options?.default) ? widget.options.default : 0;
    }

    const opts = widget.options || {};
    const min = Number.isFinite(opts.min) ? opts.min : 0;
    const max = Number.isFinite(opts.max) ? opts.max : 1;
    const step = Number.isFinite(opts.step) ? opts.step : 0.01;
    const decimals = sliderDecimals(step);
    const fallback = Number.isFinite(opts.default) ? opts.default : min;

    const row = document.createElement("div");
    row.className = "sc-sl";
    row.style.cssText = "display:flex;flex-direction:row;align-items:center;gap:4px;width:100%;height:20px;padding:0 15px;box-sizing:border-box;";
    const lab = document.createElement("span");
    lab.className = "sc-sl-lab";
    const track = document.createElement("div");
    track.className = "sc-sl-track";
    const rail = document.createElement("div");
    rail.className = "sc-sl-rail";
    const fillEl = document.createElement("div");
    fillEl.className = "sc-sl-fill";
    const thumb = document.createElement("div");
    thumb.className = "sc-sl-thumb";
    const num = document.createElement("input");
    num.type = "text";
    num.inputMode = "decimal";
    num.className = "sc-sl-num";

    const liveValue = () => {
        const raw = Number(widget._4aValue ?? widget.value);
        return Number.isFinite(raw) ? Math.min(max, Math.max(min, raw)) : fallback;
    };

    const paint = () => {
        lab.textContent = widget.label || widget.name || "";
        lab.title = lab.textContent;
        syncNodeSliderLabels(node);
        const v = liveValue();
        num.value = formatSliderValue(v, decimals);
        const pct = max === min ? 0 : ((v - min) / (max - min)) * 100;
        fillEl.style.width = `${pct}%`;
        thumb.style.left = `${pct}%`;
    };

    const commit = (next) => {
        let v = Number(next);
        if (!Number.isFinite(v)) {
            paint();
            return;
        }
        v = Math.min(max, Math.max(min, v));
        const q = decimals > 0 ? Number(v.toFixed(decimals)) : Math.round(v);
        widget._4aValue = q;
        widget.value = q;
        try {
            widget.callback?.(q);
        } finally {
            widget.value = q;
            widget._4aValue = q;
        }
        paint();
        rememberNodeParams(node);
        node.setDirtyCanvas?.(true, true);
        node._4aRefreshPreview?.(PREVIEW_DEBOUNCE_MS);
    };

    const valueFromPointer = (e) => {
        const rect = track.getBoundingClientRect();
        const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / Math.max(1, rect.width)));
        return min + x * (max - min);
    };

    const onDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        commit(valueFromPointer(e));
    };
    track.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        track.setPointerCapture(e.pointerId);
        onDrag(e);
    });
    track.addEventListener("pointermove", (e) => {
        if (track.hasPointerCapture?.(e.pointerId)) onDrag(e);
    });
    track.addEventListener("dblclick", (e) => {
        e.preventDefault();
        commit(fallback);
    });
    num.addEventListener("change", () => commit(num.value));
    num.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            num.blur();
        }
    });
    row.addEventListener("pointerdown", (e) => e.stopPropagation());
    row.addEventListener("pointermove", (e) => e.stopPropagation());
    row.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    rail.appendChild(fillEl);
    track.append(rail, thumb);
    row.append(lab, track, num);
    widget._4aSliderLab = lab;
    if (!node._4aSliderLabs) node._4aSliderLabs = [];
    if (!node._4aSliderLabs.includes(lab)) node._4aSliderLabs.push(lab);
    paint();

    const prevCb = widget.callback;
    widget.callback = function (...args) {
        const r = prevCb?.apply(this, args);
        paint();
        return r;
    };

    const dom = node.addDOMWidget(`4A_SLIDER_${widget.name}`, "4a_slider", row, {
        serialize: false,
        hideOnZoom: false,
        hideInPanel: true,
        margin: 0,
        getHeight: () => SLIDER_ROW_H,
        getMinHeight: () => SLIDER_ROW_H,
        getMaxHeight: () => SLIDER_ROW_H,
    });
    sizeDomWidget(dom, node, SLIDER_ROW_H);
    dom.__4aFor = widget.name;
    const widgets = node.widgets || [];
    const srcIdx = widgets.findIndex((w) => w === widget);
    const domIdx = widgets.indexOf(dom);
    if (srcIdx >= 0 && domIdx >= 0 && domIdx !== srcIdx + 1) {
        widgets.splice(domIdx, 1);
        widgets.splice(srcIdx + 1, 0, dom);
    }
    requestAnimationFrame(() => {
        stripDomWidgetChrome(row);
        syncNodeSliderLabels(node);
    });
    widget._4aPaintSlider = paint;
}

function enhanceNodeSliders(node) {
    for (const w of [...(node.widgets || [])]) {
        if (!SLIDER_FIELDS.has(w.name)) continue;
        if (isCensorNode(node) && w.name === "stamp_angle") continue;
        enhanceCompactSlider(node, w);
    }
    syncNodeSliderLabels(node);
}

function isChromeWidget(w) {
    if (!w) return true;
    if (isPreviewWidget(w)) return true;
    if (w.type === "converted-widget") return true;
    if (w.name === "4A_COLOR_DOM" || w.name?.startsWith("4A_SLIDER_") || w.type === "4a_slider") return true;
    return false;
}

function isStampPackNode(node) {
    return isStampLoadNode(node) || isCensorNode(node);
}

function snapshotNodeParams(node) {
    const out = {};
    for (const w of node.widgets || []) {
        if (!w?.name || isChromeWidget(w)) continue;
        out[w.name] = w._4aValue ?? w.value;
    }
    return out;
}

function rememberNodeParams(node) {
    if (!node) return;
    node._4aSavedParams = snapshotNodeParams(node);
}

function restoreNodeParams(node, snap) {
    if (!node || !snap) return;
    for (const w of node.widgets || []) {
        if (!w?.name || !Object.prototype.hasOwnProperty.call(snap, w.name)) continue;
        const v = snap[w.name];
        if (v === undefined) continue;
        w.value = v;
        if (w._4aSliderEnhanced && Number.isFinite(Number(v))) w._4aValue = Number(v);
        w._4aPaintSlider?.();
    }
    node._4aPaintColorBar?.();
}

function syncEnhancedFromWidgets(node) {
    for (const w of node.widgets || []) {
        if (!w._4aSliderEnhanced) continue;
        const raw = Number(w.value);
        if (Number.isFinite(raw)) w._4aValue = raw;
        w._4aPaintSlider?.();
    }
    node._4aPaintColorBar?.();
    rememberNodeParams(node);
}

function restoreAllRememberedParams() {
    for (const n of app.graph?._nodes || []) {
        if (!isStampPackNode(n)) continue;
        restoreNodeParams(n, n._4aSavedParams);
    }
}

function widgetValues(node) {
    const out = {};
    const owned = new Set();
    for (const w of node.widgets || []) {
        if (!w?.name || isChromeWidget(w)) continue;
        const value = w._4aValue ?? w.value;
        if (w._4aSliderEnhanced || w._4aColorEnhanced || w._4aValue != null) {
            out[w.name] = value;
            owned.add(w.name);
            continue;
        }
        if (owned.has(w.name)) continue;
        out[w.name] = value;
    }
    return out;
}

function readNumberFrom(values, name, fallback) {
    const n = Number(values?.[name]);
    return Number.isFinite(n) ? n : fallback;
}

function readBoolFrom(values, name, fallback = false) {
    const v = values?.[name];
    if (v === false || v === 0 || v === "false") return false;
    if (v === true || v === 1 || v === "true") return true;
    return fallback;
}

function isPreviewWidget(w) {
    if (!w) return false;
    if (w.type === "4A_PREVIEW" || w.name === "4A_PREVIEW_DOM") return true;
    if (w.name === "stamp_preview_panel" || w.name === "demo_preview_panel") return true;
    return false;
}

function stripBrokenPreviewWidgets(node) {
    if (!node.widgets) return;
    node.widgets = node.widgets.filter((w) => !isPreviewWidget(w));
    node._4aPreviewWidget = null;
    node._4aPreviewPainted = false;
}

const PREVIEW_MIN = { square: 160, wide: 80 };
const PREVIEW_PAD = 4;
const COMBO_ROW_H = 24;

function isOfficialImageRow(widget) {
    if (!widget) return false;
    const type = String(widget.type || "");
    if (widget.name === "image") return true;
    if (type === "button" || type === "IMAGEUPLOAD") return true;
    if (widget.name === "upload" || widget.value === "image") return true;
    return false;
}

function widgetLayoutHeight(node, widget) {
    if (isOfficialImageRow(widget)) return COMBO_ROW_H;
    if (typeof widget.computeLayoutSize === "function") {
        const layout = widget.computeLayoutSize(node);
        if (Number.isFinite(layout?.minHeight) && layout.minHeight > 0) return layout.minHeight;
    }
    if (typeof widget.computeSize === "function") {
        const sz = widget.computeSize(node.size?.[0]);
        if (Array.isArray(sz) && Number.isFinite(sz[1]) && sz[1] > 0) return sz[1];
    }
    if (Number.isFinite(widget.computedHeight) && widget.computedHeight > 0) return widget.computedHeight;
    return 0;
}

function shouldReservePreview(node) {
    if (node._4aPreview?.img) return true;
    if (isStampLoadNode(node)) return true;
    return !!findLinkedStampLoad(node);
}

function widgetsBottom(node) {
    const title = window.LiteGraph?.NODE_TITLE_HEIGHT || 30;
    let bottom = 0;
    for (const w of node.widgets || []) {
        if (!w || isPreviewWidget(w) || w.hidden || w.type === "converted-widget") continue;
        const h = widgetLayoutHeight(node, w);
        if (!(h > 0)) continue;
        const wy = Number.isFinite(w.last_y) ? w.last_y : w.y;
        if (Number.isFinite(wy) && wy >= 0) bottom = Math.max(bottom, wy + h);
    }
    return bottom > title ? bottom : title + 8;
}

function stampSpinFit(img) {
    const iw = img.naturalWidth || img.width || 1;
    const ih = img.naturalHeight || img.height || 1;
    return { iw, ih, side: Math.hypot(iw, ih) };
}

function dirtyPreviewCanvas(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
    const canvas = app.canvas;
    canvas?.setDirty?.(true, true);
    requestAnimationFrame(() => {
        node.setDirtyCanvas?.(true, true);
        canvas?.setDirty?.(true, true);
        canvas?.draw?.(true, true);
    });
}

function applyPreviewMinSize(node) {
    if (node._4aResizing) return;
    node._4aResizing = true;
    try {
        const minH = PREVIEW_MIN[node._4aPreviewKind] || PREVIEW_MIN.square;
        const pad = isStampLoadNode(node) ? 0 : PREVIEW_PAD;
        const fromWidgets = widgetsBottom(node) + pad + minH + pad;
        const computed = node.computeSize();
        const fromCompute = Array.isArray(computed) && Number.isFinite(computed[1]) ? computed[1] : 0;
        const need = Math.max(fromCompute, fromWidgets);
        const cur = node.size?.[1] || 0;
        const width = node.size?.[0] || 240;
        if (cur < need) node.setSize([width, need]);
    } finally {
        node._4aResizing = false;
    }
}

function compactOfficialImagePreview(node) {
    if (node._4aImageCompact) return;
    node._4aImageCompact = true;
    node.imgs = null;
    node.imageIndex = null;
    for (const w of node.widgets || []) {
        if (!isOfficialImageRow(w)) continue;
        w.computeSize = () => [node.size?.[0] || 200, COMBO_ROW_H];
        w.computeLayoutSize = () => ({ minHeight: COMBO_ROW_H, maxHeight: COMBO_ROW_H, minWidth: 0 });
        try {
            w.computedHeight = COMBO_ROW_H;
        } catch {
            /* some frontend builds expose computedHeight as a getter */
        }
    }
    const prevBg = node.onDrawBackground;
    node.onDrawBackground = function () {
        this.imgs = null;
        this.imageIndex = null;
        return prevBg?.apply(this, arguments);
    };
}

function shrinkCustomLoadIfBloated(node) {
    if (node._4aCustomShrunk || node._4aResizing) return;
    node._4aCustomShrunk = true;
    node._4aResizing = true;
    try {
        const next = node.computeSize();
        const cur = node.size?.[1] || 0;
        if (Array.isArray(next) && Number.isFinite(next[1]) && cur > next[1] + 4) {
            node.setSize([node.size[0], next[1]]);
        }
    } finally {
        node._4aResizing = false;
    }
}

function attachCanvasPreview(node, kind) {
    node._4aPreviewKind = kind;
    if (node._4aPreviewReady) return;
    node._4aPreviewReady = true;
    node._4aPreview = { img: null, key: "", url: "", layoutKey: "" };
    node.imgs = null;
    node.imageIndex = null;
    node.resizable = true;
    if (typeof node.setSizeForImage === "function") {
        node.setSizeForImage = function () {};
    }

    const prevDraw = node.onDrawForeground;
    node.onDrawForeground = function (ctx) {
        prevDraw?.apply(this, arguments);
        syncSliderLabelTexts(this);
        const img = this._4aPreview?.img;
        if (!img) return;
        this.imgs = null;
        this.imageIndex = null;
        const load = isStampLoadNode(this);
        const pad = load ? 0 : PREVIEW_PAD;
        const y = widgetsBottom(this) + pad;
        const boxW = Math.max(0, this.size[0]);
        const boxH = Math.max(0, this.size[1] - y - pad);
        if (boxW < 8 || boxH < 8) {
            if (!this._4aPreviewGrowOnce) {
                this._4aPreviewGrowOnce = true;
                applyPreviewMinSize(this);
                dirtyPreviewCanvas(this);
            }
            return;
        }

        const iw = img.naturalWidth || img.width || 1;
        const ih = img.naturalHeight || img.height || 1;
        let dw;
        let dh;
        let angle = 0;
        if (load) {
            const fit = this._4aPreview.spinFit || (this._4aPreview.spinFit = stampSpinFit(img));
            const box = Math.min(boxW, boxH);
            const scale = box / (fit.side || 1);
            dw = fit.iw * scale;
            dh = fit.ih * scale;
            angle = Number(readStampAngle(this) || 0);
            const cx = this.size[0] * 0.5;
            const cy = y + box * 0.5;
            const smooth = ctx.imageSmoothingEnabled;
            ctx.save();
            ctx.imageSmoothingEnabled = true;
            ctx.translate(cx, cy);
            if (angle) ctx.rotate((angle * Math.PI) / 180);
            ctx.drawImage(img, -dw * 0.5, -dh * 0.5, dw, dh);
            ctx.imageSmoothingEnabled = smooth;
            ctx.restore();
            return;
        }
        if (this._4aPreviewKind === "square") {
            dw = dh = Math.min(boxW, boxH);
        } else {
            const scale = Math.min(boxW / iw, boxH / ih);
            dw = iw * scale;
            dh = ih * scale;
        }
        if (dw < 8 || dh < 8) return;
        const dx = (this.size[0] - dw) / 2;
        const dy = y;
        const smooth = ctx.imageSmoothingEnabled;
        ctx.save();
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(img, dx, dy, dw, dh);
        ctx.imageSmoothingEnabled = smooth;
        ctx.restore();
    };

    const prevCompute = node.computeSize;
    node.computeSize = function () {
        const size = prevCompute?.apply(this, arguments) || [this.size?.[0] || 240, 80];
        if (shouldReservePreview(this)) {
            size[1] += PREVIEW_MIN[this._4aPreviewKind] || PREVIEW_MIN.wide;
            if (!isStampLoadNode(this)) size[1] += PREVIEW_PAD;
        }
        return size;
    };

    const prevExec = node.onExecuted;
    node.onExecuted = function () {
        const r = prevExec?.apply(this, arguments);
        this.imgs = null;
        this.imageIndex = null;
        return r;
    };
}

function setPreviewImage(node, imageEl, key) {
    if (!node._4aPreview) node._4aPreview = { img: null, key: "", url: "", layoutKey: "" };
    const had = !!node._4aPreview.img;
    if (node._4aPreview.url && node._4aPreview.url.startsWith("blob:")) {
        URL.revokeObjectURL(node._4aPreview.url);
    }
    node._4aPreview.img = imageEl || null;
    node._4aPreview.spinFit = imageEl && isStampLoadNode(node) ? stampSpinFit(imageEl) : null;
    node._4aPreview.key = key || "";
    node._4aPreview.url = imageEl?.src || "";
    node.imgs = null;
    node.imageIndex = null;
    if (had !== !!imageEl) {
        applyPreviewMinSize(node);
    } else if (!imageEl && !node._4aEmptySized) {
        node._4aEmptySized = true;
        applyPreviewMinSize(node);
    }
    if (imageEl) node._4aEmptySized = false;
    if (imageEl) applyPreviewMinSize(node);
    dirtyPreviewCanvas(node);
}

function setPreviewPlaceholder(node, key, text) {
    if (text) node._4aPlaceholder = text;
    setPreviewImage(node, null, key);
}

function readImageWidgetRef(srcNode) {
    const w = srcNode?.widgets?.find((x) => x.name === "image");
    const v = w?.value;
    if (typeof v === "string" && v.trim()) {
        let raw = v.trim().split("\\").join("/");
        let type = "input";
        const annotated = raw.match(/^(.*) \[(input|output|temp)\]$/i);
        if (annotated) {
            raw = annotated[1].trim();
            type = annotated[2].toLowerCase();
        }
        if (!raw) return null;
        const i = raw.lastIndexOf("/");
        if (i >= 0) {
            return { filename: raw.slice(i + 1), subfolder: raw.slice(0, i), type };
        }
        return { filename: raw, subfolder: "", type };
    }
    if (v && typeof v === "object") {
        const filename = v.filename || v.name || "";
        if (!filename) return null;
        return {
            filename,
            subfolder: v.subfolder || "",
            type: v.type || "input",
        };
    }
    return null;
}

function customStampKey(loadNode) {
    const ref = readImageWidgetRef(loadNode);
    if (ref?.filename) return `file:${ref.type}:${ref.subfolder}:${ref.filename}`;
    return "";
}

function loadHtmlImage(url) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = url;
    });
}

function hasImageTransfer(dataTransfer) {
    if (!dataTransfer) return false;
    const files = [...(dataTransfer.files || [])];
    const types = [...(dataTransfer.types || [])];
    return files.some((f) => f.type?.startsWith("image/") || /\.(?:png|jpe?g|webp|gif|bmp|tiff?|avif)$/i.test(f.name || ""))
        || types.includes("Files")
        || types.includes("application/x-comfy-asset-info");
}

function refreshCustomLoadWhenReady(node, tries = 24) {
    if (!isCustomStampLoadNode(node)) {
        node._4aRefreshPreview?.(0);
        return;
    }
    if (customStampKey(node)) {
        node._4aRefreshPreview?.(0);
        applyPreviewMinSize(node);
        dirtyPreviewCanvas(node);
        return;
    }
    if (tries <= 0) return;
    setTimeout(() => refreshCustomLoadWhenReady(node, tries - 1), 50);
}

function attachImageDrop(node) {
    if (node._4aDropReady) return;
    node._4aDropReady = true;
    const prevOver = node.onDragOver?.bind(node);
    node.onDragOver = function (event) {
        if (hasImageTransfer(event?.dataTransfer)) return true;
        return prevOver?.(event) ?? false;
    };
    const prevDrop = node.onDragDrop?.bind(node);
    node.onDragDrop = function (event) {
        const isImage = hasImageTransfer(event?.dataTransfer);
        if (!isImage) return prevDrop?.(event) ?? false;
        const result = prevDrop?.(event);
        refreshCustomLoadWhenReady(this);
        return result ?? true;
    };
    const imageW = node.widgets?.find((w) => w.name === "image");
    if (imageW && !imageW._4aDropHooked) {
        imageW._4aDropHooked = true;
        const prevCb = imageW.callback;
        imageW.callback = function (...args) {
            const r = prevCb?.apply(this, args);
            refreshCustomLoadWhenReady(node);
            return r;
        };
    }
}

function stripLegacyCustomImageWidgets(node) {
    if (!node.widgets) return;
    const dropNames = new Set(["image", "upload", "choose file to upload"]);
    const kept = [];
    for (const w of node.widgets) {
        const type = String(w.type || "");
        if (dropNames.has(w.name) || type === "image" || type === "IMAGEUPLOAD") {
            hideWidgetSlot(w);
            continue;
        }
        if (w.linkedWidgets?.length) {
            w.linkedWidgets = w.linkedWidgets.filter(
                (lw) => !dropNames.has(lw.name) && String(lw.type || "") !== "IMAGEUPLOAD"
            );
        }
        kept.push(w);
    }
    node.widgets.length = 0;
    node.widgets.push(...kept);
}

async function loadPickedStampImage(loadNode) {
    const ref = readImageWidgetRef(loadNode);
    if (!ref?.filename) return null;
    const q = new URLSearchParams({
        custom_filename: ref.filename,
        custom_subfolder: ref.subfolder || "",
        custom_type: ref.type || "input",
    });
    return {
        img: await loadHtmlImage(`/4a_stampcensor/stamp_preview?${q}`),
        key: customStampKey(loadNode),
    };
}

function findLinkedStampLoad(node) {
    const idx = node.inputs?.findIndex((i) => i.name === "stamp") ?? -1;
    if (idx < 0) return null;
    const linkId = node.inputs[idx].link;
    if (linkId == null) return null;
    const link = node.graph.links[linkId];
    if (!link) return null;
    return node.graph.getNodeById(link.origin_id);
}

function isBuiltinStampLoadNode(n) {
    return n && (n.type === "StampLoad4A" || n.comfyClass === "StampLoad4A");
}

function isCustomStampLoadNode(n) {
    return n && (n.type === "StampCustomLoad4A" || n.comfyClass === "StampCustomLoad4A");
}

function isStampLoadNode(n) {
    return isBuiltinStampLoadNode(n) || isCustomStampLoadNode(n);
}

function hideSyncedCensorAngle(node) {
    const w = node.widgets?.find((x) => x.name === "stamp_angle");
    hideWidgetSlot(w);
    if (w) {
        w.options = { ...(w.options || {}), hideInPanel: true, hidden: true };
    }
    for (const sl of node.widgets || []) {
        if (sl?.name === "4A_SLIDER_stamp_angle" || sl?.__4aFor === "stamp_angle") {
            hideWidgetSlot(sl);
        }
    }
}

function stripSeedWidgets(node) {
    if (!node.widgets) return;
    const kept = [];
    for (const w of node.widgets) {
        if (SEED_WIDGET_NAMES.has(w.name)) {
            w.serialize = false;
            hideWidgetSlot(w);
            continue;
        }
        if (w.linkedWidgets?.length) {
            w.linkedWidgets = w.linkedWidgets.filter((lw) => !SEED_WIDGET_NAMES.has(lw.name));
        }
        kept.push(w);
    }
    node.widgets.length = 0;
    node.widgets.push(...kept);
}

function ensureSeedInput(node) {
    if (!node.inputs?.some((i) => i.name === "seed")) {
        node.addInput("seed", "INT");
    }
}

function readLinkedInt(node, inputName) {
    const inp = node.inputs?.find((i) => i.name === inputName);
    if (!inp || inp.link == null) return null;
    const link = node.graph?.links?.[inp.link];
    if (!link) return null;
    const src = node.graph.getNodeById(link.origin_id);
    if (!src) return null;
    for (const name of ["value", "INT", "seed", "int"]) {
        const n = Number(src.widgets?.find((x) => x.name === name)?.value);
        if (Number.isFinite(n)) return n;
    }
    for (const w of src.widgets || []) {
        const n = Number(w.value);
        if (Number.isFinite(n) && w.type !== "combo" && w.type !== "toggle") return n;
    }
    return null;
}

function readCensorSeed(node) {
    const linked = readLinkedInt(node, "seed");
    if (Number.isFinite(linked) && linked >= 0) return linked >>> 0;
    if (!Number.isFinite(node._4aPreviewSeed)) {
        node._4aPreviewSeed = (Math.random() * 0x100000000) >>> 0;
    }
    return node._4aPreviewSeed;
}

function tidyCensorWidgets(node) {
    const widgets = node.widgets;
    if (!widgets?.length) return;
    const used = new Set();
    const next = [];
    const pull = (name) => {
        const w = widgets.find((x) => x.name === name);
        if (!w || used.has(w)) return;
        next.push(w);
        used.add(w);
        for (const lw of w.linkedWidgets || []) {
            if (widgets.includes(lw) && !used.has(lw)) {
                next.push(lw);
                used.add(lw);
            }
        }
    };
    for (const name of [
        "auto_rotate",
        "min_size",
        "max_size",
        "size_ratio",
        "target_coverage",
        "spacing_factor",
        "size_jitter",
        "angle_jitter",
        "stamp_angle",
    ]) {
        pull(name);
        const sl = widgets.find((x) => x.__4aFor === name);
        if (sl && !used.has(sl)) {
            next.push(sl);
            used.add(sl);
        }
    }
    for (const w of widgets) {
        if (!used.has(w)) next.push(w);
    }
    widgets.length = 0;
    widgets.push(...next);
    hideSyncedCensorAngle(node);
}

function censorLayoutKey(node, wv, sw, stampSrc) {
    const custom = customStampKey(stampSrc);
    return JSON.stringify({
        p: custom || sw.stamp_preset || "",
        c: custom ? "" : String(sw.stamp_color || ""),
        t: readNumberFrom(wv, "target_coverage", 0.8),
        r: readNumberFrom(wv, "size_ratio", 0.28),
        sp: readNumberFrom(wv, "spacing_factor", 0.3),
        min: readNumberFrom(wv, "min_size", 24),
        max: readNumberFrom(wv, "max_size", 512),
        sj: readNumberFrom(wv, "size_jitter", 0.15),
        aj: readNumberFrom(wv, "angle_jitter", 0),
        seed: readCensorSeed(node),
    });
}

function readStampAngle(node) {
    return node?.widgets?.find((x) => x.name === "stamp_angle")?.value ?? 0;
}

function writeStampAngle(node, angle) {
    const w = node?.widgets?.find((x) => x.name === "stamp_angle");
    if (w) w.value = angle;
}

function syncCensorAngleFromLoad(censorNode) {
    const src = findLinkedStampLoad(censorNode);
    writeStampAngle(censorNode, src && isStampLoadNode(src) ? readStampAngle(src) : 0);
}

function syncLoadAngleToCensors(loadNode) {
    const angle = readStampAngle(loadNode);
    for (const n of loadNode.graph?._nodes || []) {
        if (
            (n.type === "StampCensor4A" || n.comfyClass === "StampCensor4A") &&
            findLinkedStampLoad(n) === loadNode
        ) {
            writeStampAngle(n, angle);
        }
    }
}

const PREVIEW_DEBOUNCE_MS = 160;
const ANGLE_CENSOR_DEBOUNCE_MS = 80;

function hookWidgets(node, refreshFn) {
    node._4aRefreshPreview = (delay = PREVIEW_DEBOUNCE_MS) => {
        clearTimeout(node._4aPreviewTimer);
        node._4aPreviewTimer = setTimeout(() => refreshFn(node), delay);
    };
    for (const w of node.widgets || []) {
        if (isChromeWidget(w) || w._4aHooked) continue;
        w._4aHooked = true;
        const prev = w.callback;
        w.callback = function (...args) {
            const r = prev?.apply(this, args);
            node._4aPaintColorBar?.();
            rememberNodeParams(node);
            if (w.name === "stamp_angle") {
                node.setDirtyCanvas?.(true, true);
                node._4aRefreshPreview(ANGLE_CENSOR_DEBOUNCE_MS);
            } else {
                node._4aRefreshPreview(PREVIEW_DEBOUNCE_MS);
            }
            return r;
        };
    }
}

async function refreshStampLoadPreview(node) {
    const wv = widgetValues(node);
    if (isCustomStampLoadNode(node)) {
        const picked = customStampKey(node);
        if (!picked) {
            setPreviewPlaceholder(node, "custom", "");
            return;
        }
        const gen = (node._4aPreviewGen = (node._4aPreviewGen || 0) + 1);
        try {
            const custom = await loadPickedStampImage(node);
            if (gen !== node._4aPreviewGen) return;
            if (!custom?.img) {
                setPreviewPlaceholder(node, "custom", "");
                return;
            }
            if (node._4aPreview?.key === custom.key && node._4aPreview.img) {
                node.setDirtyCanvas?.(true, true);
                return;
            }
            setPreviewImage(node, custom.img, custom.key);
        } catch (e) {
            if (gen !== node._4aPreviewGen) return;
            console.warn("[4A StampCensor] custom stamp preview failed", e);
            setPreviewPlaceholder(node, "error", "预览加载失败");
        }
        return;
    }
    const key = `${wv.stamp_preset}|${wv.stamp_color}`;
    if (node._4aPreview?.key === key && node._4aPreview.img) {
        node.setDirtyCanvas?.(true, true);
        return;
    }
    const gen = (node._4aPreviewGen = (node._4aPreviewGen || 0) + 1);
    try {
        const url =
            `/4a_stampcensor/stamp_preview?preset=${encodeURIComponent(wv.stamp_preset || "heart_wobbly_a")}` +
            `&color=${encodeURIComponent(wv.stamp_color || "#000000")}`;
        const img = await loadHtmlImage(url);
        if (gen !== node._4aPreviewGen) return;
        setPreviewImage(node, img, key);
    } catch (e) {
        if (gen !== node._4aPreviewGen) return;
        console.warn("[4A StampCensor] stamp preview failed", e);
        setPreviewPlaceholder(node, "error", "预览加载失败");
    }
}

async function refreshCensorDemo(node) {
    const stampSrc = findLinkedStampLoad(node);
    if (!stampSrc || !isStampLoadNode(stampSrc)) {
        setPreviewPlaceholder(node, "nostamp", "");
        return;
    }
    const wv = widgetValues(node);
    const sw = widgetValues(stampSrc);
    const layoutKey = censorLayoutKey(node, wv, sw, stampSrc);
    const seed = readCensorSeed(node);
    const autoRotate = readBoolFrom(wv, "auto_rotate", true);
    const stampAngle = readNumberFrom(sw, "stamp_angle", 0);
    const key = `${layoutKey}|a:${autoRotate ? 1 : 0}|ang:${stampAngle}`;
    if (node._4aPreview?.key === key && node._4aPreview.img) return;
    const reuseLayout = node._4aPreview?.layoutKey === layoutKey && !!node._4aPreview.img;
    const gen = (node._4aPreviewGen = (node._4aPreviewGen || 0) + 1);
    try {
        const customRef = readImageWidgetRef(stampSrc);
        const body = {
            preset: sw.stamp_preset || "heart_wobbly_a",
            color: sw.stamp_color || "#000000",
            stamp_angle: stampAngle,
            target_coverage: readNumberFrom(wv, "target_coverage", 0.8),
            size_ratio: readNumberFrom(wv, "size_ratio", 0.28),
            min_size: readNumberFrom(wv, "min_size", 24),
            max_size: readNumberFrom(wv, "max_size", 512),
            spacing_factor: readNumberFrom(wv, "spacing_factor", 0.3),
            size_jitter: readNumberFrom(wv, "size_jitter", 0.15),
            angle_jitter: readNumberFrom(wv, "angle_jitter", 0),
            auto_rotate: autoRotate,
            seed,
            layout_key: layoutKey,
            reuse_layout: reuseLayout,
        };
        if (customRef?.filename) {
            body.custom_filename = customRef.filename;
            body.custom_subfolder = customRef.subfolder || "";
            body.custom_type = customRef.type || "input";
        }
        const res = await api.fetchApi("/4a_stampcensor/demo_preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        if (gen !== node._4aPreviewGen) return;
        const url = URL.createObjectURL(blob);
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = url;
        });
        if (gen !== node._4aPreviewGen) return;
        setPreviewImage(node, img, key);
        if (node._4aPreview) {
            node._4aPreview.layoutKey = layoutKey;
            node._4aPreview.autoRotate = autoRotate;
        }
    } catch (e) {
        if (gen !== node._4aPreviewGen) return;
        console.warn("[4A StampCensor] demo preview failed", e);
        setPreviewPlaceholder(node, "error", "预览加载失败");
    }
}

function setupStampSourceNode(node, { imageDrop = false } = {}) {
    if (!imageDrop) stripLegacyCustomImageWidgets(node);
    if (imageDrop) compactOfficialImagePreview(node);
    if (node._4aUiReady) {
        const colorW = node.widgets?.find((w) => w.name === "stamp_color");
        if (colorW) enhanceStampColorWidget(node, colorW);
        enhanceNodeSliders(node);
        attachCanvasPreview(node, "square");
        applyPreviewMinSize(node);
        if (imageDrop) {
            attachImageDrop(node);
            shrinkCustomLoadIfBloated(node);
        }
        requestAnimationFrame(() => applyPreviewMinSize(node));
        syncEnhancedFromWidgets(node);
        node._4aRefreshPreview?.();
        return;
    }
    node._4aUiReady = true;
    node.imgs = null;
    node.resizable = true;
    stripBrokenPreviewWidgets(node);
    const colorW = node.widgets?.find((w) => w.name === "stamp_color");
    if (colorW) enhanceStampColorWidget(node, colorW);
    enhanceNodeSliders(node);
    attachCanvasPreview(node, "square");
    applyPreviewMinSize(node);
    requestAnimationFrame(() => applyPreviewMinSize(node));
    if (imageDrop) {
        attachImageDrop(node);
        shrinkCustomLoadIfBloated(node);
        requestAnimationFrame(() => applyPreviewMinSize(node));
    }
    hookWidgets(node, (n) => {
        syncLoadAngleToCensors(n);
        refreshStampLoadPreview(n);
    });
    if (!node._4aConnHooked) {
        node._4aConnHooked = true;
        const old = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const r = old?.apply(this, args);
            this._4aRefreshPreview?.();
            return r;
        };
    }
    syncEnhancedFromWidgets(node);
    node._4aRefreshPreview();
}

let _lastStampPresets = null;
let _stampPresetRefresh = null;

async function fetchStampPresets({ refresh = false } = {}) {
    const q = refresh ? "?refresh=1" : "";
    const res = await api.fetchApi(`/4a_stampcensor/presets${q}`);
    const data = await res.json();
    return Array.isArray(data?.presets) ? data.presets : [];
}

function applyStampPresets(node, names) {
    const w = node.widgets?.find((x) => x.name === "stamp_preset");
    if (!w || !names?.length) return false;
    const values = [...names];
    if (w.value && !values.includes(w.value)) values.unshift(w.value);
    w.options = { ...(w.options || {}), values };
    if (w.value && values.includes(w.value)) return false;
    if (w.value != null && String(w.value).trim() !== "") return false;
    w.value = names.includes("heart_wobbly_a") ? "heart_wobbly_a" : names[0];
    return true;
}

function applyStampPresetsToGraph(names) {
    _lastStampPresets = names;
    const nodes = app.graph?._nodes || [];
    for (const n of nodes) {
        if (!isBuiltinStampLoadNode(n)) continue;
        applyStampPresets(n, names);
        n._4aRefreshPreview?.();
    }
}

function refreshStampPresetCombos({ refresh = true } = {}) {
    if (_stampPresetRefresh) return _stampPresetRefresh;
    _stampPresetRefresh = (async () => {
        const names = await fetchStampPresets({ refresh });
        applyStampPresetsToGraph(names);
        return names;
    })().finally(() => {
        _stampPresetRefresh = null;
    });
    return _stampPresetRefresh;
}

function setupStampLoad(node) {
    setupStampSourceNode(node, { imageDrop: false });
    const keep = () => {
        applyStampPresets(node, _lastStampPresets);
        restoreNodeParams(node, node._4aSavedParams);
    };
    if (_lastStampPresets) keep();
    else refreshStampPresetCombos({ refresh: true }).then(keep);
}

function setupStampCustomLoad(node) {
    setupStampSourceNode(node, { imageDrop: true });
}

function setupStampCensor(node) {
    if (node._4aUiReady) {
        stripSeedWidgets(node);
        ensureSeedInput(node);
        tidyCensorWidgets(node);
        enhanceNodeSliders(node);
        hideSyncedCensorAngle(node);
        attachCanvasPreview(node, "square");
        hookWidgets(node, refreshCensorDemo);
        syncEnhancedFromWidgets(node);
        node._4aRefreshPreview?.();
        return;
    }
    node._4aUiReady = true;
    node.imgs = null;
    node.resizable = true;
    stripBrokenPreviewWidgets(node);
    stripSeedWidgets(node);
    ensureSeedInput(node);
    tidyCensorWidgets(node);
    enhanceNodeSliders(node);
    hideSyncedCensorAngle(node);
    attachCanvasPreview(node, "square");
    applyPreviewMinSize(node);
    hookWidgets(node, refreshCensorDemo);
    syncCensorAngleFromLoad(node);
    if (!node._4aConnHooked) {
        node._4aConnHooked = true;
        const old = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const r = old?.apply(this, args);
            syncCensorAngleFromLoad(this);
            this._4aRefreshPreview?.();
            const src = findLinkedStampLoad(this);
            if (src && isStampLoadNode(src) && !src._4aLinkedToCensor) {
                src._4aLinkedToCensor = true;
                const prev = src._4aRefreshPreview;
                src._4aRefreshPreview = (delay) => {
                    prev?.(delay);
                    for (const n of this.graph?._nodes || []) {
                        if (
                            (n.type === "StampCensor4A" || n.comfyClass === "StampCensor4A") &&
                            findLinkedStampLoad(n) === src
                        ) {
                            n._4aRefreshPreview?.(delay);
                        }
                    }
                };
            }
            return r;
        };
    }
    syncEnhancedFromWidgets(node);
    node._4aRefreshPreview();
}

app.registerExtension({
    name: "ComfyUI-4A-StampCensor.ui",

    async setup() {
        try {
            await refreshStampPresetCombos({ refresh: true });
        } catch (e) {
            console.warn("[4A StampCensor] preset refresh on load failed", e);
        }
        restoreAllRememberedParams();
    },

    async refreshComboInNodes() {
        try {
            await refreshStampPresetCombos({ refresh: true });
        } catch (e) {
            console.warn("[4A StampCensor] preset refresh on R failed", e);
        }
        restoreAllRememberedParams();
        requestAnimationFrame(restoreAllRememberedParams);
        setTimeout(restoreAllRememberedParams, 50);
    },

    getCustomWidgets() {
        return {
            COLORCODE: (node, inputName, inputData) => ({
                widget: node.addCustomWidget(makeColorWidget(inputName, inputData)),
                minWidth: 150,
                minHeight: 22,
            }),
        };
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (
            nodeData?.name === "StampLoad4A" ||
            nodeData?.name === "StampCustomLoad4A" ||
            nodeData?.name === "StampCensor4A"
        ) {
            const prevCfg = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                const r = prevCfg?.apply(this, arguments);
                syncEnhancedFromWidgets(this);
                return r;
            };
        }
        if (nodeData?.name === "StampLoad4A" || nodeData?.name === "StampCustomLoad4A") {
            const prev = nodeType.prototype.onNodeCreated;
            const setup = nodeData.name === "StampCustomLoad4A" ? setupStampCustomLoad : setupStampLoad;
            nodeType.prototype.onNodeCreated = function () {
                const r = prev?.apply(this, arguments);
                setup(this);
                return r;
            };
        }
        if (nodeData?.name === "StampCensor4A") {
            const prev = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = prev?.apply(this, arguments);
                setupStampCensor(this);
                return r;
            };
        }
    },

    async nodeCreated(node) {
        if (isBuiltinStampLoadNode(node)) setupStampLoad(node);
        if (isCustomStampLoadNode(node)) setupStampCustomLoad(node);
        if (node.comfyClass === "StampCensor4A" || node.type === "StampCensor4A") {
            setupStampCensor(node);
        }
    },

    loadedGraphNode(node) {
        if (isBuiltinStampLoadNode(node)) {
            setupStampLoad(node);
            syncEnhancedFromWidgets(node);
            syncLoadAngleToCensors(node);
        }
        if (isCustomStampLoadNode(node)) {
            setupStampCustomLoad(node);
            syncEnhancedFromWidgets(node);
            syncLoadAngleToCensors(node);
        }
        if (node.comfyClass === "StampCensor4A" || node.type === "StampCensor4A") {
            setupStampCensor(node);
            syncEnhancedFromWidgets(node);
            syncCensorAngleFromLoad(node);
        }
    },
});
