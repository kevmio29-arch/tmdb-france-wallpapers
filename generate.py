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
    return Image.open(BytesIO(r.content)).convert("RGBA")


def fit_cover(im):
    ratio = max(W / im.width, H / im.height)
    size = (int(im.width * ratio), int(im.height * ratio))
    im = im.resize(size, Image.Resampling.LANCZOS)
    left = (im.width - W) // 2
    top = (im.height - H) // 2
    return im.crop((left, top, left + W, top + H))


def wrap(draw, text, fnt, max_width, max_lines=4):
    words = (text or "").split()
    lines, line = [], ""
    truncated = False
    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
            if len(lines) == max_lines:
                truncated = True
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    if truncated and lines:
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=fnt)[2] > max_width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return "\n".join(lines)


def get_logo(media_type, media_id):
    """Prefer a French TMDB logo, then an unlabelled or English logo."""
    data = api(
        f"/{media_type}/{media_id}/images",
        include_image_language=f"{LANGUAGE.split('-')[0]},null,en",
    )
    logos = data.get("logos", [])
    if not logos:
        return None

    def score(logo):
        lang = logo.get("iso_639_1")
        vote = float(logo.get("vote_average") or 0)
        width = int(logo.get("width") or 0)
        if lang == LANGUAGE.split("-")[0]:
            return (3, vote, width)
        if lang is None:
            return (2, vote, width)
        if lang == "en":
            return (1, vote, width)
        return (0, vote, width)

    logos.sort(key=score, reverse=True)
    return logos[0].get("file_path")


def paste_logo(base, logo_path, max_width=850, max_height=260, x=95, y=90):
    if not logo_path:
        return False
    try:
        logo = download(logo_path)
        logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        alpha = logo.getchannel("A")
        shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(7)))
        shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shadow_layer.alpha_composite(shadow, (x + 5, y + 7))
        base.alpha_composite(shadow_layer)
        base.alpha_composite(logo, (x, y))
        return True
    except Exception:
        return False


def make_wallpaper(item, media_type):
    title = item.get("title") or item.get("name") or "Sans titre"
    overview = item.get("overview") or ""
    date = item.get("release_date") or item.get("first_air_date") or ""
    year = date[:4] if date else ""
    backdrop = item.get("backdrop_path")
    if not backdrop:
        return

    details = api(f"/{media_type}/{item['id']}", language=LANGUAGE)
    rating = details.get("vote_average", item.get("vote_average"))
    backdrop = details.get("backdrop_path") or backdrop
    overview = details.get("overview") or overview

    bg = fit_cover(download(backdrop)).filter(ImageFilter.GaussianBlur(0.25))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 58))
    bg = Image.alpha_composite(bg, dark)

    # Dégradé sombre à gauche, inspiré du rendu cinéma de Projectivy.
    grad = Image.new("L", (W, 1))
    px = grad.load()
    for x in range(W):
        t = x / W
        value = int(215 * (1 - t / 0.68) ** 1.55) if t < 0.68 else 0
        px[x, 0] = max(0, min(215, value))
    grad = grad.resize((W, H))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.putalpha(grad)
    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)
    title_font = font(82, bold=True)
    meta_font = font(34)
    body_font = font(32)

    x = 95
    logo_path = get_logo(media_type, item["id"])
    logo_ok = paste_logo(bg, logo_path, x=x, y=90)

    title_y = 365 if logo_ok else 285
    if not logo_ok:
        draw.text((x + 3, title_y + 3), title, font=title_font, fill=(0, 0, 0, 220))
        draw.text((x, title_y), title, font=title_font, fill="white")
        title_y += 115

    genres = details.get("genres") or []
    genre = genres[0].get("name") if genres else ""
    if media_type == "movie":
        runtime = details.get("runtime")
        extra = f"{runtime} min" if runtime else ""
    else:
        seasons = details.get("number_of_seasons")
        extra = f"{seasons} saison" + ("s" if seasons and seasons > 1 else "") if seasons else ""

    parts = [p for p in [genre, year, extra, f"TMDB {rating:.1f}" if isinstance(rating, (int, float)) else ""] if p]
    meta = "  •  ".join(parts)
    draw.text((x, title_y + 5), meta, font=meta_font, fill=(215, 215, 215, 255))

    if overview:
        text = wrap(draw, overview, body_font, 820, 5)
        draw.multiline_text((x, title_y + 68), text, font=body_font, fill=(245, 245, 245, 255), spacing=12)

    prefix = "film" if media_type == "movie" else "serie"
    filename = f"{prefix}_{item['id']}_{year}_{title}".replace("/", "_").replace("\\", "_")
    filename = "".join(c if c.isalnum() or c in " ._-" else "_" for c in filename)[:100]
    bg.convert("RGB").save(OUT / f"{filename}.jpg", quality=94, optimize=True)


def collect_items(media_type, pages=5):
    """Collect a large French catalogue from several popular TMDB pages."""
    results = []
    seen = set()
    endpoint = "/discover/movie" if media_type == "movie" else "/discover/tv"
    date_sort = "primary_release_date.desc" if media_type == "movie" else "first_air_date.desc"

    # Mix popularity and recent releases to avoid getting 200 nearly identical titles.
    for sort_by in ["popularity.desc", date_sort]:
        for page in range(1, pages + 1):
            params = {
                "language": LANGUAGE,
                "sort_by": sort_by,
                "page": page,
                "include_adult": "false",
                "include_video": "false",
            }
            if media_type == "movie":
                params["vote_count.gte"] = 20
            else:
                params["vote_count.gte"] = 10
            data = api(endpoint, **params)
            for item in data.get("results", []):
                item_id = item.get("id")
                if item_id and item_id not in seen and item.get("backdrop_path"):
                    seen.add(item_id)
                    results.append(item)
    return results


def main():
    for old in OUT.glob("*.jpg"):
        old.unlink()

    # 200 fonds : 100 films + 100 séries.
    movies = collect_items("movie", pages=5)[:100]
    shows = collect_items("tv", pages=5)[:100]

    print(f"Génération : {len(movies)} films + {len(shows)} séries")

    for item in movies:
        make_wallpaper(item, "movie")
    for item in shows:
        make_wallpaper(item, "tv")


if __name__ == "__main__":
    main()
