"""生成 OCR 自检用样例图：白底黑字，含型号与故障码。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - 环境缺依赖时的明确提示
    print("缺少 Pillow，请先安装：pip install pillow", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "ocr_samples" / "sample.png"

SAMPLE_LINES: tuple[str, ...] = (
    "型号 AuroraHome AC-Pro 1200",
    "故障码 E106",
)

# 中文需要可渲染的 TrueType 字体；内置位图字体不含中文字形。
FONT_CANDIDATES: tuple[str, ...] = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

FONT_SIZE = 32
PADDING = 32
LINE_SPACING = 14


def load_font(size: int = FONT_SIZE) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    print("未找到可用中文字体，回退内置字体；中文可能渲染为方块", file=sys.stderr)
    return ImageFont.load_default(size=size)


def make_sample(output: Path = DEFAULT_OUTPUT) -> Path:
    font = load_font()
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))
    boxes = [probe.textbbox((0, 0), line, font=font) for line in SAMPLE_LINES]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]

    width = max(widths) + PADDING * 2
    height = sum(heights) + LINE_SPACING * (len(SAMPLE_LINES) - 1) + PADDING * 2

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = PADDING
    for line, box, line_height in zip(SAMPLE_LINES, boxes, heights):
        # 减去 bbox 偏移，避免字形上沿超出绘制原点
        draw.text((PADDING - box[0], top - box[1]), line, fill="black", font=font)
        top += line_height + LINE_SPACING

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 OCR 自检样例图")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出图片路径")
    args = parser.parse_args(argv)
    print(f"已生成样例图：{make_sample(Path(args.output))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())