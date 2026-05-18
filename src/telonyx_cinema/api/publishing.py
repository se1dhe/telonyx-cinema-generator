import html
import json
import os
import re
import subprocess
import textwrap
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Publishing-модуль работает поверх уже готовых job из STORAGE_DIR/jobs/{job_id}.
# Для Telegram preview теперь используем реальные кадры из готового MP4, а не текстовые заглушки.

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@TXC_UA").strip()
BRAND_WATERMARK = os.getenv("BRAND_WATERMARK", "TELONYX CINEMA").strip()
BRAND_STYLE = os.getenv("BRAND_STYLE", "dark_neon_cinematic").strip()
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

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
    """Безопасно читит JSON-файл."""
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Записывает JSON с нормальным UTF-8."""
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


def normalize_list(value: Any) -> list[str]:
    """Приводит Gemini-ответ к списку строк.

    Gemini иногда возвращает hashtags строкой, объектом или массивом объектов.
    Frontend и Telegram-публикация должны получать стабильный формат.
    """
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(normalize_list(item))
        return [item for item in result if item]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(normalize_list(item))
        return [item for item in result if item]
    if isinstance(value, str):
        # Для хештегов строка обычно приходит как "#one #two" или "#one, #two".
        parts = re.split(r"[\s,]+", value.strip())
        return [part.strip() for part in parts if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    """Нормализует структуру Gemini/fallback перед сохранением."""
    return {
        **content,
        "telegram_text_uk": str(content.get("telegram_text_uk") or ""),
        "tiktok_title": str(content.get("tiktok_title") or ""),
        "tiktok_description": str(content.get("tiktok_description") or ""),
        "tiktok_hashtags": normalize_list(content.get("tiktok_hashtags")),
        "youtube_title": str(content.get("youtube_title") or ""),
        "youtube_description": str(content.get("youtube_description") or ""),
        "youtube_hashtags": normalize_list(content.get("youtube_hashtags")),
        "image_prompts_uk": normalize_list(content.get("image_prompts_uk"))[:5],
        "source_links": content.get("source_links") if isinstance(content.get("source_links"), list) else [],
    }


def telegram_html(text: str) -> str:
    """Конвертирует простой Gemini markdown в безопасный Telegram HTML.

    Было: **Історія створення** показывалось как текст, потому что отправка идёт
    через parse_mode=HTML. Теперь **...** превращается в <b>...</b>, а остальное
    экранируется.
    """
    if not text:
        return ""

    # Временно заменяем markdown-bold на плейсхолдеры, потом экранируем всё остальное.
    bold_parts: list[str] = []

    def remember_bold(match: re.Match[str]) -> str:
        bold_parts.append(html.escape(match.group(1).strip()))
        return f"@@BOLD_{len(bold_parts) - 1}@@"

    converted = re.sub(r"\*\*(.+?)\*\*", remember_bold, text, flags=re.DOTALL)

    # Если fallback или модель уже вернули <b>, не даём любому HTML пройти как есть.
    converted = converted.replace("<b>", "@@OPEN_B@@").replace("</b>", "@@CLOSE_B@@")
    converted = html.escape(converted)
    converted = converted.replace("@@OPEN_B@@", "<b>").replace("@@CLOSE_B@@", "</b>")

    for index, part in enumerate(bold_parts):
        converted = converted.replace(f"@@BOLD_{index}@@", f"<b>{part}</b>")

    return converted


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Загружает системный шрифт."""
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


def probe_duration(path: Path) -> float:
    """Получает длительность видео для выбора кадров."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.1, float(result.stdout.strip()))
    except ValueError:
        return 0.0


def cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """Масштабирует изображение cover-crop под нужный размер."""
    source_width, source_height = image.size
    scale = max(width / source_width, height / source_height)
    resized = image.resize((int(source_width * scale), int(source_height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def style_video_frame(raw_frame: Path, target: Path, movie_title: str, movie_year: str, index: int) -> None:
    """Превращает реальный кадр из ролика в фирменную Telegram-картинку."""
    width, height = 1080, 1350
    image = Image.open(raw_frame).convert("RGB")
    image = cover_resize(image, width, height)

    # Лёгкая премиальная обработка: контраст через overlay, виньетка, neon frame.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, width, height), fill=(2, 4, 10, 62))
    draw.rectangle((0, int(height * 0.66), width, height), fill=(0, 0, 0, 92))
    draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=34, outline=(34, 211, 238, 150), width=3)
    draw.rectangle((62, 128, 68, height - 190), fill=(34, 211, 238, 185))

    small_font = load_font(24, bold=True)
    title_font = load_font(38, bold=True)
    year_font = load_font(24, bold=True)
    watermark_font = load_font(22, bold=True)

    # Название делаем маленьким и переносим, чтобы оно больше не вылезало за кадр.
    title_lines = wrap_text(draw, movie_title.upper(), title_font, width - 170)[:2]
    y = 74
    draw.text((84, y), "TXC UKRAINE", font=small_font, fill=(210, 220, 230, 210))
    y += 46
    for line in title_lines:
        draw.text((84, y), line, font=title_font, fill=(246, 242, 234, 245))
        y += 46
    draw.text((84, y + 6), str(movie_year), font=year_font, fill=(34, 211, 238, 245))

    draw.text((84, height - 96), BRAND_WATERMARK, font=watermark_font, fill=(255, 255, 255, 145))
    draw.text((width - 128, height - 96), f"0{index}", font=watermark_font, fill=(34, 211, 238, 190))

    glow = overlay.filter(ImageFilter.GaussianBlur(8))
    image_rgba = Image.alpha_composite(image.convert("RGBA"), glow)
    image_rgba = Image.alpha_composite(image_rgba, overlay)
    image_rgba.convert("RGB").save(target, quality=94)


def create_brand_image(target: Path, movie_title: str, movie_year: str, label: str, index: int) -> None:
    """Fallback-картинка, если ffmpeg не смог вытащить кадры из видео."""
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), "#05060b")
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, width, height), fill=(8, 13, 28, 255))
    draw.ellipse((-220, -180, 620, 620), fill=(34, 211, 238, 42))
    draw.ellipse((420, 470, 1320, 1480), fill=(139, 30, 30, 92))
    draw.rounded_rectangle((44, 44, width - 44, height - 44), radius=38, outline=(34, 211, 238, 115), width=3)
    draw.rectangle((84, 164, 90, height - 220), fill=(34, 211, 238, 190))

    small_font = load_font(24, bold=True)
    title_font = load_font(42, bold=True)
    label_font = load_font(44, bold=True)
    watermark_font = load_font(22, bold=True)

    draw.text((110, 96), "TXC UKRAINE", font=small_font, fill=(210, 220, 230, 210))
    y = 150
    for line in wrap_text(draw, movie_title.upper(), title_font, 850)[:2]:
        draw.text((110, y), line, font=title_font, fill=(246, 242, 234, 245))
        y += 50
    draw.text((110, y + 8), str(movie_year), font=small_font, fill=(34, 211, 238, 245))

    y = 680
    for line in wrap_text(draw, label, label_font, 850)[:4]:
        draw.text((110, y), line, font=label_font, fill=(255, 255, 255, 235))
        y += 58

    draw.text((110, height - 110), BRAND_WATERMARK, font=watermark_font, fill=(255, 255, 255, 140))
    draw.text((width - 140, height - 110), f"0{index}", font=watermark_font, fill=(34, 211, 238, 190))

    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    image.convert("RGB").save(target, quality=94)


def create_video_frame_images(package_id: str, job_state: dict[str, Any], movie_title: str, movie_year: str, labels: list[str]) -> list[dict[str, Any]]:
    """Берёт 3–5 кадров из готового MP4 и оформляет их в фирменном стиле."""
    images_dir = package_dir(package_id) / "images"
    raw_dir = images_dir / "raw"
    images_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    video_path = Path(str(job_state.get("output_path") or job_dir(job_state["job_id"]) / "final_vertical.mp4"))
    if not video_path.exists():
        video_path = job_dir(job_state["job_id"]) / "final_vertical.mp4"

    duration = probe_duration(video_path) if video_path.exists() else 0.0
    if duration <= 0:
        duration = 10.0

    frame_count = 5
    ratios = [0.12, 0.29, 0.47, 0.65, 0.83]
    images: list[dict[str, Any]] = []

    for index, ratio in enumerate(ratios[:frame_count], start=1):
        filename = f"{index:02d}-video-frame.jpg"
        raw_frame = raw_dir / filename
        target = images_dir / filename
        timestamp = max(0.1, min(duration - 0.2, duration * ratio))
        label = labels[index - 1] if index - 1 < len(labels) else f"Кадр {index}"

        try:
            result = subprocess.run(
                [
                    FFMPEG,
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(raw_frame),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if result.returncode != 0 or not raw_frame.exists():
                raise RuntimeError(result.stdout[-800:])
            style_video_frame(raw_frame, target, movie_title, movie_year, index)
        except Exception:
            create_brand_image(target, movie_title, movie_year, label, index)

        images.append(
            {
                "id": uuid.uuid4().hex,
                "kind": "video_frame",
                "sort_order": index,
                "alt_text_uk": label,
                "local_path": str(target),
                "url": f"/api/publish-packages/{package_id}/images/{filename}",
            }
        )

    return images


def fallback_content(movie_title: str, movie_year: str) -> dict[str, Any]:
    """Fallback, если Gemini API ещё не подключён или вернул ошибку."""
    telegram_text = textwrap.dedent(
        f"""
        🎬 <b>{html.escape(movie_title)} ({html.escape(str(movie_year))})</b>

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
        "image_prompts_uk": ["Кадр із ролика", "Атмосфера сцени", "Головний момент", "Кінематографічний кадр", "TELONYX Cinema edit"],
        "source_links": [],
        "generated_by": "fallback_without_gemini_key",
    }


async def generate_with_gemini(movie_title: str, movie_year: str) -> dict[str, Any]:
    """Генерирует структурированный JSON через Gemini REST API."""
    if not GEMINI_API_KEY:
        return normalize_content(fallback_content(movie_title, movie_year))

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
6. Не використовуй markdown. Для жирних заголовків використовуй HTML <b>...</b>.
7. Обовʼязкові хештеги Telegram: #Історія #Факти #ЦікавоЗнати
8. Для TikTok і YouTube Shorts створи окремо title, description, hashtags.
9. Дай 5 коротких українських alt-підписів до кадрів із відео.

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
        return normalize_content(data)
    except Exception as exc:
        data = normalize_content(fallback_content(movie_title, movie_year))
        data["gemini_error"] = str(exc)
        return data


async def generate_package_task(package_id: str) -> None:
    """Фоновая генерация текста и Telegram-картинок из кадров видео."""
    package_path = package_dir(package_id) / "package.json"
    package = read_json(package_path)
    job_id = package["job_id"]
    movie_title = package["movie_title"]
    movie_year = package["movie_year"]

    try:
        update_package(package_id, {"status": "generating", "message": "Генерирую украинский контент через Gemini"})
        content = await generate_with_gemini(movie_title, movie_year)
        job_state = read_job_state(job_id)

        update_package(package_id, {"message": "Вытаскиваю 3–5 кадров из готового видео и оформляю в TXC-стиле"})
        images = create_video_frame_images(package_id, job_state, movie_title, movie_year, content.get("image_prompts_uk", []))

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
                    "image_source": "final_video_frames",
                },
            },
        )
    except Exception as exc:
        update_package(package_id, {"status": "failed", "message": str(exc), "error_message": str(exc)})


async def publish_to_telegram(package: dict[str, Any]) -> dict[str, Any]:
    """Публикует Telegram album и отдельный HTML-пост в канал."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("TELEGRAM_CHANNEL_ID не задан")

    text = telegram_html(package.get("telegram_text_uk") or "")
    images = package.get("images") or []
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    async with httpx.AsyncClient(timeout=120) as client:
        sent_media = None
        if images:
            media: list[dict[str, Any]] = []
            files: dict[str, tuple[str, bytes, str]] = {}
            for idx, item in enumerate(images[:5]):
                path = Path(item["local_path"])
                if not path.exists():
                    continue
                attach_name = f"photo{idx}"
                media.append({"type": "photo", "media": f"attach://{attach_name}"})
                files[attach_name] = (path.name, path.read_bytes(), "image/jpeg")

            if media:
                response = await client.post(
                    f"{api}/sendMediaGroup",
                    data={"chat_id": TELEGRAM_CHANNEL_ID, "media": json.dumps(media, ensure_ascii=False)},
                    files=files,
                )
                response.raise_for_status()
                sent_media = response.json()

        sent_text = None
        if text:
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
    """Перегенерирует весь пакет: текст + кадры."""
    path = package_dir(package_id) / "package.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Контент-пакет не найден")
    update_package(package_id, {"status": "queued", "message": "Перегенерация текста и кадров"})
    background_tasks.add_task(generate_package_task, package_id)
    return {"package_id": package_id, "status_url": f"/api/publish-packages/{package_id}"}


@router.post("/api/publish-packages/{package_id}/publish")
async def publish_package(package_id: str, targets: dict[str, Any] | None = None) -> dict[str, Any]:
    """Публикует пакет. В MVP реально включён Telegram."""
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
