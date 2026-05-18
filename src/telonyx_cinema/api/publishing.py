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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Отдельный publishing-модуль не трогает рендер-видео.
# Он работает поверх уже готовых job из STORAGE_DIR/jobs/{job_id}.

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@TXC_UA").strip()
BRAND_WATERMARK = os.getenv("BRAND_WATERMARK", "TELONYX CINEMA").strip()
BRAND_STYLE = os.getenv("BRAND_STYLE", "dark_neon_cinematic").strip()

router = APIRouter(tags=["publishing"])


def now_iso() -> str:
    """Возвращает UTC-время в ISO-формате для state-файлов."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def job_dir(job_id: str) -> Path:
    """Папка существующей задачи рендера."""
    return STORAGE_DIR / "jobs" / job_id


def package_dir(package_id: str) -> Path:
    """Папка контент-пакета публикации."""
    return STORAGE_DIR / "publish_packages" / package_id


def read_json(path: Path) -> dict[str, Any]:
    """Безопасно читает JSON-файл."""
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Записывает JSON с нормальным UTF-8, чтобы украинский текст не ломался."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_state(job_id: str) -> dict[str, Any]:
    """Читает state существующего finalizer job."""
    state_path = job_dir(job_id) / "state.json"
    if not state_path.exists():
        raise HTTPException(status_code=404, detail="Задача рендера не найдена")
    state = read_json(state_path)
    if state.get("status") != "done":
        raise HTTPException(status_code=409, detail="Видео ещё не готово для генерации контента")
    return state


def update_package(package_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Обновляет state content package."""
    path = package_dir(package_id) / "package.json"
    data = read_json(path) if path.exists() else {"package_id": package_id}
    data.update(patch)
    data["updated_at"] = now_iso()
    write_json(path, data)
    return data


def slugify(value: str) -> str:
    """Делает безопасный slug для имён файлов."""
    value = re.sub(r"[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ_-]+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or uuid.uuid4().hex[:8]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Загружает системный шрифт. В Docker уже ставятся fonts-dejavu."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Разбивает текст на строки по реальной ширине."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def create_brand_image(target: Path, movie_title: str, movie_year: str, label: str, index: int) -> None:
    """Создаёт фирменную dark/neon карточку, пока нет внешних licensed stills.

    Это MVP-вариант: вместо скачивания спорных кадров из интернета мы генерируем
    безопасную branded-картинку. Позже сюда можно подключить источник изображений
    и прогонять реальные кадры через тот же style pass.
    """
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), "#05060b")
    pixels = image.load()

    # Кинематографичный градиент без внешних ассетов.
    for y in range(height):
        for x in range(width):
            nx = x / width
            ny = y / height
            cyan = int(max(0, 1 - ((nx - 0.18) ** 2 + (ny - 0.18) ** 2) * 4) * 68)
            violet = int(max(0, 1 - ((nx - 0.85) ** 2 + (ny - 0.82) ** 2) * 3) * 72)
            base = 7 + int(ny * 12)
            pixels[x, y] = (base + violet, base + cyan // 3, base + cyan)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Неоновая рамка и акцентная линия.
    draw.rounded_rectangle((46, 46, width - 46, height - 46), radius=38, outline=(34, 211, 238, 105), width=3)
    draw.rectangle((86, 220, 92, 1030), fill=(34, 211, 238, 190))
    draw.line((92, 220, 985, 220), fill=(139, 92, 246, 110), width=2)

    title_font = load_font(82, bold=True)
    year_font = load_font(34, bold=True)
    label_font = load_font(44, bold=True)
    small_font = load_font(26, bold=True)
    watermark_font = load_font(24, bold=True)

    draw.text((112, 124), "TXC UKRAINE", font=small_font, fill=(180, 190, 205, 230))
    draw.text((112, 188), movie_title.upper(), font=title_font, fill=(246, 242, 234, 255))
    draw.text((112, 300), str(movie_year), font=year_font, fill=(34, 211, 238, 255))

    label_lines = wrap_text(draw, label, label_font, 850)
    y = 720
    for line in label_lines[:5]:
        draw.text((112, y), line, font=label_font, fill=(255, 255, 255, 245))
        y += 58

    draw.text((112, height - 128), BRAND_WATERMARK, font=watermark_font, fill=(255, 255, 255, 130))
    draw.text((width - 250, height - 128), f"0{index}", font=watermark_font, fill=(34, 211, 238, 160))

    # Лёгкий blur/glow.
    glow = overlay.filter(ImageFilter.GaussianBlur(10))
    image = Image.alpha_composite(image.convert("RGBA"), glow)
    image = Image.alpha_composite(image, overlay)
    image.convert("RGB").save(target, quality=94)


def fallback_content(movie_title: str, movie_year: str) -> dict[str, Any]:
    """Fallback, если Gemini API ещё не подключён.

    Это не притворяется интернет-анализом: текст честно универсальный и пригоден
    как черновик для UI/Telegram-пайплайна.
    """
    telegram_text = textwrap.dedent(
        f"""
        🎬 <b>{movie_title} ({movie_year})</b>

        Іноді фільм стає більшим, ніж просто історія на екрані. Він перетворюється на настрій, спогад і окремий візуальний код.

        <b>Історія створення</b>
        Для цього релізу TELONYX Cinema підготує окремий матеріал з історією виробництва, атмосферою зйомок і деталями, які зазвичай залишаються поза кадром.

        <b>Цікаві факти</b>
        1. Візуальний стиль фільму — один із головних елементів його впізнаваності.
        2. Музика, монтаж і колір створюють окремий емоційний ритм.
        3. Персонажі часто розкриваються не тільки словами, а й паузами, поглядами та деталями кадру.
        4. Саме короткі сцени часто найкраще передають головний нерв фільму.
        5. У форматі Shorts такі моменти працюють як кінематографічний спалах памʼяті.

        Кіно живе не тільки в повному метрі. Іноді достатньо одного моменту.

        #Історія #Факти #ЦікавоЗнати #Кіно #TELONYXCinema
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
        "image_prompts_uk": [
            "Історія створення",
            "Атмосфера фільму",
            "Цікаві факти",
            "Кінематографічний момент",
            "TELONYX Cinema edit",
        ],
        "source_links": [],
        "generated_by": "fallback_without_gemini_key",
    }


async def generate_with_gemini(movie_title: str, movie_year: str) -> dict[str, Any]:
    """Генерирует структурированный JSON через Gemini REST API.

    Если ключ не задан или модель вернула мусор — отдаём fallback, чтобы UI и
    Telegram-пайплайн всё равно можно было тестировать.
    """
    if not GEMINI_API_KEY:
        return fallback_content(movie_title, movie_year)

    prompt = f"""
Ти — редактор українського кіно-каналу TELONYX Cinema.

Фільм: {movie_title}
Рік: {movie_year}

Завдання:
1. Знайди історію створення фільму та цікаві факти.
2. Пиши тільки українською мовою.
3. Не вигадуй факти. Якщо факт не підтверджено джерелами — не використовуй.
4. Тон: кінематографічний, темний, атмосферний, але зрозумілий.
5. Telegram-пост: хук, блок «Історія створення», 5 фактів, фінальна фраза, хештеги.
6. Обовʼязкові хештеги Telegram: #Історія #Факти #ЦікавоЗнати
7. Для TikTok і YouTube Shorts створи окремо title, description, hashtags.
8. Дай 5 коротких підписів українською для branded-зображень.

Поверни тільки валідний JSON з полями:
telegram_text_uk, tiktok_title, tiktok_description, tiktok_hashtags,
youtube_title, youtube_description, youtube_hashtags, image_prompts_uk, source_links.
""".strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.65, "responseMimeType": "application/json"},
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            raw = response.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        data["generated_by"] = GEMINI_MODEL
        return data
    except Exception as exc:
        data = fallback_content(movie_title, movie_year)
        data["gemini_error"] = str(exc)
        return data


async def generate_package_task(package_id: str) -> None:
    """Фоновая генерация текста и фирменных картинок."""
    package_path = package_dir(package_id) / "package.json"
    package = read_json(package_path)
    job_id = package["job_id"]
    movie_title = package["movie_title"]
    movie_year = package["movie_year"]

    try:
        update_package(package_id, {"status": "generating", "message": "Генерирую украинский контент через Gemini"})
        content = await generate_with_gemini(movie_title, movie_year)

        images_dir = package_dir(package_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        prompts = content.get("image_prompts_uk") or []
        if not isinstance(prompts, list) or not prompts:
            prompts = ["Історія", "Факти", "Кіно", "Атмосфера", "TELONYX Cinema"]

        images: list[dict[str, Any]] = []
        for index, label in enumerate(prompts[:5], start=1):
            filename = f"{index:02d}-{slugify(str(label))}.jpg"
            target = images_dir / filename
            create_brand_image(target, movie_title, movie_year, str(label), index)
            images.append(
                {
                    "id": uuid.uuid4().hex,
                    "kind": "brand_card",
                    "sort_order": index,
                    "alt_text_uk": str(label),
                    "local_path": str(target),
                    "url": f"/api/publish-packages/{package_id}/images/{filename}",
                }
            )

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
                "images": images,
                "generator_meta": {
                    "generated_by": content.get("generated_by"),
                    "gemini_error": content.get("gemini_error"),
                    "brand_style": BRAND_STYLE,
                },
            },
        )
    except Exception as exc:
        update_package(package_id, {"status": "failed", "message": str(exc), "error_message": str(exc)})


async def publish_to_telegram(package: dict[str, Any]) -> dict[str, Any]:
    """Публикует Telegram-пост в канал через Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("TELEGRAM_CHANNEL_ID не задан")

    text = package.get("telegram_text_uk") or ""
    images = package.get("images") or []
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    async with httpx.AsyncClient(timeout=120) as client:
        sent_media = None
        if images:
            media: list[dict[str, Any]] = []
            files: dict[str, tuple[str, bytes, str]] = {}
            for idx, item in enumerate(images[:5]):
                path = Path(item["local_path"])
                attach_name = f"photo{idx}"
                caption = text if idx == 0 and len(text) <= 1024 else None
                media_item: dict[str, Any] = {"type": "photo", "media": f"attach://{attach_name}"}
                if caption:
                    media_item["caption"] = caption
                    media_item["parse_mode"] = "HTML"
                media.append(media_item)
                files[attach_name] = (path.name, path.read_bytes(), "image/jpeg")

            response = await client.post(
                f"{api}/sendMediaGroup",
                data={"chat_id": TELEGRAM_CHANNEL_ID, "media": json.dumps(media, ensure_ascii=False)},
                files=files,
            )
            response.raise_for_status()
            sent_media = response.json()

        sent_text = None
        if text and (not images or len(text) > 1024):
            response = await client.post(
                f"{api}/sendMessage",
                json={"chat_id": TELEGRAM_CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            response.raise_for_status()
            sent_text = response.json()

    return {"target": "telegram", "status": "success", "media": sent_media, "message": sent_text}


@router.post("/api/jobs/{job_id}/generate-package")
def generate_package(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Создаёт content package после готового рендера."""
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
    """Возвращает JSON для UI-предпросмотра."""
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    return JSONResponse(read_json(path), headers={"Cache-Control": "no-store"})


@router.get("/api/publish-packages/{package_id}/images/{filename}")
def get_publish_image(package_id: str, filename: str) -> FileResponse:
    """Отдаёт фирменные картинки для предпросмотра и Telegram."""
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    path = package_dir(package_id) / "images" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@router.post("/api/publish-packages/{package_id}/regenerate-text")
def regenerate_text(package_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Перегенерирует весь пакет. Для MVP это проще и безопаснее."""
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    update_package(package_id, {"status": "queued", "message": "Перегенерация текста и изображений"})
    background_tasks.add_task(generate_package_task, package_id)
    return {"package_id": package_id, "status_url": f"/api/publish-packages/{package_id}"}


@router.post("/api/publish-packages/{package_id}/publish")
async def publish_package(package_id: str, targets: dict[str, Any] | None = None) -> dict[str, Any]:
    """Публикует пакет. В MVP реально включён Telegram.

    TikTok и YouTube возвращают pending_config, пока пользователь не получит OAuth-данные.
    """
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
