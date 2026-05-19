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

APP_VERSION = "dialogue-shorts-v16-vad-compatible-2026-05-19"
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
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def clean_text(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("♪", "").split())
    return re.sub(r"\s+([,.!?;:])", r"\1", cleaned).strip()


def wrap_text(text: str, max_chars: int = 34) -> str:
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
    return r"\N".join(lines[:2])


def write_title_ass(path: Path, movie_title: str, movie_year: str, duration: float) -> None:
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")
    outro = max(0.8, duration - 1.2)
    content = f"""[Script Info]
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
"""
    path.write_text(content, encoding="utf-8")


def write_subs_ass(path: Path, segments: list[dict[str, Any]]) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&HCC050505,&H99000000,-1,0,0,0,100,100,0,0,1,4,1,2,72,72,218,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        text = wrap_text(str(seg.get("text", "")))
        if not text:
            continue
        start = float(seg.get("start", 0))
        end = max(start + 0.35, float(seg.get("end", start + 1.2)))
        lines.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\fad(45,90)\\blur0.55}}{ass_escape(text)}\n")
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
        "vad_filter": True,
        "condition_on_previous_text": False,
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -1.0,
        "no_speech_threshold": 0.55,
    }
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
        cmd = [FFMPEG, "-y", "-i", str(input_path), "-vf", video_filter(title_ass, subs_file), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-shortest", str(output_path)]
        run_cmd(job_id, cmd)
        write_state(job_id, {"status": "done", "progress": 100, "message": "Готово" if segments or not state.get("subtitles_enabled") else "Готово, но без диалоговых субтитров", "output_path": str(output_path), "download_url": f"/api/jobs/{job_id}/download", "segments": len(segments)})
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_state(job_id, {"status": "failed", "progress": 100, "subtitles_status": "failed" if state.get("subtitles_enabled") else state.get("subtitles_status", "disabled"), "subtitles_error": str(exc), "message": str(exc)})


HTML = """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TXC Cinema</title><style>body{margin:0;background:#05070d;color:#f8fafc;font-family:Arial,sans-serif}.app{max-width:980px;margin:auto;padding:24px}.panel{background:#0f172a;border:1px solid #334155;border-radius:24px;padding:20px;margin:16px 0}input,select,button{width:100%;padding:14px;margin:8px 0;border-radius:14px;border:1px solid #334155;background:#020617;color:white;font-size:16px}button{border:0;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:900;cursor:pointer}.bar{height:14px;background:#020617;border-radius:99px;overflow:hidden}.bar span{display:block;height:100%;width:0;background:#22d3ee}.ok{color:#bbf7d0}.err{color:#fecaca}.warn{color:#fde68a}.log{white-space:pre-wrap;font:12px monospace;max-height:340px;overflow:auto;background:#020617;padding:12px;border-radius:14px}.download{display:none;color:#bbf7d0;font-weight:900}</style></head><body><main class='app'><h1>TXC Ukraine Cinema Finalizer</h1><p>__VERSION__</p><section class='panel'><form id='form'><label>Готовый момент из фильма<input id='videoInput' name='video' type='file' accept='video/*' required></label><label>Название фильма<input name='movie_title' placeholder='Drive' required></label><label>Год<input name='movie_year' placeholder='2011' required></label><label>Язык речи<select id='language' name='language'><option value='auto'>Auto</option><option value='ru'>Русский</option><option value='en'>English</option><option value='uk'>Українська</option></select></label><label><input name='subtitles_enabled' type='checkbox' checked style='width:auto'> Включить автоматические субтитры</label><button id='renderBtn' type='button'>Сделать финальный vertical edit</button></form><p id='toast' class='warn'>Готов к загрузке.</p></section><section class='panel'><div class='bar'><span id='progress'></span></div><p id='status'>Ожидание файла</p><p id='subsStatus'>Субтитры: ожидание</p><a id='download' class='download' href='#'>Скачать готовое видео</a><button id='generate' style='display:none' type='button'>Генерація</button><div id='log' class='log'>WAITING_FOR_UPLOAD</div></section><section id='publishBox' class='panel' style='display:none'><p id='packageStatus'>Ожидание генерации</p><div id='packageImages'></div><h3>Telegram</h3><pre id='telegramPost'></pre><h3>TikTok</h3><pre id='tiktokPost'></pre><h3>YouTube Shorts</h3><pre id='youtubePost'></pre><button id='publishTelegram'>Публікувати в Telegram</button><div id='publishResult' class='log'>PUBLISH_RESULT</div></section></main><script>let currentJobId=null,currentPackageId=null;const form=document.getElementById('form'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),subsStatus=document.getElementById('subsStatus'),download=document.getElementById('download'),renderBtn=document.getElementById('renderBtn'),generateBtn=document.getElementById('generate'),logEl=document.getElementById('log'),publishBox=document.getElementById('publishBox'),packageStatus=document.getElementById('packageStatus'),telegramPost=document.getElementById('telegramPost'),tiktokPost=document.getElementById('tiktokPost'),youtubePost=document.getElementById('youtubePost'),publishResult=document.getElementById('publishResult');function setToast(t,c){toast.className=c||'';toast.textContent=t}function esc(v){return String(v||'').replace(/[&<>]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]))}async function parseJson(r){const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(JSON.stringify(d));return d}function subsText(j){if(j.subtitles_status==='ready')return 'Субтитры: готовы, '+(j.subtitles_segments||0)+' реплик';if(j.subtitles_status==='failed')return 'Субтитры: ошибка — '+(j.subtitles_error||j.message);if(j.subtitles_status==='no_speech')return 'Субтитры: речь не найдена';if(j.subtitles_status==='processing'||j.subtitles_status==='loading_model')return 'Субтитры: распознавание, язык '+(j.subtitles_language_label||j.language_label||'Auto');if(j.subtitles_status==='disabled')return 'Субтитры: выключены';return 'Субтитры: ожидание'}function pollJob(id){fetch('/api/jobs/'+id,{cache:'no-store'}).then(parseJson).then(j=>{progress.style.width=(j.progress||0)+'%';statusEl.textContent=j.message||j.status;subsStatus.textContent=subsText(j);logEl.textContent=JSON.stringify(j,null,2);if(j.status==='done'){currentJobId=id;setToast('Готово','ok');download.href=j.download_url;download.style.display='block';generateBtn.style.display='block';renderBtn.disabled=false;return}if(j.status==='failed'){setToast('Ошибка рендера: '+(j.message||'unknown'),'err');renderBtn.disabled=false;return}setTimeout(()=>pollJob(id),1500)}).catch(e=>{setToast('Ошибка статуса: '+e.message,'err');renderBtn.disabled=false})}renderBtn.onclick=()=>{if(!document.getElementById('videoInput').files.length)return setToast('Выбери видеофайл','err');download.style.display='none';generateBtn.style.display='none';renderBtn.disabled=true;setToast('Загружаю и рендерю...','warn');fetch('/api/jobs',{method:'POST',body:new FormData(form)}).then(parseJson).then(r=>pollJob(r.job_id)).catch(e=>{setToast('Ошибка старта: '+e.message,'err');renderBtn.disabled=false})};generateBtn.onclick=()=>{if(!currentJobId)return;publishBox.style.display='block';fetch('/api/jobs/'+currentJobId+'/generate-package',{method:'POST'}).then(parseJson).then(r=>{currentPackageId=r.package_id;pollPackage(r.package_id)}).catch(e=>packageStatus.textContent='Ошибка: '+e.message)};function pollPackage(id){fetch('/api/publish-packages/'+id,{cache:'no-store'}).then(parseJson).then(p=>{packageStatus.textContent=p.message||p.status;telegramPost.innerHTML=esc(p.telegram_text_uk||'');tiktokPost.innerHTML=esc((p.tiktok_title||'')+'\n'+(p.tiktok_description||''));youtubePost.innerHTML=esc((p.youtube_title||'')+'\n'+(p.youtube_description||''));if(p.status==='queued'||p.status==='generating')setTimeout(()=>pollPackage(id),1500)})}document.getElementById('publishTelegram').onclick=()=>{if(!currentPackageId)return;fetch('/api/publish-packages/'+currentPackageId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({targets:['telegram']})}).then(parseJson).then(r=>publishResult.textContent=JSON.stringify(r,null,2)).catch(e=>publishResult.textContent=e.message)};form.onsubmit=e=>e.preventDefault();</script></body></html>"""


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
