"""Regenerate every shipped brand asset from logo/ — one source of truth.

Outputs (committed, so CI and PyInstaller never need Pillow):
  assets/icon.png                     256x256 transparent mark — in-app header
                                      # and taskbar/title-bar icon
  assets/icon.ico                     multi-size exe + installer + shortcut icon
  installer/images/wizard-image.png   480x918 banner (Inno aspect 164:314)
  installer/images/wizard-small.png   294x294 square mark (Inno corner image)

Run:  python tools/make_brand_assets.py
Dev machines only. Latin text only on purpose: Pillow here has no Raqm, so
Arabic-script shaping would come out wrong.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "logo", "no-background.png")
ASSETS = os.path.join(ROOT, "assets")
INST_IMAGES = os.path.join(ROOT, "installer", "images")
FONT_BOLD = os.path.join(ASSETS, "fonts", "Vazirmatn-Bold.ttf")
FONT_REG = os.path.join(ASSETS, "fonts", "Vazirmatn-Regular.ttf")

BG = (5, 5, 5, 255)          # matches logo/with-background.png
GOLD_TEXT = (240, 180, 60, 255)
DIM_TEXT = (150, 150, 150, 255)


def mark():
    """Trimmed logo mark (alpha-cropped) as RGBA."""
    if not os.path.isfile(SRC):
        sys.exit("logo source missing: %s\n"
                 "Run this from a checkout that has logo/no-background.png."
                 % SRC)
    im = Image.open(SRC).convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    return im.crop(bbox) if bbox else im


def fit_square(im, size, pad=0.06):
    """`im` centered on a transparent square canvas with padding."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, int(size * (1 - 2 * pad)))
    tile = im.copy()
    tile.thumbnail((inner, inner), Image.LANCZOS)
    canvas.alpha_composite(tile, ((size - tile.width) // 2,
                                  (size - tile.height) // 2))
    return canvas


def centered(draw, y, text, font, color, width):
    box = draw.textbbox((0, 0), text, font=font)
    x = (width - (box[2] - box[0])) // 2 - box[0]
    draw.text((x, y), text, font=font, fill=color)


def wizard_banner(m, width=480, height=918):
    """Vertical Inno wizard banner: mark + wordmark on the brand black."""
    img = Image.new("RGBA", (width, height), BG)
    d = ImageDraw.Draw(img)

    tile = m.copy()
    tile.thumbnail((int(width * 0.72), int(width * 0.72)), Image.LANCZOS)
    img.alpha_composite(tile, ((width - tile.width) // 2, 200))

    try:
        bold = ImageFont.truetype(FONT_BOLD, 64)
        reg = ImageFont.truetype(FONT_REG, 24)
    except OSError:
        bold = reg = ImageFont.load_default()

    y = 200 + tile.height + 56
    centered(d, y, "SubSaz", bold, GOLD_TEXT, width)
    y += 84
    d.line([(width * 0.30, y), (width * 0.70, y)], fill=(90, 70, 30, 255),
           width=2)
    y += 26
    centered(d, y, "precise word-by-word", reg, DIM_TEXT, width)
    y += 34
    centered(d, y, "subtitles, fully offline", reg, DIM_TEXT, width)
    return img


def main():
    m = mark()
    os.makedirs(INST_IMAGES, exist_ok=True)

    icon_png = os.path.join(ASSETS, "icon.png")
    icon_sq = fit_square(m, 256)  # one render, reused for .png and .ico
    icon_sq.save(icon_png, "PNG")
    icon_sq.save(os.path.join(ASSETS, "icon.ico"), format="ICO",
                 sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                        (128, 128), (256, 256)])
    wizard_banner(m).save(os.path.join(INST_IMAGES, "wizard-image.png"), "PNG")
    fit_square(m, 294, pad=0.02).save(
        os.path.join(INST_IMAGES, "wizard-small.png"), "PNG")

    for p in (icon_png, os.path.join(ASSETS, "icon.ico"),
              os.path.join(INST_IMAGES, "wizard-image.png"),
              os.path.join(INST_IMAGES, "wizard-small.png")):
        print("%9d  %s" % (os.path.getsize(p), os.path.relpath(p, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
