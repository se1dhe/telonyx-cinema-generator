import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from telonyx_cinema.api.publishing import router as publishing_router

APP_VERSION = "dialogue-shorts-v18-subs-higher-audio-fix-2026-05-19"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1200"))
ENABLE_WHISPER = os.getenv("ENABLE_WHISPER", "true").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

LANGUAGE_LABELS = {"auto": "Auto", "ru": "Русский", "en": "English", "uk": "Українська"}
LANGUAGE_PROMPTS = {
    "ru": "Точная расшифровка русской речи из фильма. Сохраняй имена, паузы и короткие реплики.",
    "uk": "Точна розшифровка української мови з фільму. Зберігай імена, паузи та короткі репліки.",
    "en": "Accurate movie dialogue transcription. Preserve names, pauses and short replies.",
}

app = FastAPI(title="TXC Ukraine Cinema Finalizer", version=APP_VERSION)
app.include_router(publishing_router)
JOBS: dict[str, dict[str, Any]] = {}
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
    # Важно: обратный слеш не экранируем, иначе ASS-перенос строки \N превращается в видимый символ "\".
    return str(text).replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def clean_text(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("♪", "").replace("\\", "").split())
    return re.sub(r"\s+([,.!?;:])", r"\1", cleaned).strip()


def wrap_text(text: str, max_chars: int = 30) -> str:
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


def write_title_ass(path: Path, movie_title: str, movie_year: str, duration: float) -> None:
    # НЕ ТРОГАЕМ позицию титра фильма и года: оставляем как было в версии v17.
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")
    outro = max(0.8, duration - 1.2)
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
Dialogue: 1,{ass_time(0)},{ass_time(outro)},Axis,,0,0,0,,{{\\move(-120,1507,74,1507,0,760)\\fad(120,0)}}{{\\p1}}m 0 0 l 4 0 l 4 116 l 0 116{{\\p0}}
Dialogue: 3,{ass_time(0.02)},{ass_time(outro)},TitleBlock,,0,0,0,,{{\\an7\\move(-920,1504,96,1504,0,760)\\blur0.08\\fad(120,0)}}{{\\fs18\\fsp2.4\\c&H9CFFFFFF&\\bord0.35}}TXC UKRAINE\\N{{\\fs58\\fsp0.25\\c&H00F6F2EA&\\bord1.65}}{title}\\N{{\\fs30\\fsp3.4\\c&H00EED322&\\bord0.85}}{year}
Dialogue: 1,{ass_time(outro)},{ass_time(duration)},Axis,,0,0,0,,{{\\move(74,1507,-120,1507,0,880)\\fad(0,190)}}{{\\p1}}m 0 0 l 4 0 l 4 116 l 0 116{{\\p0}}
Dialogue: 3,{ass_time(outro)},{ass_time(duration)},TitleBlock,,0,0,0,,{{\\an7\\move(96,1504,-920,1504,0,880)\\blur0.08\\fad(0,190)}}{{\\fs18\\fsp2.4\\c&H9CFFFFFF&\\bord0.35}}TXC UKRAINE\\N{{\\fs58\\fsp0.25\\c&H00F6F2EA&\\bord1.65}}{title}\\N{{\\fs30\\fsp3.4\\c&H00EED322&\\bord0.85}}{year}
""", encoding="utf-8")


def write_subs_ass(path: Path, segments: list[dict[str, Any]]) -> None:
    # Субтитры подняты выше: MarginV=410, то есть нижняя граница текста примерно в нижней трети кадра,
    # а не у самого низа и не поверх UI TikTok/Shorts.
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,52,&H00FFFFFF,&H000000FF,&HDD050505,&H99000000,-1,0,0,0,100,100,0,0,1,3.4,0.8,2,82,82,410,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        text = wrap_text(str(seg.get("text", "")))
        if text:
            start = float(seg.get("start", 0))
            end = max(start + 0.35, float(seg.get("end", start + 1.2)))
            lines.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\fad(40,85)\\blur0.32}}{ass_escape(text)}\n")
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
    kwargs: dict[str, Any] = {"beam_size": 5, "best_of": 5, "temperature": 0.0, "vad_filter": True, "condition_on_previous_text": False, "compression_ratio_threshold": 2.4, "log_prob_threshold": -1.0, "no_speech_threshold": 0.55}
    if selected != "auto":
        kwargs["language"] = selected
        kwargs["initial_prompt"] = LANGUAGE_PROMPTS.get(selected, "")
    try:
        segments_iter, info = model.transcribe(str(audio_path), **kwargs)
    except TypeError as exc:
        log(job_id, f"Whisper TypeError, retry with minimal kwargs: {exc}")
        minimal_kwargs = {"beam_size": 5, "best_of": 5, "temperature": 0.0, "vad_filter": False}
        if selected != "auto":
            minimal_kwargs["language"] = selected
        segments_iter, info = model.transcribe(str(audio_path), **minimal_kwargs)

    segments = []
    for seg in segments_iter:
        text = clean_text(seg.text)
        if text:
            segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    meta = {"requested_language": selected, "detected_language": getattr(info, "language", selected), "detected_language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 4), "model": WHISPER_MODEL, "device": MODEL_DEVICE, "compute_type": COMPUTE_TYPE, "segments": len(segments)}
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
        write_state(job_id, {"progress": 22, "duration": duration, "message": "Готовлю TXC Ukraine титр"})
        write_title_ass(title_ass, state["movie_title"], state["movie_year"], duration)
        segments: list[dict[str, Any]] = []
        subs_file: Path | None = None
        if state.get("subtitles_enabled"):
            write_state(job_id, {"progress": 34, "subtitles_requested": True, "subtitles_status": "processing", "message": f"Распознаю диалоги. Язык: {LANGUAGE_LABELS.get(state.get('language', 'auto'), 'Auto')}"})
            segments, meta = transcribe(job_id, input_path, state.get("language", "auto"))
            if segments:
                write_subs_ass(subs_ass, segments)
                subs_file = subs_ass
                write_state(job_id, {"progress": 58, "subtitles_status": "ready", "subtitles_segments": len(segments), "subtitles_meta": meta, "message": f"Субтитры готовы: {len(segments)} реплик"})
            else:
                write_state(job_id, {"progress": 58, "subtitles_status": "no_speech", "subtitles_segments": 0, "subtitles_meta": meta, "message": "Whisper не нашёл диалоги. Рендерю без субтитров."})
        else:
            write_state(job_id, {"subtitles_requested": False, "subtitles_status": "disabled", "subtitles_segments": 0})
        write_state(job_id, {"progress": 68, "message": "Рендерю vertical MP4 1080x1920"})
        run_cmd(job_id, [FFMPEG, "-y", "-i", str(input_path), "-vf", video_filter(title_ass, subs_file), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "256k", "-ac", "2", "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output_path)])
        write_state(job_id, {"status": "done", "progress": 100, "message": "Готово" if segments or not state.get("subtitles_enabled") else "Готово, но без диалоговых субтитров", "output_path": str(output_path), "download_url": f"/api/jobs/{job_id}/download", "segments": len(segments)})
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_state(job_id, {"status": "failed", "progress": 100, "subtitles_status": "failed" if state.get("subtitles_enabled") else state.get("subtitles_status", "disabled"), "subtitles_error": str(exc), "message": str(exc)})


HTML = r"""
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TXC Cinema</title><style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#2b1856,transparent 31rem),linear-gradient(135deg,#05060b,#090d16);color:#f8fafc;font-family:Inter,system-ui,Arial}.app{width:min(1180px,calc(100% - 28px));margin:auto;padding:24px 0}.top,.panel{border:1px solid #ffffff24;background:#0f172add;border-radius:28px;box-shadow:0 26px 90px #0008}.top{display:flex;justify-content:space-between;align-items:center;padding:16px 18px}.brand{display:flex;gap:13px;align-items:center}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:950}h1{font-size:18px;margin:0}p{color:#9aa4b2;line-height:1.55}.hero{padding:34px 0 20px}.hero h2{max-width:900px;margin:10px 0;font-size:clamp(34px,5vw,68px);line-height:.94;letter-spacing:-.06em}.grid{display:grid;grid-template-columns:420px 1fr;gap:18px}.head{padding:20px 20px 0}.body{padding:20px}label{display:block;margin:0 0 13px;font-size:12px;font-weight:900}input,select{width:100%;margin-top:7px;padding:14px;border:1px solid #ffffff24;border-radius:16px;background:#070a12;color:#fff;font-size:16px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid #ffffff24;border-radius:16px;background:#070a12}.check input{width:auto}.btn{width:100%;margin-top:14px;padding:15px;border:0;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:white;font-weight:950;cursor:pointer;font-size:16px}.btn:disabled{opacity:.45}.btn.secondary{background:linear-gradient(135deg,#111827,#334155);border:1px solid #22d3ee59}.btn.publish{background:linear-gradient(135deg,#16a34a,#22d3ee)}.toast,.card,.log,.post{margin-top:13px;padding:13px;border:1px solid #ffffff24;border-radius:16px;background:#0003;color:#cbd5e1}.ok{border-color:#22c55e;color:#bbf7d0}.warn{border-color:#f59e0b;color:#fde68a}.err{border-color:#ef4444;color:#fecaca}.phonewrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:18px}.phone{aspect-ratio:9/16;border:1px solid #ffffff24;border-radius:34px;padding:12px;background:#02030a}.screen{position:relative;width:100%;height:100%;overflow:hidden;border-radius:24px;background:radial-gradient(circle at 50% 40%,#22d3ee44,transparent 30%),linear-gradient(#141827,#03040a)}.safe{position:absolute;inset:8%;border:1px dashed #22d3ee88;border-radius:18px}.title{position:absolute;left:8%;bottom:14%;padding-left:14px;text-transform:uppercase;text-shadow:0 3px 16px #000;border-left:3px solid #22d3eea3}.title b{display:block;margin-bottom:7px;font-size:9px;letter-spacing:.22em;color:#ffffffaa}.title strong{display:block;font-size:30px;line-height:.98;font-weight:950;color:#f6f2ea}.title small{display:block;margin-top:8px;font-size:15px;letter-spacing:.26em;color:#22d3ee;font-weight:950}.subs{position:absolute;left:8%;right:8%;bottom:25%;padding:10px;border-radius:14px;background:#0009;text-align:center;font-weight:900}.bar{height:13px;border:1px solid #ffffff24;border-radius:999px;overflow:hidden;background:#05070d}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,#8b5cf6,#22d3ee);transition:.2s}.log{min-height:210px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}.download{display:none;margin-top:12px;padding:14px;border-radius:16px;background:#22c55e22;border:1px solid #22c55e;color:#bbf7d0;text-decoration:none;font-weight:950;text-align:center}.publishBox{display:none;margin-top:18px}.post{white-space:pre-wrap}.imgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px}.imgs img{width:100%;border-radius:16px;border:1px solid #ffffff24}@media(max-width:980px){.grid,.phonewrap{grid-template-columns:1fr}.phone{width:min(380px,100%);margin:auto}}</style></head><body><main class="app"><header class="top"><div class="brand"><div class="logo">TXC</div><div><h1>TXC Ukraine Cinema Finalizer</h1><p>Готовый момент → vertical edit → автосубтитры → публикация</p></div></div><span>__VERSION__</span></header><section class="hero"><p>TXC UKRAINE</p><h2>Точные автосубтитры по выбранному языку речи.</h2><p>Для максимальной точности выбирай реальный язык диалогов, а не Auto.</p></section><section class="grid"><form id="form" class="panel"><div class="head"><p>01 / INPUT</p><h3>Данные ролика</h3></div><div class="body"><label>Готовый момент из фильма<input id="videoInput" name="video" type="file" accept="video/*" required></label><label>Название фильма<input id="movieTitle" name="movie_title" placeholder="Drive" required></label><div class="row"><label>Год<input id="movieYear" name="movie_year" placeholder="2011" required></label><label>Язык речи<select id="language" name="language"><option value="auto">Auto</option><option value="ru">Русский</option><option value="en">English</option><option value="uk">Українська</option></select></label></div><label class="check"><input id="subtitlesEnabled" name="subtitles_enabled" type="checkbox" checked> Включить автоматические субтитры</label><button id="renderBtn" class="btn" type="button">Сделать финальный vertical edit</button><div id="toast" class="toast">Готов к загрузке.</div></div></form><section class="panel"><div class="head"><p>02 / PREVIEW</p><h3>Статус рендера</h3></div><div class="body phonewrap"><div class="phone"><div class="screen"><div class="safe"></div><div class="title" id="previewTitle"><b>TXC UKRAINE</b><strong>MOVIE</strong><small>YEAR</small></div><div class="subs" id="subsPreview">Субтитры появятся здесь</div></div></div><div><div class="card"><b>Автосубтитры</b><p id="subsStatus">Ожидание файла</p></div><div class="card"><div class="bar"><span id="progress"></span></div><p id="status">Ожидание файла</p></div><a id="download" class="download" href="#">Скачать готовое видео</a><button id="generate" class="btn secondary" style="display:none" type="button">Генерація</button><div id="log" class="log">WAITING_FOR_UPLOAD</div></div></div></section></section><section id="publishBox" class="panel publishBox"><div class="head"><p>03 / CONTENT PACKAGE</p><h3>Предпросмотр публикации</h3></div><div class="body"><div id="packageStatus" class="toast warn">Ожидание генерации</div><div class="imgs" id="packageImages"></div><h3>Telegram</h3><div id="telegramPost" class="post"></div><h3>TikTok</h3><div id="tiktokPost" class="post"></div><h3>YouTube Shorts</h3><div id="youtubePost" class="post"></div><button id="publishTelegram" class="btn publish" type="button">Публікувати в Telegram</button><div id="publishResult" class="log">PUBLISH_RESULT</div></div></section></main><script>(function(){'use strict';let currentJobId=null,currentPackageId=null;const form=document.getElementById('form'),videoInput=document.getElementById('videoInput'),movieTitle=document.getElementById('movieTitle'),movieYear=document.getElementById('movieYear'),language=document.getElementById('language'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),subsStatus=document.getElementById('subsStatus'),subsPreview=document.getElementById('subsPreview'),logEl=document.getElementById('log'),download=document.getElementById('download'),renderBtn=document.getElementById('renderBtn'),previewTitle=document.getElementById('previewTitle'),generateBtn=document.getElementById('generate'),publishBox=document.getElementById('publishBox'),packageStatus=document.getElementById('packageStatus'),packageImages=document.getElementById('packageImages'),telegramPost=document.getElementById('telegramPost'),tiktokPost=document.getElementById('tiktokPost'),youtubePost=document.getElementById('youtubePost'),publishTelegram=document.getElementById('publishTelegram'),publishResult=document.getElementById('publishResult');function setToast(t,c){toast.className='toast '+(c||'');toast.textContent=t}function setProgress(v){progress.style.width=(v||0)+'%'}function esc(v){return String(v||'').replace(/[&<>]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]))}function asList(v){if(Array.isArray(v))return v.map(String).filter(Boolean);if(v==null)return[];if(typeof v==='string')return v.split(/[\s,]+/).map(x=>x.trim()).filter(Boolean);if(typeof v==='object')return Object.values(v).flatMap(asList);return[String(v)]}function hashtags(v){return asList(v).join(' ')}function refreshPreview(){previewTitle.innerHTML='<b>TXC UKRAINE</b><strong>'+esc(movieTitle.value||'MOVIE')+'</strong><small>'+esc(movieYear.value||'YEAR')+'</small>';subsPreview.textContent=language.options[language.selectedIndex].text+' subtitles'}async function parseJson(r){const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(JSON.stringify(d));return d}function updateSubs(job){let t='Субтитры: ожидание';if(job.subtitles_status==='processing'||job.subtitles_status==='loading_model')t='Субтитры: распознавание, язык '+(job.subtitles_language_label||job.language_label||'Auto');else if(job.subtitles_status==='ready')t='Субтитры: готовы, '+(job.subtitles_segments||job.segments||0)+' реплик';else if(job.subtitles_status==='no_speech')t='Субтитры: речь не найдена';else if(job.subtitles_status==='failed')t='Субтитры: ошибка — '+(job.subtitles_error||job.message||'unknown');else if(job.subtitles_status==='disabled')t='Субтитры: выключены';subsStatus.textContent=t}function pollJob(id){fetch('/api/jobs/'+id,{cache:'no-store'}).then(parseJson).then(job=>{setProgress(job.progress||0);statusEl.textContent=job.message||job.status;updateSubs(job);logEl.textContent=JSON.stringify(job,null,2);if(job.status==='done'){currentJobId=id;setToast(job.subtitles_status==='ready'?'Готово. Субтитры прожжены.':'Готово.','ok');download.href=job.download_url;download.style.display='block';generateBtn.style.display='block';renderBtn.disabled=false;return}if(job.status==='failed'){setToast('Ошибка рендера: '+(job.message||'unknown'),'err');renderBtn.disabled=false;return}setTimeout(()=>pollJob(id),1500)}).catch(e=>{setToast('Ошибка статуса: '+e.message,'err');renderBtn.disabled=false})}function renderPackage(p){const imgs=Array.isArray(p.images)?p.images:[];packageStatus.className='toast '+(p.status==='ready'?'ok':p.status==='failed'?'err':'warn');packageStatus.textContent=p.message||p.status;packageImages.innerHTML=imgs.map(img=>'<img src="'+esc(img.url)+'" alt="'+esc(img.alt_text_uk||'TELONYX')+'">').join('')||'<div class="toast warn">Картинки ещё генерируются.</div>';telegramPost.innerHTML=esc(p.telegram_text_uk||'');tiktokPost.innerHTML=esc((p.tiktok_title||'')+'\n\n'+(p.tiktok_description||'')+'\n\n'+hashtags(p.tiktok_hashtags));youtubePost.innerHTML=esc((p.youtube_title||'')+'\n\n'+(p.youtube_description||'')+'\n\n'+hashtags(p.youtube_hashtags));publishResult.textContent=JSON.stringify(p.publish_results||p.generator_meta||{},null,2)}function pollPackage(id){fetch('/api/publish-packages/'+id,{cache:'no-store'}).then(parseJson).then(p=>{renderPackage(p);if(p.status==='queued'||p.status==='generating')setTimeout(()=>pollPackage(id),1500)}).catch(e=>{packageStatus.className='toast err';packageStatus.textContent='Ошибка пакета: '+e.message})}function startRender(){refreshPreview();if(!videoInput.files.length)return setToast('Выбери видеофайл.','err');if(!movieTitle.value.trim())return setToast('Введи название фильма.','err');if(!movieYear.value.trim())return setToast('Введи год выхода.','err');download.style.display='none';generateBtn.style.display='none';publishBox.style.display='none';renderBtn.disabled=true;setToast('Загружаю файл и запускаю рендер...','warn');subsStatus.textContent='Субтитры: выбран язык '+language.options[language.selectedIndex].text;setProgress(3);fetch('/api/jobs',{method:'POST',body:new FormData(form)}).then(parseJson).then(r=>{setToast('Задача создана: '+r.job_id,'ok');pollJob(r.job_id)}).catch(e=>{setToast('Ошибка старта: '+e.message,'err');renderBtn.disabled=false})}function startGenerate(){if(!currentJobId)return;publishBox.style.display='block';packageStatus.className='toast warn';packageStatus.textContent='Запускаю генерацию контент-пакета...';fetch('/api/jobs/'+currentJobId+'/generate-package',{method:'POST'}).then(parseJson).then(r=>{currentPackageId=r.package_id;pollPackage(r.package_id)}).catch(e=>{packageStatus.className='toast err';packageStatus.textContent='Ошибка генерации: '+e.message})}function startTelegramPublish(){if(!currentPackageId)return;publishResult.textContent='PUBLISHING_TELEGRAM...';fetch('/api/publish-packages/'+currentPackageId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({targets:['telegram']})}).then(parseJson).then(r=>{publishResult.textContent=JSON.stringify(r,null,2);pollPackage(currentPackageId)}).catch(e=>{publishResult.textContent='ERROR: '+e.message})}form.addEventListener('submit',e=>e.preventDefault());renderBtn.addEventListener('click',startRender);generateBtn.addEventListener('click',startGenerate);publishTelegram.addEventListener('click',startTelegramPublish);movieTitle.addEventListener('input',refreshPreview);movieYear.addEventListener('input',refreshPreview);language.addEventListener('change',refreshPreview);refreshPreview()})();</script></body></html>
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
    return FileResponse(output, media_type="video/mp4", filename=f"txc_{job_id}_vertical.mp4")
