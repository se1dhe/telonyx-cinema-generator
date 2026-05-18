import html
import json
import os
import re
import textwrap
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# Publishing pipeline:
# - текст генерирует Gemini;
# - изображения берём из интернета, а не из исходного/готового видео;
# - в Telegram публикуем ОДИН album-пост: картинки + caption на первой картинке.

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@TXC_UA").strip()
BRAND_WATERMARK = os.getenv("BRAND_WATERMARK", "TELONYX CINEMA").strip()
BRAND_STYLE = os.getenv("BRAND_STYLE", "dark_neon_cinematic").strip()

TELEGRAM_CAPTION_LIMIT = 1024
SAFE_CAPTION_LIMIT = 930

router = APIRouter(tags=["publishing"])


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def job_dir(job_id: str) -> Path:
    return STORAGE_DIR / "jobs" / job_id


def package_dir(package_id: str) -> Path:
    return STORAGE_DIR / "publish_packages" / package_id


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_state(job_id: str) -> dict[str, Any]:
    state_path = job_dir(job_id) / "state.json"
    if not state_path.exists():
        raise HTTPException(status_code=404, detail="Задача рендера не найдена")
    state = read_json(state_path)
    if state.get("status") != "done":
        raise HTTPException(status_code=409, detail="Видео ещё не готово для генерации контента")
    return state


def update_package(package_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    path = package_dir(package_id) / "package.json"
    data = read_json(path) if path.exists() else {"package_id": package_id}
    data.update(patch)
    data["updated_at"] = now_iso()
    write_json(path, data)
    return data


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ_-]+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or uuid.uuid4().hex[:8]


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(normalize_list(item))
        return [x for x in result if x]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(normalize_list(item))
        return [x for x in result if x]
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[\s,]+", value.strip()) if x.strip()]
    value = str(value).strip()
    return [value] if value else []


def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    return {
        **content,
        "telegram_text_uk": str(content.get("telegram_text_uk") or ""),
        "tiktok_title": str(content.get("tiktok_title") or ""),
        "tiktok_description": str(content.get("tiktok_description") or ""),
        "tiktok_hashtags": normalize_list(content.get("tiktok_hashtags")),
        "youtube_title": str(content.get("youtube_title") or ""),
        "youtube_description": str(content.get("youtube_description") or ""),
        "youtube_hashtags": normalize_list(content.get("youtube_hashtags")),
        "image_queries": normalize_list(content.get("image_queries"))[:8],
        "source_links": content.get("source_links") if isinstance(content.get("source_links"), list) else [],
    }


def telegram_html(text: str) -> str:
    if not text:
        return ""
    bold_parts: list[str] = []

    def remember_bold(match: re.Match[str]) -> str:
        bold_parts.append(html.escape(match.group(1).strip()))
        return f"@@BOLD_{len(bold_parts) - 1}@@"

    converted = re.sub(r"\*\*(.+?)\*\*", remember_bold, text, flags=re.DOTALL)
    converted = converted.replace("<b>", "@@OPEN_B@@").replace("</b>", "@@CLOSE_B@@")
    converted = html.escape(converted)
    converted = converted.replace("@@OPEN_B@@", "<b>").replace("@@CLOSE_B@@", "</b>")
    for index, part in enumerate(bold_parts):
        converted = converted.replace(f"@@BOLD_{index}@@", f"<b>{part}</b>")
    return converted


def plain_len_html(text: str) -> int:
    return len(re.sub(r"<[^>]+>", "", text))


def compact_caption(text: str) -> str:
    """Telegram album caption <=1024. Делаем безопасно около 930 символов."""
    text = telegram_html(text).strip()
    if plain_len_html(text) <= SAFE_CAPTION_LIMIT and len(text) <= TELEGRAM_CAPTION_LIMIT:
        return text

    # Режем по строкам, сохраняя хештеги, чтобы album был одним постом.
    plain_hashes = "#Історія #Факти #ЦікавоЗнати #TELONYXCinema"
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    result = ""
    for line in cleaned.splitlines():
        candidate = (result + "\n" + line).strip()
        if plain_len_html(candidate) > SAFE_CAPTION_LIMIT - len(plain_hashes) - 10:
            break
        result = candidate
    result = result.strip()
    if plain_hashes not in result:
        result = f"{result}\n\n{plain_hashes}".strip()
    return result[:TELEGRAM_CAPTION_LIMIT]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    source_width, source_height = image.size
    scale = max(width / source_width, height / source_height)
    resized = image.resize((int(source_width * scale), int(source_height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def style_internet_image(raw_image: Path, target: Path, index: int) -> None:
    """Фирменная обработка без длинного текста, чтобы ничего не вылезало за пределы."""
    width, height = 1080, 1350
    image = Image.open(raw_image).convert("RGB")
    image = cover_resize(image, width, height)
    image = ImageEnhance.Contrast(image).enhance(1.08)
    image = ImageEnhance.Color(image).enhance(0.95)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, width, height), fill=(2, 4, 10, 42))
    draw.rectangle((0, height - 190, width, height), fill=(0, 0, 0, 115))
    draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=34, outline=(34, 211, 238, 130), width=3)
    draw.rectangle((62, 96, 67, height - 128), fill=(34, 211, 238, 175))

    small_font = load_font(24, bold=True)
    number_font = load_font(24, bold=True)
    draw.text((86, 70), "TXC UKRAINE", font=small_font, fill=(230, 238, 246, 210))
    draw.text((86, height - 92), BRAND_WATERMARK, font=small_font, fill=(255, 255, 255, 155))
    draw.text((width - 126, height - 92), f"0{index}", font=number_font, fill=(34, 211, 238, 210))

    glow = overlay.filter(ImageFilter.GaussianBlur(5))
    result = Image.alpha_composite(image.convert("RGBA"), glow)
    result = Image.alpha_composite(result, overlay)
    result.convert("RGB").save(target, quality=93)


def create_fallback_image(target: Path, movie_title: str, movie_year: str, index: int) -> None:
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), "#060812")
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse((-220, -180, 620, 620), fill=(34, 211, 238, 44))
    draw.ellipse((420, 480, 1320, 1480), fill=(139, 30, 30, 100))
    draw.rounded_rectangle((44, 44, width - 44, height - 44), radius=38, outline=(34, 211, 238, 120), width=3)
    draw.rectangle((84, 140, 90, height - 160), fill=(34, 211, 238, 190))
    title_font = load_font(48, bold=True)
    small_font = load_font(24, bold=True)
    draw.text((112, 95), "TXC UKRAINE", font=small_font, fill=(230, 238, 246, 210))
    # Ограничиваем ширину грубо, без вылета за край.
    title = movie_title.upper()
    max_chars = 28
    lines = [title[i:i + max_chars] for i in range(0, min(len(title), max_chars * 3), max_chars)]
    y = 590
    for line in lines[:3]:
        draw.text((112, y), line, font=title_font, fill=(246, 242, 234, 245))
        y += 58
    draw.text((112, y + 8), str(movie_year), font=small_font, fill=(34, 211, 238, 245))
    draw.text((112, height - 110), BRAND_WATERMARK, font=small_font, fill=(255, 255, 255, 140))
    draw.text((width - 140, height - 110), f"0{index}", font=small_font, fill=(34, 211, 238, 190))
    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(target, quality=93)


async def wikimedia_image_urls(query: str, limit: int = 5) -> list[str]:
    """Ищет изображения в интернете через Wikimedia Commons API без ключей."""
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "format": "json",
        "origin": "*",
    }
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            response = await client.get(api, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []

    pages = data.get("query", {}).get("pages", {})
    urls: list[str] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("url")
        mime = info.get("mime", "")
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if url and mime.startswith("image/") and width >= 500 and height >= 500:
            urls.append(url)
    return urls


async def download_image(url: str, target: Path) -> bool:
    try:
        async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "TELONYX-Cinema/1.0"})
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return False
            target.write_bytes(response.content)
        Image.open(target).verify()
        return True
    except Exception:
        return False


async def create_internet_images(package_id: str, movie_title: str, movie_year: str, queries: list[str]) -> list[dict[str, Any]]:
    images_dir = package_dir(package_id) / "images"
    raw_dir = images_dir / "raw"
    images_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    search_queries = queries or [
        f"{movie_title} film poster",
        f"{movie_title} cast",
        f"{movie_title} movie premiere",
        f"{movie_title} actor",
        f"{movie_title} Lucasfilm",
    ]
    # Добавляем общие варианты, потому что Wikimedia лучше находит по персонажам/актёрам/премьерам.
    search_queries.extend([f"{movie_title} movie", f"{movie_title} film", f"{movie_title} cast"])

    found_urls: list[str] = []
    for query in search_queries[:8]:
        for url in await wikimedia_image_urls(query, limit=5):
            if url not in found_urls:
                found_urls.append(url)
            if len(found_urls) >= 5:
                break
        if len(found_urls) >= 5:
            break

    images: list[dict[str, Any]] = []
    for index in range(1, 6):
        filename = f"{index:02d}-internet.jpg"
        raw_path = raw_dir / filename
        target = images_dir / filename
        source_url = found_urls[index - 1] if index - 1 < len(found_urls) else None

        ok = False
        if source_url:
            ok = await download_image(source_url, raw_path)
        if ok:
            try:
                style_internet_image(raw_path, target, index)
            except Exception:
                create_fallback_image(target, movie_title, movie_year, index)
                source_url = None
        else:
            create_fallback_image(target, movie_title, movie_year, index)

        images.append(
            {
                "id": uuid.uuid4().hex,
                "kind": "internet_image" if source_url else "fallback_brand_card",
                "sort_order": index,
                "source_url": source_url,
                "alt_text_uk": f"{movie_title} — зображення {index}",
                "local_path": str(target),
                "url": f"/api/publish-packages/{package_id}/images/{filename}",
            }
        )
    return images


def fallback_content(movie_title: str, movie_year: str) -> dict[str, Any]:
    telegram_text = textwrap.dedent(
        f"""
        🎬 <b>{html.escape(movie_title)} ({html.escape(str(movie_year))})</b>

        Кіно знову нагадує: іноді один момент важить більше, ніж ціла історія.

        <b>Історія</b>: цей матеріал підготовлений як короткий кінопост для TELONYX Cinema — з атмосферою, фактами й візуальним настроєм фільму.

        <b>Факти</b>: візуальний стиль, музика, монтаж і паузи персонажів часто створюють головну емоцію сцени.

        #Історія #Факти #ЦікавоЗнати #TELONYXCinema
        """
    ).strip()
    return {
        "telegram_text_uk": telegram_text,
        "tiktok_title": f"{movie_title} ({movie_year}) | cinematic moment",
        "tiktok_description": f"Атмосферний момент із фільму {movie_title}. Український cinematic edit від TELONYX Cinema.",
        "tiktok_hashtags": ["#кіно", "#фільм", "#cinema", "#movie", "#telonyxcinema"],
        "youtube_title": f"{movie_title} ({movie_year}) — cinematic moment #Shorts",
        "youtube_description": f"Короткий кінематографічний момент із фільму {movie_title} ({movie_year}).\n\n#Shorts #Кіно #Факти #TELONYXCinema",
        "youtube_hashtags": ["#Shorts", "#Кіно", "#Факти", "#TELONYXCinema"],
        "image_queries": [f"{movie_title} film poster", f"{movie_title} cast", f"{movie_title} movie premiere"],
        "source_links": [],
        "generated_by": "fallback_without_gemini_key",
    }


async def generate_with_gemini(movie_title: str, movie_year: str) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        return normalize_content(fallback_content(movie_title, movie_year))

    prompt = f"""
Ти — редактор українського кіно-каналу TELONYX Cinema.

Фільм: {movie_title}
Рік: {movie_year}

Завдання:
1. Напиши короткий Telegram-caption українською мовою до 900 символів.
2. Це має бути ОДИН пост з фотоальбомом, тому текст має бути коротким.
3. Структура: хук, 1 короткий блок історії створення, 3 короткі факти, фінальна фраза.
4. Не використовуй markdown. Для жирних заголовків використовуй HTML <b>...</b>.
5. Обовʼязкові хештеги: #Історія #Факти #ЦікавоЗнати #TELONYXCinema
6. Для TikTok і YouTube Shorts створи окремо title, description, hashtags.
7. Дай 5 пошукових запитів англійською для пошуку зображень в інтернеті: постер, актори, премʼєра, behind the scenes, moments.

Поверни тільки валідний JSON з полями:
telegram_text_uk, tiktok_title, tiktok_description, tiktok_hashtags,
youtube_title, youtube_description, youtube_hashtags, image_queries, source_links.
""".strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.55, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            raw = response.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        data["generated_by"] = GEMINI_MODEL
        normalized = normalize_content(data)
        normalized["telegram_text_uk"] = compact_caption(normalized["telegram_text_uk"])
        return normalized
    except Exception as exc:
        data = normalize_content(fallback_content(movie_title, movie_year))
        data["telegram_text_uk"] = compact_caption(data["telegram_text_uk"])
        data["gemini_error"] = str(exc)
        return data


async def generate_package_task(package_id: str) -> None:
    package = read_json(package_dir(package_id) / "package.json")
    movie_title = package["movie_title"]
    movie_year = package["movie_year"]
    try:
        update_package(package_id, {"status": "generating", "message": "Генерирую короткий Telegram-caption через Gemini"})
        content = await generate_with_gemini(movie_title, movie_year)
        update_package(package_id, {"message": "Ищу изображения в интернете и оформляю в TXC-стиле"})
        images = await create_internet_images(package_id, movie_title, movie_year, content.get("image_queries", []))
        update_package(
            package_id,
            {
                "status": "ready",
                "message": "Контент-пакет готов к предпросмотру",
                "telegram_text_uk": content.get("telegram_text_uk", ""),
                "tiktok_title": content.get("tiktok_title", ""),
                "tiktok_description": content.get("tiktok_description", ""),
                "tiktok_hashtags": content.get("tiktok_hashtags", []),
                "youtube_title": content.get("youtube_title", ""),
                "youtube_description": content.get("youtube_description", ""),
                "youtube_hashtags": content.get("youtube_hashtags", []),
                "source_links": content.get("source_links", []),
                "image_queries": content.get("image_queries", []),
                "images": images,
                "generator_meta": {
                    "generated_by": content.get("generated_by"),
                    "gemini_error": content.get("gemini_error"),
                    "brand_style": BRAND_STYLE,
                    "image_source": "internet_wikimedia_commons",
                    "telegram_mode": "single_album_post_caption",
                },
            },
        )
    except Exception as exc:
        update_package(package_id, {"status": "failed", "message": str(exc), "error_message": str(exc)})


async def publish_to_telegram(package: dict[str, Any]) -> dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("TELEGRAM_CHANNEL_ID не задан")

    caption = compact_caption(package.get("telegram_text_uk") or "")
    images = package.get("images") or []
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    async with httpx.AsyncClient(timeout=120) as client:
        media: list[dict[str, Any]] = []
        files: dict[str, tuple[str, bytes, str]] = {}
        for idx, item in enumerate(images[:5]):
            path = Path(item.get("local_path", ""))
            if not path.exists():
                continue
            attach_name = f"photo{idx}"
            item_payload: dict[str, Any] = {"type": "photo", "media": f"attach://{attach_name}"}
            if idx == 0 and caption:
                item_payload["caption"] = caption
                item_payload["parse_mode"] = "HTML"
            media.append(item_payload)
            files[attach_name] = (path.name, path.read_bytes(), "image/jpeg")

        if not media:
            raise RuntimeError("Нет изображений для Telegram album-поста")

        response = await client.post(
            f"{api}/sendMediaGroup",
            data={"chat_id": TELEGRAM_CHANNEL_ID, "media": json.dumps(media, ensure_ascii=False)},
            files=files,
        )
        response.raise_for_status()
        sent_media = response.json()

    return {"target": "telegram", "status": "success", "mode": "single_album_post", "media": sent_media}


@router.post("/api/jobs/{job_id}/generate-package")
def generate_package(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    state = read_job_state(job_id)
    package_id = uuid.uuid4().hex[:16]
    payload = {
        "package_id": package_id,
        "job_id": job_id,
        "movie_title": state.get("movie_title", "Movie"),
        "movie_year": state.get("movie_year", ""),
        "status": "queued",
        "message": "Контент-пакет поставлен в очередь генерации",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "final_video_url": f"/api/jobs/{job_id}/download",
    }
    write_json(package_dir(package_id) / "package.json", payload)
    background_tasks.add_task(generate_package_task, package_id)
    return {"package_id": package_id, "status_url": f"/api/publish-packages/{package_id}"}


@router.get("/api/publish-packages/{package_id}")
def get_publish_package(package_id: str) -> JSONResponse:
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    return JSONResponse(read_json(path), headers={"Cache-Control": "no-store"})


@router.get("/api/publish-packages/{package_id}/images/{filename}")
def get_publish_image(package_id: str, filename: str) -> FileResponse:
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    path = package_dir(package_id) / "images" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@router.post("/api/publish-packages/{package_id}/regenerate-text")
def regenerate_text(package_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    update_package(package_id, {"status": "queued", "message": "Перегенерация текста и интернет-изображений"})
    background_tasks.add_task(generate_package_task, package_id)
    return {"package_id": package_id, "status_url": f"/api/publish-packages/{package_id}"}


@router.post("/api/publish-packages/{package_id}/publish")
async def publish_package(package_id: str, targets: dict[str, Any] | None = None) -> dict[str, Any]:
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    package = read_json(path)
    if package.get("status") != "ready":
        raise HTTPException(status_code=409, detail="Контент-пакет ещё не готов")

    requested = (targets or {}).get("targets") or ["telegram"]
    results: list[dict[str, Any]] = []
    update_package(package_id, {"status": "publishing", "message": "Публикую выбранные каналы"})

    if "telegram" in requested:
        try:
            results.append(await publish_to_telegram(package))
        except Exception as exc:
            results.append({"target": "telegram", "status": "failed", "error_message": str(exc)})
    if "tiktok" in requested:
        results.append({"target": "tiktok", "status": "pending_config", "message": "Нужны TikTok OAuth данные и approval Content Posting API"})
    if "youtube" in requested:
        results.append({"target": "youtube", "status": "pending_config", "message": "Нужны YouTube OAuth refresh token и включённый YouTube Data API"})

    has_failed = any(item.get("status") == "failed" for item in results)
    has_success = any(item.get("status") == "success" for item in results)
    final_status = "published" if has_success and not has_failed else "partially_published" if has_success else "failed"
    update_package(package_id, {"status": final_status, "message": "Публикация завершена", "publish_results": results})
    return {"package_id": package_id, "status": final_status, "results": results}
