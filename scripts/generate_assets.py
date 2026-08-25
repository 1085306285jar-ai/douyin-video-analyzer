from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def has_cjk_font() -> bool:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        windows / "msyh.ttc",
        windows / "msyhbd.ttc",
        windows / "simhei.ttf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    return any(path.is_file() for path in candidates)


def find_font(*, bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        windows / ("msyhbd.ttc" if bold else "msyh.ttc"),
        windows / ("simhei.ttf" if bold else "simsun.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def vertical_gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    top = (17, 42, 92)
    bottom = (37, 99, 235)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(a + (b - a) * ratio) for a, b in zip(top, bottom))
        for x in range(width):
            pixels[x, y] = color
    return image


def build_splash() -> None:
    width, height = 760, 430
    image = vertical_gradient(width, height)
    draw = ImageDraw.Draw(image, "RGBA")

    draw.ellipse((530, -120, 860, 210), fill=(255, 255, 255, 18))
    draw.ellipse((-160, 260, 270, 690), fill=(91, 160, 255, 34))
    draw.rounded_rectangle((54, 56, 154, 156), radius=24, fill=(255, 255, 255, 235))
    draw.polygon(((94, 82), (94, 130), (132, 106)), fill=(37, 99, 235, 255))

    title_font = find_font(bold=True, size=40)
    subtitle_font = find_font(bold=False, size=19)
    badge_font = find_font(bold=True, size=15)
    small_font = find_font(bold=False, size=14)

    if has_cjk_font():
        title = "抖音视频 AI 智能解析"
        subtitle = "公开媒体读取 · 本地语音转写 · 离线内容分析"
        badge = "本地处理  不上传"
        status = "正在启动，请稍候……"
    else:
        title = "Douyin Video AI Analyzer"
        subtitle = "Public media · Local transcription · Offline analysis"
        badge = "LOCAL  PRIVATE"
        status = "Starting local AI components..."
    draw.text((54, 190), title, font=title_font, fill=(255, 255, 255, 255))
    draw.text((56, 253), subtitle, font=subtitle_font, fill=(222, 232, 255, 255))
    draw.rounded_rectangle((55, 306, 231, 346), radius=20, fill=(255, 255, 255, 34), outline=(255, 255, 255, 80))
    draw.text((78, 315), badge, font=badge_font, fill=(255, 255, 255, 255))
    draw.text((56, 382), status, font=small_font, fill=(207, 222, 255, 255))
    image.save(ASSETS / "splash.png", optimize=True)


def build_icon() -> None:
    size = 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((24, 24, 488, 488), radius=112, fill=(37, 99, 235, 255))
    draw.rounded_rectangle((96, 96, 416, 416), radius=86, fill=(255, 255, 255, 245))
    draw.polygon(((205, 162), (205, 350), (352, 256)), fill=(37, 99, 235, 255))
    image.save(
        ASSETS / "app.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    build_splash()
    build_icon()
    print(f"Generated assets in {ASSETS}")


if __name__ == "__main__":
    main()
