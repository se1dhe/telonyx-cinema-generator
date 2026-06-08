import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from telonyx_cinema.api.publishing import router as publishing_router

APP_VERSION = "dialogue-shorts-v22-clean-cinematic-subs-2026-05-19"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1200"))
ENABLE_WHISPER = os.getenv("ENABLE_WHISPER", "true").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")
LOGO_PATH = os.getenv("LOGO_PATH", str(Path(__file__).parent / "static" / "logo.png"))
YT_DLP_BIN = os.getenv("YT_DLP_BIN", "yt-dlp")
YT_COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "") or os.getenv("YT_DLP_COOKIES_FILE", "")
YT_COOKIES_BASE64 = os.getenv("YT_DLP_COOKIES_BASE64", "")

LANGUAGE_LABELS = {"auto": "Auto", "ru": "Русский", "en": "English", "uk": "Українська"}
LANGUAGE_PROMPTS = {
    "ru": "Расшифровывай только человеческую русскую речь и диалоги из фильма. Не пиши описания музыки, шума, смеха, пауз, титров и звуковых эффектов. Не добавляй фразы в скобках. Если нет речи — верни пустой текст.",
    "uk": "Розшифровуй тільки людську українську мову та діалоги з фільму. Не пиши описи музики, шуму, сміху, пауз, титрів і звукових ефектів. Не додавай фрази в дужках. Якщо мовлення немає — поверни порожній текст.",
    "en": "Transcribe only human speech and movie dialogue. Do not write descriptions of music, noise, laughter, pauses, captions, credits or sound effects. Do not add bracketed stage directions. If there is no speech, return empty text.",
}
NON_DIALOGUE_RE = re.compile(
    r"(^|\b)(музык|музыка|песня|поет|поют|звучит|играет|торжественн|драматическ|напряженн|шум|звук|грохот|взрыв|крик|смех|смеются|аплодисмент|тишина|пауза|субтитр|титр|music|song|singing|plays|playing|dramatic|solemn|sound|noise|laughter|laughing|applause|silence|pause|caption|subtitle|credits|музика|пісня|співає|співають|лунає|грає|урочист|драматич|напружен|шум|звук|сміх|аплодисмент|тиша|пауза|титри)(\b|$)",
    re.IGNORECASE,
)
BRACKET_RE = re.compile(r"[\[\(\{][^\]\)\}]{1,90}[\]\)\}]")
ONLY_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)

app = FastAPI(title="TXC Ukraine Cinema Finalizer", version=APP_VERSION)
app.include_router(publishing_router)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

JOBS: dict[str, dict[str, Any]] = {}
TIKTOK_JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def job_dir(job_id: str) -> Path:
    return STORAGE_DIR / "jobs" / job_id


def write_state(job_id: str, patch: dict[str, Any]) -> None:
    with LOCK:
        current = JOBS.setdefault(job_id, {})
        current.update(patch)
        current["updated_at"] = now_iso()
        d = job_dir(job_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def log(job_id: str, message: str) -> None:
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "render.log").open("a", encoding="utf-8") as file:
        file.write(f"[{now_iso()}] {message}\n")


def run_cmd(job_id: str, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    log(job_id, "RUN: " + " ".join(cmd))
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log(job_id, result.stdout[-6000:])
    if result.returncode != 0:
        raise RuntimeError(result.stdout[-3000:])
    return result


def probe_duration(job_id: str, path: Path) -> float:
    result = run_cmd(job_id, [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    try:
        return max(0.1, float(result.stdout.strip()))
    except ValueError:
        return 0.1


def save_upload(upload: UploadFile, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as file:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"Файл больше лимита {MAX_UPLOAD_MB} MB")
            file.write(chunk)


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return str(text).replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def clean_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("♪", " ").replace("♫", " ").replace("\\", " ")
    text = BRACKET_RE.sub(" ", text)
    text = re.sub(r"<\|[^>]+\|>", " ", text)
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.!?;:])", r"\1", text).strip(" -—–…")
    return text.strip()


def is_dialogue_text(text: str) -> bool:
    text = clean_text(text)
    if not text or len(text) < 2 or ONLY_PUNCT_RE.match(text):
        return False
    lowered = text.lower().strip()
    if NON_DIALOGUE_RE.search(lowered):
        words = re.findall(r"[a-zа-яіїєґё]+", lowered, flags=re.IGNORECASE)
        if len(words) <= 6:
            return False
        if words and NON_DIALOGUE_RE.search(words[0]):
            return False
    return True


def wrap_text(text: str, max_chars: int = 28) -> str:
    words = clean_text(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\\N".join(lines[:2])


def subtitle_text(text: str) -> str:
    return ass_escape(wrap_text(text))


def postprocess_segments(raw_segments: list[dict[str, Any]], video_duration: float) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in sorted(raw_segments, key=lambda s: float(s.get("start", 0.0))):
        text = clean_text(str(item.get("text", "")))
        if not is_dialogue_text(text):
            continue
        start = max(0.0, float(item.get("start", 0.0)) - 0.04)
        end = min(video_duration, max(start + 0.35, float(item.get("end", start + 0.35))))
        if cleaned:
            prev = cleaned[-1]
            gap = start - float(prev["end"])
            merged_text = clean_text(str(prev["text"]) + " " + text)
            if -0.05 <= gap <= 0.22 and len(merged_text) <= 72 and is_dialogue_text(merged_text):
                prev["text"] = merged_text
                prev["end"] = max(float(prev["end"]), end)
                continue
        cleaned.append({"start": start, "end": end, "text": text})

    polished: list[dict[str, Any]] = []
    for index, item in enumerate(cleaned):
        text = str(item["text"])
        start = float(item["start"])
        end = float(item["end"])
        next_start = float(cleaned[index + 1]["start"]) if index + 1 < len(cleaned) else video_duration
        min_duration = min(2.8, max(1.0, len(text) * 0.052))
        tail = min(0.65, max(0.26, len(text) * 0.008))
        wanted_end = max(end + tail, start + min_duration)
        safe_next_limit = max(start + 0.55, next_start - 0.07)
        final_end = min(video_duration, wanted_end, safe_next_limit)
        if final_end - start < 0.82:
            start = max(0.0, final_end - 0.82)
        polished.append({"start": round(start, 3), "end": round(final_end, 3), "text": text})
    return polished


def write_title_ass(path: Path, movie_title: str, movie_year: str, duration: float) -> None:
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")
    intro_end = min(duration, 5.0)
    intro_exit_start = min(duration, 4.2)
    outro_start = max(0.0, duration - 5.0)
    axis_y = 1507
    title_y = 1504
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleBlock,DejaVu Sans,48,&H00F6F2EA,&H000000FF,&HAA000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0.4,7,0,0,0,1
Style: Axis,DejaVu Sans,16,&H66EED322,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,{ass_time(0)},{ass_time(intro_end)},Axis,,0,0,0,,{{\\move(-120,{axis_y},74,{axis_y},0,760)\\t({int(intro_exit_start*1000)},{int(intro_end*1000)},\\move(74,{axis_y},-120,{axis_y}))\\fad(120,160)}}{{\\p1}}m 0 0 l 4 0 l 4 116 l 0 116{{\\p0}}
Dialogue: 3,{ass_time(0.02)},{ass_time(intro_end)},TitleBlock,,0,0,0,,{{\\an7\\move(-920,{title_y},96,{title_y},0,760)\\t({int(intro_exit_start*1000)},{int(intro_end*1000)},\\move(96,{title_y},-920,{title_y}))\\blur0.08\\fad(120,160)}}{{\\fs18\\fsp2.4\\c&H9CFFFFFF&\\bord0.35}}TELONYX.APP\\N{{\\fs58\\fsp0.25\\c&H00F6F2EA&\\bord1.65}}{title}\\N{{\\fs30\\fsp3.4\\c&H00EED322&\\bord0.85}}{year}
Dialogue: 1,{ass_time(outro_start)},{ass_time(duration)},Axis,,0,0,0,,{{\\move(-120,{axis_y},74,{axis_y},0,680)\\t({max(0,int((duration-outro_start-0.85)*1000))},{int((duration-outro_start)*1000)},\\move(74,{axis_y},-120,{axis_y}))\\fad(120,190)}}{{\\p1}}m 0 0 l 4 0 l 4 116 l 0 116{{\\p0}}
Dialogue: 3,{ass_time(outro_start)},{ass_time(duration)},TitleBlock,,0,0,0,,{{\\an7\\move(-920,{title_y},96,{title_y},0,680)\\t({max(0,int((duration-outro_start-0.85)*1000))},{int((duration-outro_start)*1000)},\\move(96,{title_y},-920,{title_y}))\\blur0.08\\fad(120,190)}}{{\\fs18\\fsp2.4\\c&H9CFFFFFF&\\bord0.35}}TELONYX.APP\\N{{\\fs58\\fsp0.25\\c&H00F6F2EA&\\bord1.65}}{title}\\N{{\\fs30\\fsp3.4\\c&H00EED322&\\bord0.85}}{year}
""", encoding="utf-8")


def write_subs_ass(path: Path, segments: list[dict[str, Any]]) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SubText,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&HF0000000,&HAA000000,-1,0,0,0,101,100,0,0,1,5.8,1.6,5,70,70,0,1
Style: SubShadow,DejaVu Sans,72,&H66000000,&H000000FF,&H00000000,&H00000000,-1,0,0,0,101,100,0,0,1,0,0,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        raw_text = clean_text(str(seg.get("text", "")))
        if not is_dialogue_text(raw_text):
            continue
        start = float(seg.get("start", 0))
        end = max(start + 0.82, float(seg.get("end", start + 1.0)))
        dur_ms = max(820, int((end - start) * 1000))
        pop_in = min(160, max(80, dur_ms // 6))
        settle = min(pop_in + 120, dur_ms - 80)
        pop_out_start = max(settle + 40, dur_ms - 150)
        text = subtitle_text(raw_text)
        shadow_effect = f"{{\\an5\\move(544,962,544,950,0,{pop_in})\\fad(45,90)\\blur3.2\\fscx92\\fscy92\\t(0,{pop_in},\\fscx106\\fscy106)\\t({pop_in},{settle},\\fscx100\\fscy100)}}"
        text_effect = f"{{\\an5\\move(540,958,540,946,0,{pop_in})\\fad(45,90)\\blur0.18\\fscx92\\fscy92\\t(0,{pop_in},\\fscx106\\fscy106\\blur0)\\t({pop_in},{settle},\\fscx100\\fscy100)\\t({pop_out_start},{dur_ms},\\fscx97\\fscy97\\alpha&H28&)}}"
        lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},SubShadow,,0,0,0,,{shadow_effect}{text}\n")
        lines.append(f"Dialogue: 2,{ass_time(start)},{ass_time(end)},SubText,,0,0,0,,{text_effect}{text}\n")
    path.write_text("".join(lines), encoding="utf-8")


def extract_audio(job_id: str, input_path: Path, audio_path: Path) -> None:
    run_cmd(job_id, [FFMPEG, "-y", "-i", str(input_path), "-vn", "-ac", "1", "-ar", "16000", "-af", "highpass=f=80,lowpass=f=7600,dynaudnorm=f=150:g=13:p=0.95", "-c:a", "pcm_s16le", str(audio_path)])


def transcribe(job_id: str, input_path: Path, language: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = (language or "auto").lower().strip()
    if selected not in LANGUAGE_LABELS:
        selected = "auto"
    if not ENABLE_WHISPER:
        raise RuntimeError("Автосубтитры включены, но ENABLE_WHISPER=false на сервере")
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError(f"faster-whisper не загрузился: {exc}") from exc

    audio_path = job_dir(job_id) / "whisper_16k.wav"


    extract_audio(job_id, input_path, audio_path)
    write_state(job_id, {"subtitles_status": "loading_model", "subtitles_language_requested": selected, "subtitles_language_label": LANGUAGE_LABELS[selected], "message": f"Загружаю Whisper {WHISPER_MODEL}. Язык: {LANGUAGE_LABELS[selected]}"})
    model = WhisperModel(WHISPER_MODEL, device=MODEL_DEVICE, compute_type=COMPUTE_TYPE)
    kwargs: dict[str, Any] = {
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0.0,
        "vad_filter": False,
        "word_timestamps": True,
        "condition_on_previous_text": True,
        "compression_ratio_threshold": 2.8,
        "log_prob_threshold": -1.2,
        "no_speech_threshold": 0.28,
        "suppress_blank": True,
    }
    if selected != "auto":
        kwargs["language"] = selected
        kwargs["initial_prompt"] = LANGUAGE_PROMPTS.get(selected, "")
    try:
        segments_iter, info = model.transcribe(str(audio_path), **kwargs)
    except TypeError as exc:
        log(job_id, f"Whisper TypeError, retry with compatible kwargs: {exc}")
        kwargs.pop("word_timestamps", None)
        kwargs.pop("suppress_blank", None)
        segments_iter, info = model.transcribe(str(audio_path), **kwargs)

    segments = []
    skipped_non_dialogue = 0
    for seg in segments_iter:
        text = clean_text(seg.text)
        if not is_dialogue_text(text):
            skipped_non_dialogue += 1
            continue
        start = float(seg.start)
        end = float(seg.end)
        words = getattr(seg, "words", None)
        if words:
            word_starts = [float(w.start) for w in words if getattr(w, "start", None) is not None]
            word_ends = [float(w.end) for w in words if getattr(w, "end", None) is not None]
            if word_starts:
                start = min(start, min(word_starts))
            if word_ends:
                end = max(end, max(word_ends))
        segments.append({"start": start, "end": end, "text": text})

    meta = {
        "requested_language": selected,
        "detected_language": getattr(info, "language", selected),
        "detected_language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 4),
        "model": WHISPER_MODEL,
        "device": MODEL_DEVICE,
        "compute_type": COMPUTE_TYPE,
        "segments": len(segments),
        "skipped_non_dialogue": skipped_non_dialogue,
        "dialogue_only": True,
        "vad_filter": False,
        "word_timestamps": True,
    }
    log(job_id, "Whisper meta: " + json.dumps(meta, ensure_ascii=False))
    return segments, meta


def video_filter(title_ass: Path, subs_ass: Path | None) -> str:
    chain = ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920", "eq=contrast=1.07:saturation=1.08:brightness=-0.018", "unsharp=5:5:0.55:3:3:0.25", "subtitles='" + ass_filter_path(title_ass) + "'"]
    if subs_ass:
        chain.append("subtitles='" + ass_filter_path(subs_ass) + "'")
    return ",".join(chain)


def render_video(job_id: str) -> None:
    state = JOBS[job_id]
    d = job_dir(job_id)
    input_path = Path(state["input_path"])
    output_path = d / "final_vertical.mp4"
    title_ass = d / "title.ass"
    subs_ass = d / "subtitles.ass"
    try:
        write_state(job_id, {"status": "processing", "progress": 8, "message": "Анализирую длительность видео"})
        duration = probe_duration(job_id, input_path)
        write_state(job_id, {"progress": 22, "duration": duration, "message": "Готовлю TELONYX.APP титр"})
        write_title_ass(title_ass, state["movie_title"], state["movie_year"], duration)
        segments: list[dict[str, Any]] = []
        subs_file: Path | None = None
        if state.get("subtitles_enabled"):
            write_state(job_id, {"progress": 34, "subtitles_requested": True, "subtitles_status": "processing", "message": f"Распознаю только диалоги. Язык: {LANGUAGE_LABELS.get(state.get('language', 'auto'), 'Auto')}"})
            raw_segments, meta = transcribe(job_id, input_path, state.get("language", "auto"))
            segments = postprocess_segments(raw_segments, duration)
            meta["raw_segments"] = len(raw_segments)
            meta["postprocessed_segments"] = len(segments)
            if segments:
                write_subs_ass(subs_ass, segments)
                subs_file = subs_ass
                write_state(job_id, {"progress": 58, "subtitles_status": "ready", "subtitles_segments": len(segments), "subtitles_meta": meta, "message": f"Диалоговые субтитры готовы: {len(segments)} реплик"})
            else:
                write_state(job_id, {"progress": 58, "subtitles_status": "no_speech", "subtitles_segments": 0, "subtitles_meta": meta, "message": "Диалоги не найдены. Рендерю без субтитров."})
        else:
            write_state(job_id, {"subtitles_requested": False, "subtitles_status": "disabled", "subtitles_segments": 0})
        write_state(job_id, {"progress": 68, "message": "Рендерю vertical MP4 1080x1920"})
        run_cmd(job_id, [FFMPEG, "-y", "-i", str(input_path), "-vf", video_filter(title_ass, subs_file), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "256k", "-ac", "2", "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output_path)])
        write_state(job_id, {"status": "done", "progress": 100, "message": "Готово" if segments or not state.get("subtitles_enabled") else "Готово, но без диалоговых субтитров", "output_path": str(output_path), "download_url": f"/api/jobs/{job_id}/download", "segments": len(segments)})
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_state(job_id, {"status": "failed", "progress": 100, "subtitles_status": "failed" if state.get("subtitles_enabled") else state.get("subtitles_status", "disabled"), "subtitles_error": str(exc), "message": str(exc)})


def render_tiktok_video(job_id: str) -> None:
    state = TIKTOK_JOBS[job_id]
    d = job_dir(job_id)
    logo_path = state.get("logo_path", LOGO_PATH)
    rotation_map: dict[str, str] = {"none": "0", "slow": "PI/6*t", "medium": "PI/2*t", "fast": "PI*t"}
    angle = rotation_map.get(state.get("rotation_speed", "slow"), "PI/6*t")
    logo_opacity = max(0.1, min(1.0, float(state.get("opacity", 0.75))))
    try:
        youtube_url = state.get("youtube_url", "").strip()
        if youtube_url:
            write_tiktok_state(job_id, {"status": "processing", "progress": 5, "message": "Скачиваю видео с YouTube..."})
            downloaded = download_youtube_video(job_id, youtube_url, d)
            state["input_path"] = str(downloaded)
            write_tiktok_state(job_id, {"progress": 15, "message": "Видео скачано, начинаю обработку"})
        input_path = Path(state["input_path"])
        output_path = d / "final_tiktok.mp4"
        write_tiktok_state(job_id, {"status": "processing", "progress": 10, "message": "Анализирую видео"})
        duration = probe_duration(job_id, input_path)
        write_tiktok_state(job_id, {"progress": 40, "message": "Накладываю анимированный логотип l2watcher"})
        filter_complex = (
            f"[1:v]scale=100:-1,format=rgba,colorchannelmixer=aa={logo_opacity:.2f},"
            f"rotate={angle}:ow=1.5*iw:oh=1.5*ih:c=black@0[logo];"
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,eq=contrast=1.07:saturation=1.08:brightness=-0.018,"
            f"unsharp=5:5:0.55:3:3:0.25[bg];"
            f"[bg][logo]overlay=(W-w)/2:H-h-30"
        )
        run_cmd(job_id, [
            FFMPEG, "-y",
            "-i", str(input_path),
            "-i", str(logo_path),
            "-filter_complex", filter_complex,
            "-map", "0:a?", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p",
            str(output_path)
        ])
        write_tiktok_state(job_id, {
            "status": "done", "progress": 100,
            "message": "Готово! TikTok видео с логотипом l2watcher",
            "output_path": str(output_path),
            "download_url": f"/api/tiktok-jobs/{job_id}/download",
            "duration": duration
        })
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_tiktok_state(job_id, {"status": "failed", "progress": 100, "message": str(exc)})


def download_youtube_video(job_id: str, url: str, output_dir: Path) -> Path:
    output_path = output_dir / "youtube_input.mp4"
    cmd = [
        YT_DLP_BIN,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=android",
    ]
    cookies_arg = None
    if YT_COOKIES_FILE and Path(YT_COOKIES_FILE).exists():
        cookies_arg = YT_COOKIES_FILE
        log(job_id, f"Using cookies file: {YT_COOKIES_FILE}")
    elif YT_COOKIES_BASE64:
        cookies_path = output_dir / "cookies.txt"
        try:
            raw = base64.b64decode(YT_COOKIES_BASE64)
            decoded = raw.decode("utf-8")
            cookies_path.write_text(decoded, encoding="utf-8")
            cookies_arg = str(cookies_path)
            log(job_id, f"Decoded YT_DLP_COOKIES_BASE64: {len(raw)} bytes -> {cookies_path}")
        except Exception as exc:
            log(job_id, f"Failed to decode YT_DLP_COOKIES_BASE64: {exc}")
    else:
        log(job_id, f"No cookies found: YT_COOKIES_FILE={repr(YT_COOKIES_FILE)}, YT_DLP_COOKIES_BASE64={'set' if os.getenv('YT_DLP_COOKIES_BASE64') else 'NOT SET'}")
    if cookies_arg:
        cmd.extend(["--cookies", cookies_arg])
    cmd.append(url)
    log(job_id, f"Downloading YouTube video: {url}")
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    log(job_id, result.stdout[-3000:])
    if result.returncode != 0:
        msg = result.stdout[-1000:]
        if "Sign in" in msg or "bot" in msg:
            raise RuntimeError(f"YouTube блокирует скачивание без Cookie. Проверь логи выше — видно, нашлись ли куки.")
        raise RuntimeError(f"yt-dlp failed: {msg}")
    if not output_path.exists():
        raise RuntimeError(f"yt-dlp не создал файл: {output_path}")
    return output_path


def cleanup_job(job_id: str) -> None:
    d = job_dir(job_id)
    if d.exists():
        shutil.rmtree(d)
    JOBS.pop(job_id, None)
    TIKTOK_JOBS.pop(job_id, None)


def write_tiktok_state(job_id: str, patch: dict) -> None:
    with LOCK:
        current = TIKTOK_JOBS.setdefault(job_id, {})
        current.update(patch)
        current["updated_at"] = now_iso()
        d = job_dir(job_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "tiktok_state.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


HTML = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TXC Cinema</title><style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#2b1856,transparent 31rem),linear-gradient(135deg,#05060b,#090d16);color:#f8fafc;font-family:Inter,system-ui,Arial}.app{width:min(1180px,calc(100% - 28px));margin:auto;padding:24px 0}.top,.panel{border:1px solid #ffffff24;background:#0f172add;border-radius:28px;box-shadow:0 26px 90px #0008}.top{display:flex;justify-content:space-between;align-items:center;padding:16px 18px}.brand{display:flex;gap:13px;align-items:center}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:950}h1{font-size:18px;margin:0}p{color:#9aa4b2;line-height:1.55}.hero{padding:34px 0 20px}.hero h2{max-width:900px;margin:10px 0;font-size:clamp(34px,5vw,68px);line-height:.94;letter-spacing:-.06em}.grid{display:grid;grid-template-columns:420px 1fr;gap:18px}.head{padding:20px 20px 0}.body{padding:20px}label{display:block;margin:0 0 13px;font-size:12px;font-weight:900}input,select{width:100%;margin-top:7px;padding:14px;border:1px solid #ffffff24;border-radius:16px;background:#070a12;color:#fff;font-size:16px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid #ffffff24;border-radius:16px;background:#070a12}.check input{width:auto}.btn{width:100%;margin-top:14px;padding:15px;border:0;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:white;font-weight:950;cursor:pointer;font-size:16px}.btn:disabled{opacity:.45}.btn.secondary{background:linear-gradient(135deg,#111827,#334155);border:1px solid #22d3ee59}.btn.publish{background:linear-gradient(135deg,#16a34a,#22d3ee)}.toast,.card,.log,.post{margin-top:13px;padding:13px;border:1px solid #ffffff24;border-radius:16px;background:#0003;color:#cbd5e1}.ok{border-color:#22c55e;color:#bbf7d0}.warn{border-color:#f59e0b;color:#fde68a}.err{border-color:#ef4444;color:#fecaca}.phonewrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:18px}.phone{aspect-ratio:9/16;border:1px solid #ffffff24;border-radius:34px;padding:12px;background:#02030a}.screen{position:relative;width:100%;height:100%;overflow:hidden;border-radius:24px;background:radial-gradient(circle at 50% 40%,#22d3ee44,transparent 30%),linear-gradient(#141827,#03040a)}.safe{position:absolute;inset:8%;border:1px dashed #22d3ee88;border-radius:18px}.title{position:absolute;left:8%;bottom:14%;padding-left:14px;text-transform:uppercase;text-shadow:0 3px 16px #000;border-left:3px solid #22d3eea3}.title b{display:block;margin-bottom:7px;font-size:9px;letter-spacing:.22em;color:#ffffffaa}.title strong{display:block;font-size:30px;line-height:.98;font-weight:950;color:#f6f2ea}.title small{display:block;margin-top:8px;font-size:15px;letter-spacing:.26em;color:#22d3ee;font-weight:950}.subs{position:absolute;left:8%;right:8%;top:50%;transform:translateY(-50%);text-align:center;font-weight:950;font-size:26px;line-height:1.08;color:#fff;text-shadow:0 4px 0 #000,0 0 22px #000,0 10px 34px #000}.bar{height:13px;border:1px solid #ffffff24;border-radius:999px;overflow:hidden;background:#05070d}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,#8b5cf6,#22d3ee);transition:.2s}.log{min-height:210px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}.download{display:none;margin-top:12px;padding:14px;border-radius:16px;background:#22c55e22;border:1px solid #22c55e;color:#bbf7d0;text-decoration:none;font-weight:950;text-align:center}.publishBox{display:none;margin-top:18px}.post{white-space:pre-wrap}.imgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px}.imgs img{width:100%;border-radius:16px;border:1px solid #ffffff24}@media(max-width:980px){.grid,.phonewrap{grid-template-columns:1fr}.phone{width:min(380px,100%);margin:auto}}.tabs{display:flex;gap:6px;padding:0 0 10px;flex-wrap:wrap}.tab{padding:7px 16px;border:1px solid #ffffff24;border-radius:999px;background:transparent;color:#9aa4b2;cursor:pointer;font-size:13px;font-weight:700;transition:.2s;font-family:inherit}.tab:hover{border-color:#8b5cf688;color:#fff}.tab.active{background:#8b5cf644;border-color:#8b5cf6;color:#fff;box-shadow:0 0 18px #8b5cf633}.tab-content{display:none}.tab-content.active{display:block}</style></head><body><main class="app"><header class="top"><div class="brand"><div class="logo">TXC</div><div><h1>TXC Ukraine Cinema Finalizer</h1><p>Готовый момент → vertical edit → диалоговые автосубтитры → публикация</p></div></div><span>__VERSION__</span></header><nav class="tabs"><button class="tab active" data-tab-btn="cinema">Cinema</button><button class="tab" data-tab-btn="tiktok">TikTok Shorts</button></nav><section class="hero"><p>TELONYX.APP</p><h2>Чистые cinematic-субтитры только для реальных реплик.</h2><p>Без огромных плашек. Без кислотных рамок. Без описаний музыки и шума.</p></section><div class="tab-content active" data-tab="cinema"><section class="grid"><form id="form" class="panel"><div class="head"><p>01 / INPUT</p><h3>Данные ролика</h3></div><div class="body"><label>Готовый момент из фильма<input id="videoInput" name="video" type="file" accept="video/*" required></label><label>Название фильма<input id="movieTitle" name="movie_title" placeholder="Drive" required></label><div class="row"><label>Год<input id="movieYear" name="movie_year" placeholder="2011" required></label><label>Язык речи<select id="language" name="language"><option value="auto">Auto</option><option value="ru">Русский</option><option value="en">English</option><option value="uk">Українська</option></select></label></div><label class="check"><input id="subtitlesEnabled" name="subtitles_enabled" type="checkbox" checked> Включить автоматические субтитры</label><button id="renderBtn" class="btn" type="button">Сделать финальный vertical edit</button><div id="toast" class="toast">Готов к загрузке.</div></div></form><section class="panel"><div class="head"><p>02 / PREVIEW</p><h3>Статус рендера</h3></div><div class="body phonewrap"><div class="phone"><div class="screen"><div class="safe"></div><div class="title" id="previewTitle"><b>TELONYX.APP</b><strong>MOVIE</strong><small>YEAR</small></div><div class="subs" id="subsPreview">CLEAN CINEMATIC SUBS</div></div></div><div><div class="card"><b>Автосубтитры</b><p id="subsStatus">Ожидание файла</p></div><div class="card"><div class="bar"><span id="progress"></span></div><p id="status">Ожидание файла</p></div><a id="download" class="download" href="#">Скачать готовое видео</a><button id="generate" class="btn secondary" style="display:none" type="button">Генерація</button><div id="log" class="log">WAITING_FOR_UPLOAD</div></div></div></section></section><section id="publishBox" class="panel publishBox"><div class="head"><p>03 / CONTENT PACKAGE</p><h3>Предпросмотр публикации</h3></div><div class="body"><div id="packageStatus" class="toast warn">Ожидание генерации</div><div class="imgs" id="packageImages"></div><h3>Telegram</h3><div id="telegramPost" class="post"></div><h3>TikTok</h3><div id="tiktokPost" class="post"></div><h3>YouTube Shorts</h3><div id="youtubePost" class="post"></div><button id="publishTelegram" class="btn publish" type="button">Публікувати в Telegram</button><div id="publishResult" class="log">PUBLISH_RESULT</div></div></section></div><div class="tab-content" data-tab="tiktok"><section class="grid"><form id="tiktokForm" class="panel"><div class="head"><p>01 / INPUT</p><h3>TikTok Shorts</h3></div><div class="body"><label>YouTube ссылка (Shorts)<input id="tiktokUrlInput" name="youtube_url" type="url" placeholder="https://youtube.com/shorts/..."><small style="color:#9aa4b2;font-size:11px;margin-top:4px;display:block">Если блокирует — установи переменную YT_COOKIES_FILE</small></label><label>Или загрузить видео<input id="tiktokVideoInput" name="video" type="file" accept="video/*"></label><label>Скорость вращения логотипа<select id="rotationSpeed" name="rotation_speed"><option value="slow">Медленно</option><option value="medium">Средне</option><option value="fast">Быстро</option><option value="none">Без вращения</option></select></label><label>Прозрачность логотипа<select id="logoOpacity" name="opacity"><option value="0.50">50%</option><option value="0.65">65%</option><option value="0.75" selected>75%</option><option value="0.85">85%</option><option value="1.00">100%</option></select></label><button id="tiktokRenderBtn" class="btn" type="button">Сделать TikTok видео</button><div id="tiktokToast" class="toast">Готов к загрузке.</div></div></form><section class="panel"><div class="head"><p>02 / PREVIEW</p><h3>Статус рендера</h3></div><div class="body phonewrap"><div class="phone"><div class="screen"><div class="safe"></div><div class="title" id="tiktokPreviewTitle"><b>L2WATCHER</b><strong>LOGO</strong><small>TIKTOK</small></div><div class="subs" id="tiktokSubsPreview">ЛОГОТИП L2WATCHER</div></div></div><div><div class="card"><b>Логотип</b><p id="tiktokLogoStatus">l2watcher avatar</p></div><div class="card"><div class="bar"><span id="tiktokProgress"></span></div><p id="tiktokStatus">Ожидание файла</p></div><a id="tiktokDownload" class="download" href="#">Скачать видео</a><div id="tiktokLog" class="log">WAITING_FOR_UPLOAD</div></div></div></section></section></div></main><script>(function(){'use strict';let currentJobId=null,currentPackageId=null;const form=document.getElementById('form'),videoInput=document.getElementById('videoInput'),movieTitle=document.getElementById('movieTitle'),movieYear=document.getElementById('movieYear'),language=document.getElementById('language'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),subsStatus=document.getElementById('subsStatus'),subsPreview=document.getElementById('subsPreview'),logEl=document.getElementById('log'),download=document.getElementById('download'),renderBtn=document.getElementById('renderBtn'),previewTitle=document.getElementById('previewTitle'),generateBtn=document.getElementById('generate'),publishBox=document.getElementById('publishBox'),packageStatus=document.getElementById('packageStatus'),packageImages=document.getElementById('packageImages'),telegramPost=document.getElementById('telegramPost'),tiktokPost=document.getElementById('tiktokPost'),youtubePost=document.getElementById('youtubePost'),publishTelegram=document.getElementById('publishTelegram'),publishResult=document.getElementById('publishResult');function setToast(t,c){toast.className='toast '+(c||'');toast.textContent=t}function setProgress(v){progress.style.width=(v||0)+'%'}function esc(v){return String(v||'').replace(/[&<>]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]))}function asList(v){if(Array.isArray(v))return v.map(String).filter(Boolean);if(v==null)return[];if(typeof v==='string')return v.split(/[\s,]+/).map(x=>x.trim()).filter(Boolean);if(typeof v==='object')return Object.values(v).flatMap(asList);return[String(v)]}function hashtags(v){return asList(v).join(' ')}function refreshPreview(){previewTitle.innerHTML='<b>TELONYX.APP</b><strong>'+esc(movieTitle.value||'MOVIE')+'</strong><small>'+esc(movieYear.value||'YEAR')+'</small>';subsPreview.textContent=(language.options[language.selectedIndex].text||'TXC')+' SUBTITLES'}async function parseJson(r){const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(JSON.stringify(d));return d}function updateSubs(job){let t='Субтитры: ожидание';if(job.subtitles_status==='processing'||job.subtitles_status==='loading_model')t='Субтитры: распознавание только диалогов, язык '+(job.subtitles_language_label||job.language_label||'Auto');else if(job.subtitles_status==='ready')t='Субтитры: готовы, '+(job.subtitles_segments||job.segments||0)+' реплик';else if(job.subtitles_status==='no_speech')t='Субтитры: диалоги не найдены';else if(job.subtitles_status==='failed')t='Субтитры: ошибка — '+(job.subtitles_error||job.message||'unknown');else if(job.subtitles_status==='disabled')t='Субтитры: выключены';subsStatus.textContent=t}function pollJob(id){fetch('/api/jobs/'+id,{cache:'no-store'}).then(parseJson).then(job=>{setProgress(job.progress||0);statusEl.textContent=job.message||job.status;updateSubs(job);logEl.textContent=JSON.stringify(job,null,2);if(job.status==='done'){currentJobId=id;setToast(job.subtitles_status==='ready'?'Готово. Чистые cinematic-субтитры прожжены.':'Готово.','ok');download.href=job.download_url;download.style.display='block';generateBtn.style.display='block';renderBtn.disabled=false;return}if(job.status==='failed'){setToast('Ошибка рендера: '+(job.message||'unknown'),'err');renderBtn.disabled=false;return}setTimeout(()=>pollJob(id),1500)}).catch(e=>{setToast('Ошибка статуса: '+e.message,'err');renderBtn.disabled=false})}function renderPackage(p){const imgs=Array.isArray(p.images)?p.images:[];packageStatus.className='toast '+(p.status==='ready'?'ok':p.status==='failed'?'err':'warn');packageStatus.textContent=p.message||p.status;packageImages.innerHTML=imgs.map(img=>'<img src="'+esc(img.url)+'" alt="'+esc(img.alt_text_uk||'TELONYX')+'">').join('')||'<div class="toast warn">Картинки ещё генерируются.</div>';telegramPost.innerHTML=esc(p.telegram_text_uk||'');tiktokPost.innerHTML=esc((p.tiktok_title||'')+'\n\n'+(p.tiktok_description||'')+'\n\n'+hashtags(p.tiktok_hashtags));youtubePost.innerHTML=esc((p.youtube_title||'')+'\n\n'+(p.youtube_description||'')+'\n\n'+hashtags(p.youtube_hashtags));publishResult.textContent=JSON.stringify(p.publish_results||p.generator_meta||{},null,2)}function pollPackage(id){fetch('/api/publish-packages/'+id,{cache:'no-store'}).then(parseJson).then(p=>{renderPackage(p);if(p.status==='queued'||p.status==='generating')setTimeout(()=>pollPackage(id),1500)}).catch(e=>{packageStatus.className='toast err';packageStatus.textContent='Ошибка пакета: '+e.message})}function startRender(){refreshPreview();if(!videoInput.files.length)return setToast('Выбери видеофайл.','err');if(!movieTitle.value.trim())return setToast('Введи название фильма.','err');if(!movieYear.value.trim())return setToast('Введи год выхода.','err');download.style.display='none';generateBtn.style.display='none';publishBox.style.display='none';renderBtn.disabled=true;setToast('Загружаю файл и запускаю рендер...','warn');subsStatus.textContent='Субтитры: выбран язык '+language.options[language.selectedIndex].text;setProgress(3);fetch('/api/jobs',{method:'POST',body:new FormData(form)}).then(parseJson).then(r=>{setToast('Задача создана: '+r.job_id,'ok');pollJob(r.job_id)}).catch(e=>{setToast('Ошибка старта: '+e.message,'err');renderBtn.disabled=false})}function startGenerate(){if(!currentJobId)return;publishBox.style.display='block';packageStatus.className='toast warn';packageStatus.textContent='Запускаю генерацию контент-пакета...';fetch('/api/jobs/'+currentJobId+'/generate-package',{method:'POST'}).then(parseJson).then(r=>{currentPackageId=r.package_id;pollPackage(r.package_id)}).catch(e=>{packageStatus.className='toast err';packageStatus.textContent='Ошибка генерации: '+e.message})}function startTelegramPublish(){if(!currentPackageId)return;publishResult.textContent='PUBLISHING_TELEGRAM...';fetch('/api/publish-packages/'+currentPackageId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({targets:['telegram']})}).then(parseJson).then(r=>{publishResult.textContent=JSON.stringify(r,null,2);pollPackage(currentPackageId)}).catch(e=>{publishResult.textContent='ERROR: '+e.message})}form.addEventListener('submit',e=>e.preventDefault());renderBtn.addEventListener('click',startRender);generateBtn.addEventListener('click',startGenerate);publishTelegram.addEventListener('click',startTelegramPublish);movieTitle.addEventListener('input',refreshPreview);movieYear.addEventListener('input',refreshPreview);language.addEventListener('change',refreshPreview);refreshPreview()})();
const tabBtns=document.querySelectorAll('[data-tab-btn]');
const tabContents=document.querySelectorAll('.tab-content');
tabBtns.forEach(btn=>{btn.addEventListener('click',()=>{tabBtns.forEach(b=>b.classList.remove('active'));btn.classList.add('active');const tab=btn.dataset.tabBtn;tabContents.forEach(c=>{c.classList.toggle('active',c.dataset.tab===tab)})})});
let currentTikTokJobId=null;
const tiktokForm=document.getElementById('tiktokForm'),tiktokVideoInput=document.getElementById('tiktokVideoInput'),tiktokUrlInput=document.getElementById('tiktokUrlInput'),tiktokRenderBtn=document.getElementById('tiktokRenderBtn'),tiktokToast=document.getElementById('tiktokToast'),tiktokProgress=document.getElementById('tiktokProgress'),tiktokStatus=document.getElementById('tiktokStatus'),tiktokLog=document.getElementById('tiktokLog'),tiktokDownload=document.getElementById('tiktokDownload');
function tiktokSetToast(t,c){tiktokToast.className='toast '+(c||'');tiktokToast.textContent=t}
function tiktokSetProgress(v){tiktokProgress.style.width=(v||0)+'%'}
function tiktokPollJob(id){fetch('/api/tiktok-jobs/'+id,{cache:'no-store'}).then(r=>r.json()).then(job=>{tiktokSetProgress(job.progress||0);tiktokStatus.textContent=job.message||job.status;tiktokLog.textContent=JSON.stringify(job,null,2);if(job.status==='done'){currentTikTokJobId=id;tiktokSetToast('Готово! Видео с логотипом l2watcher','ok');tiktokDownload.href=job.download_url;tiktokDownload.style.display='block';tiktokRenderBtn.disabled=false;return}if(job.status==='failed'){tiktokSetToast('Ошибка: '+(job.message||'unknown'),'err');tiktokRenderBtn.disabled=false;return}setTimeout(()=>tiktokPollJob(id),1500)}).catch(e=>{tiktokSetToast('Ошибка статуса: '+e.message,'err');tiktokRenderBtn.disabled=false})}
function startTikTokRender(){const url=tiktokUrlInput.value.trim();const file=tiktokVideoInput.files.length;if(!url&&!file)return tiktokSetToast('Укажи YouTube ссылку или выбери видеофайл.','err');tiktokDownload.style.display='none';tiktokRenderBtn.disabled=true;tiktokSetToast(url?'Скачиваю с YouTube...':'Загружаю файл...','warn');tiktokSetProgress(3);const fd=new FormData(tiktokForm);fetch('/api/tiktok-jobs',{method:'POST',body:fd}).then(r=>r.json()).then(r=>{tiktokSetToast('Задача создана: '+r.job_id,'ok');tiktokPollJob(r.job_id)}).catch(e=>{tiktokSetToast('Ошибка старта: '+e.message,'err');tiktokRenderBtn.disabled=false})}
tiktokForm.addEventListener('submit',e=>e.preventDefault());tiktokRenderBtn.addEventListener('click',startTikTokRender);
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    response = HTMLResponse(HTML.replace("__VERSION__", APP_VERSION))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": APP_VERSION, "storage_dir": str(STORAGE_DIR), "whisper_enabled": ENABLE_WHISPER, "whisper_model": WHISPER_MODEL, "model_device": MODEL_DEVICE, "compute_type": COMPUTE_TYPE}


@app.post("/api/jobs")
def create_job(background_tasks: BackgroundTasks, video: UploadFile = File(...), movie_title: str = Form(...), movie_year: str = Form(...), language: str = Form("auto"), subtitles_enabled: bool = Form(False)) -> dict[str, Any]:
    if not video.filename:
        raise HTTPException(status_code=400, detail="Видео не выбрано")
    selected = (language or "auto").lower().strip()
    if selected not in LANGUAGE_LABELS:
        raise HTTPException(status_code=400, detail="Неверный язык речи. Доступно: auto, ru, en, uk")
    job_id = uuid.uuid4().hex[:16]
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    suffix = Path(video.filename).suffix.lower() or ".mp4"
    input_path = d / f"input{suffix}"
    save_upload(video, input_path)
    write_state(job_id, {"job_id": job_id, "status": "queued", "progress": 1, "message": "Задача поставлена в очередь", "movie_title": movie_title.strip(), "movie_year": movie_year.strip(), "language": selected, "language_label": LANGUAGE_LABELS[selected], "subtitles_enabled": subtitles_enabled, "subtitles_requested": subtitles_enabled, "subtitles_status": "queued" if subtitles_enabled else "disabled", "subtitles_segments": 0, "input_path": str(input_path), "created_at": now_iso()})
    background_tasks.add_task(render_video, job_id)
    return {"job_id": job_id, "status_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    state_path = job_dir(job_id) / "state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
    elif job_id in JOBS:
        data = JOBS[job_id]
    else:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    safe = {k: v for k, v in data.items() if k not in {"input_path", "output_path"}}
    return JSONResponse(safe, headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    output = job_dir(job_id) / "final_vertical.mp4"
    if not output.exists():
        raise HTTPException(status_code=404, detail="Файл ещё не готов")
    return FileResponse(output, media_type="video/mp4", filename=f"txc_{job_id}_vertical.mp4", background=BackgroundTask(cleanup_job, job_id))


@app.post("/api/tiktok-jobs")
def create_tiktok_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(None),
    youtube_url: str = Form(""),
    rotation_speed: str = Form("slow"),
    opacity: float = Form(0.75),
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:16]
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    url = (youtube_url or "").strip()
    has_video = video and video.filename
    if not url and not has_video:
        raise HTTPException(status_code=400, detail="Укажи YouTube ссылку или загрузи видео")
    if has_video:
        suffix = Path(video.filename).suffix.lower() or ".mp4"
        input_path = d / f"input{suffix}"
        save_upload(video, input_path)
    else:
        input_path = d / "youtube_input.mp4"
    write_tiktok_state(job_id, {
        "job_id": job_id, "status": "queued", "progress": 1,
        "message": "Задача TikTok поставлена в очередь",
        "rotation_speed": rotation_speed, "opacity": opacity,
        "logo_path": LOGO_PATH, "youtube_url": url,
        "input_path": str(input_path), "created_at": now_iso()
    })
    background_tasks.add_task(render_tiktok_video, job_id)
    return {"job_id": job_id, "status_url": f"/api/tiktok-jobs/{job_id}"}


@app.get("/api/tiktok-jobs/{job_id}")
def get_tiktok_job(job_id: str) -> JSONResponse:
    state_path = job_dir(job_id) / "tiktok_state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
    elif job_id in TIKTOK_JOBS:
        data = TIKTOK_JOBS[job_id]
    else:
        raise HTTPException(status_code=404, detail="Задача TikTok не найдена")
    safe = {k: v for k, v in data.items() if k not in {"input_path", "output_path", "logo_path"}}
    return JSONResponse(safe, headers={"Cache-Control": "no-store"})


@app.get("/api/tiktok-jobs/{job_id}/download")
def download_tiktok(job_id: str) -> FileResponse:
    output = job_dir(job_id) / "final_tiktok.mp4"
    if not output.exists():
        raise HTTPException(status_code=404, detail="Файл ещё не готов")
    return FileResponse(output, media_type="video/mp4", filename=f"tiktok_{job_id}.mp4", background=BackgroundTask(cleanup_job, job_id))
