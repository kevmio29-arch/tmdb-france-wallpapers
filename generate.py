import os
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TMDB_TOKEN = os.environ["TMDB_BEARER_TOKEN"]
LANGUAGE = os.getenv("TMDB_LANGUAGE", "fr-FR")
BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/original"
OUT = Path("wallpapers")
OUT.mkdir(exist_ok=True)

HEADERS = {"Authorization": f"Bearer {TMDB_TOKEN}", "accept": "application/json"}
W, H = 1920, 1080


def api(path, **params):
    r = requests.get(BASE + path, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def download(path):
    r = requests.get(IMG + path, timeout=30)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def fit_cover(im):
    ratio = max(W / im.width, H / im.height)
    size = (int(im.width * ratio), int(im.height * ratio))
    im = im.resize(size, Image.Resampling.LANCZOS)
    left = (im.width - W) // 2
    top = (im.height - H) // 2
    return im.crop((left, top, left + W, top + H))


def wrap(draw, text, fnt, max_width, max_lines=3):
    words = (text or "").split()
    lines, line = [], ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
            if len(lines) == max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    return "\n".join(lines)


def make_wallpaper(item, media_type):
    title = item.get("title") or item.get("name") or "Sans titre"
    overview = item.get("overview") or ""
    date = item.get("release_date") or item.get("first_air_date") or ""
    year = date[:4] if date else ""
    rating = item.get("vote_average")
    backdrop = item.get("backdrop_path")
    if not backdrop:
        return

    bg = fit_cover(download(backdrop)).filter(ImageFilter.GaussianBlur(0.4))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 80))
    bg = Image.alpha_composite(bg.convert("RGBA"), dark)

    # Gradient sombre à gauche pour conserver une excellente lisibilité.
    grad = Image.new("L", (W, 1))
    px = grad.load()
    for x in range(W):
        px[x, 0] = int(190 * max(0, 1 - x / (W * 0.72)))
    grad = grad.resize((W, H))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.putalpha(grad)
    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)
    title_font = font(82, bold=True)
    meta_font = font(28)
    body_font = font(31)

    x = 100
    draw.text((x + 2, 430 + 2), title, font=title_font, fill=(0, 0, 0, 210))
    draw.text((x, 430), title, font=title_font, fill="white")

    meta = f"{year}  •  TMDB {rating:.1f}" if isinstance(rating, (int, float)) else year
    draw.text((x, 535), meta, font=meta_font, fill=(220, 220, 220, 255))

    if overview:
        text = wrap(draw, overview, body_font, 690, 4)
        draw.multiline_text((x, 600), text, font=body_font, fill=(245, 245, 245, 255), spacing=12)

    filename = f"{media_type}_{item['id']}_{year}_{title}".replace("/", "_").replace("\\", "_")
    filename = "".join(c if c.isalnum() or c in " ._-" else "_" for c in filename)[:100]
    bg.convert("RGB").save(OUT / f"{filename}.jpg", quality=94, optimize=True)


def main():
    # Les tendances TMDB sont déjà localisées en français.
    movies = api("/trending/movie/week", language=LANGUAGE).get("results", [])
    shows = api("/trending/tv/week", language=LANGUAGE).get("results", [])

    # 10 wallpapers par exécution: 5 films + 5 séries.
    for item in movies[:5]:
        make_wallpaper(item, "film")
    for item in shows[:5]:
        make_wallpaper(item, "serie")


if __name__ == "__main__":
    main()
