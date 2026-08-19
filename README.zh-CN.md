# ComfyUI-4A-StampCensor

[English](README.md)

用贴纸 / 图案铺在遮罩上打码，替代马赛克。内置纯白（或白底黑稿）预设可用色盘上色；自定义 PNG 走自己的透明通道。检测和膨胀请用 SAM / Impact / Grow Mask，本插件不做。

**当前版本：0.1.0** — 贴纸加载、自定义贴纸加载、贴纸打码，节点内可预览。

![总览](docs/images/hero.png)

## 亮点

### 贴纸加载 + 色盘上色

选内置形状、用色盘染色、设初始角度。节点预览会跟着角度转；输出的 `STAMP` 本身不转，留给贴纸打码做自动旋转 / 抖动。

![贴纸加载](docs/images/stamp_load.png)

### 自定义线稿（不上色）

拖入或点选自己的 PNG。两种画法会自动收成贴纸：

- **纯白形状 + 透明底** — 原样使用
- **白底纯黑线稿** — 只读黑色、丢掉白色

已有颜色的透明贴纸会直接读通道，不上色。

![自定义贴纸加载](docs/images/stamp_custom.png)

### 按覆盖率 / 间距铺满遮罩

接 `image` + `mask` + `stamp`。每个连通区域单独算长边朝向（可关）、随机尺寸和旋转矩形碰撞，直到达到**覆盖率**。贴纸可以溢出遮罩。接好贴纸后，节点底部会更新演示预览。

![贴纸打码](docs/images/stamp_censor.png)

### 用图案代替马赛克

爱心、涂鸦横条、星星、叉，或你自己的贴纸——同一条遮罩链路，不再像素化。

![效果对比](docs/images/result.png)

## 安装

### ComfyUI-Manager（推荐）

搜索 **4A Stamp Censor** / `ComfyUI-4A-StampCensor` 安装。

### 手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/tsukino4a/ComfyUI-4A-StampCensor.git ComfyUI-4A-StampCensor
```

没有额外 pip 依赖。安装后重启 ComfyUI。改 Python / 语言文件后再重启一次；只改 JS 时浏览器硬刷新（Ctrl+F5）即可。

## 快速开始

1. 从 `4A/贴纸打码` 加上 **贴纸加载** 和 **贴纸打码**。
2. 把 `stamp` 接到 `stamp`。`image` 和遮罩（白色区域会被打码）用你现有的 YOLO / SAM / Impact / Grow Mask。
3. 排队跑一次。调覆盖率、尺寸比例、间距、自动旋转；接的是贴纸加载时，底部演示预览会跟着变。
4. 有自己的 PNG 时，改用 **自定义贴纸加载**。

本插件**不做** NSFW 检测，也不膨胀遮罩，请自己接线。

## 节点一览

| 节点 | 作用 |
|------|------|
| 贴纸加载 | 内置预设 + 颜色 + 角度 → `STAMP` |
| 自定义贴纸加载 | 拖入 / 点选 PNG → `STAMP`（不上色） |
| 贴纸打码 | 在 `mask` 上铺已连接的贴纸；种子口可选 |

## 贴纸资源

| 路径 | 用途 |
|------|------|
| [`assets/`](assets/) | 内置预设。启动时扫描全部 `.png`，**不包括** `demo_scene.png` |
| [`assets/demo_scene.png`](assets/demo_scene.png) | 内部演示底图，不会出现在贴纸列表里 |

可被扫进预设的画法：

- 纯白 RGB + 真透明底
- 白底纯黑线稿（加载时自动转换）

增删文件后按 **R**（刷新节点定义）或刷新页面，就会出现在贴纸加载下拉里。文件名（不含扩展名）就是下拉里的 id。

随包装的形状（顺序固定，多出来的文件排在后面）：`heart_standard`、`heart_wobbly_a`、`heart_soft`、`bar_h_scribble`、`bar_h_thick`、`star_wobbly`、`circle_scribble`、`cross_x`。

## 依赖

- Pillow、NumPy 由 ComfyUI 提供，本插件不再额外声明

## 许可证

本项目以 [MIT License](LICENSE) 发布。
