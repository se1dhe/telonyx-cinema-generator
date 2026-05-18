import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

APP_VERSION = "dialogue-shorts-v5-clean-title-year-2026-05-18"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1200"))
ENABLE_WHISPER = os.getenv("ENABLE_WHISPER", "true").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

app = FastAPI(title="TELONYX Cinema Finalizer", version=APP_VERSION)
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
    with (d / "render.log").open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {message}\n")


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
    with target.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"Файл больше лимита {MAX_UPLOAD_MB} MB")
            f.write(chunk)


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def write_title_ass(path: Path, movie_title: str, movie_year: str, duration: float) -> None:
    # Чистый титр без перегруза: только название фильма и год выхода.
    # Поведение: выкатывается в начале, висит весь шортс, закатывается под конец.
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")

    enter_end_ms = 780
    outro_start = max(0.8, duration - 1.22)
    outro_move_end_ms = 920

    x = 76
    y_title = 1558
    y_year = 1608
    y_line = 1648
    hidden_x = -760

    line_shape = r"{\p1}m 0 0 l 328 0 l 328 3 l 0 3{\p0}"

    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MovieTitle,DejaVu Sans,43,&H00F7F3EA,&H000000FF,&HB0000000,&H00000000,-1,0,0,0,100,100,0,0,1,1.45,0.7,1,0,0,0,1
Style: MovieYear,DejaVu Sans,24,&H96FFFFFF,&H000000FF,&H9A000000,&H00000000,-1,0,0,0,100,100,0,0,1,0.55,0.25,1,0,0,0,1
Style: AccentLine,DejaVu Sans,18,&H0022D3EE,&H000000FF,&H0022D3EE,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Mark,DejaVu Sans,22,&H72FFFFFF,&H000000FF,&H66000000,&H00000000,-1,0,0,0,100,100,0,0,1,0.8,0.4,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 2,{ass_time(0.00)},{ass_time(outro_start)},MovieTitle,,0,0,0,,{{\\move({hidden_x},{y_title},{x},{y_title},0,{enter_end_ms})\\fsp1.8\\blur0.22\\fad(120,0)}}{title}
Dialogue: 2,{ass_time(0.06)},{ass_time(outro_start)},MovieYear,,0,0,0,,{{\\move({hidden_x},{y_year},{x + 2},{y_year},0,{enter_end_ms})\\fsp7\\fad(120,0)}}{year}
Dialogue: 1,{ass_time(0.10)},{ass_time(outro_start)},AccentLine,,0,0,0,,{{\\move({hidden_x},{y_line},{x + 2},{y_line},0,{enter_end_ms})\\alpha&H22&\\fad(120,0)}}{line_shape}

Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},MovieTitle,,0,0,0,,{{\\move({x},{y_title},{hidden_x},{y_title},0,{outro_move_end_ms})\\fsp1.8\\blur0.22\\fad(0,190)}}{title}
Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},MovieYear,,0,0,0,,{{\\move({x + 2},{y_year},{hidden_x},{y_year},0,{outro_move_end_ms})\\fsp7\\fad(0,190)}}{year}
Dialogue: 1,{ass_time(outro_start)},{ass_time(duration)},AccentLine,,0,0,0,,{{\\move({x + 2},{y_line},{hidden_x},{y_line},0,{outro_move_end_ms})\\alpha&H22&\\fad(0,190)}}{line_shape}

Dialogue: 5,{ass_time(0.25)},{ass_time(max(0.3, duration - 0.18))},Mark,,0,0,0,,{{\\pos(1032,960)\\frz90\\fsp5\\alpha&H58&\\fad(420,420)}}TELONYX
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
Style: Sub,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&HCC050505,&H99000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,235,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).strip().split())
        if not text:
            continue
        start = float(seg.get("start", 0))
        end = max(start + 0.35, float(seg.get("end", start + 1.2)))
        styled = "{\\fad(60,120)\\blur0.8}" + ass_escape(text)
        lines.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{styled}\n")
    path.write_text("".join(lines), encoding="utf-8")


def transcribe(job_id: str, input_path: Path, language: str) -> list[dict[str, Any]]:
    if not ENABLE_WHISPER:
        log(job_id, "Whisper disabled")
        return []
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        log(job_id, f"faster-whisper import failed: {exc}")
        return []
    model = WhisperModel(WHISPER_MODEL, device=MODEL_DEVICE, compute_type=COMPUTE_TYPE)
    kwargs: dict[str, Any] = {"vad_filter": True, "beam_size": 5}
    if language and language != "auto":
        kwargs["language"] = language
    segments, info = model.transcribe(str(input_path), **kwargs)
    log(job_id, f"Whisper language={getattr(info, 'language', 'unknown')}")
    return [{"start": float(s.start), "end": float(s.end), "text": s.text} for s in segments]


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
        write_state(job_id, {"progress": 22, "duration": duration, "message": "Готовлю чистый титр фильма и года"})
        write_title_ass(title_ass, state["movie_title"], state["movie_year"], duration)
        segments: list[dict[str, Any]] = []
        if state.get("subtitles_enabled"):
            write_state(job_id, {"progress": 38, "message": "Распознаю диалоги через Whisper"})
            segments = transcribe(job_id, input_path, state.get("language", "auto"))
            write_subs_ass(subs_ass, segments)
        write_state(job_id, {"progress": 68, "message": "Рендерю вертикальное видео 1080x1920"})
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.07:saturation=1.08:brightness=-0.018,unsharp=5:5:0.55:3:3:0.25,subtitles='" + ass_filter_path(title_ass) + "'"
        if segments:
            vf += ",subtitles='" + ass_filter_path(subs_ass) + "'"
        cmd = [FFMPEG, "-y", "-i", str(input_path), "-vf", vf, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-shortest", str(output_path)]
        run_cmd(job_id, cmd)
        write_state(job_id, {"status": "done", "progress": 100, "message": "Готово", "output_path": str(output_path), "download_url": f"/api/jobs/{job_id}/download", "segments": len(segments)})
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_state(job_id, {"status": "failed", "progress": 100, "message": str(exc)})


HTML = """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TELONYX Cinema Finalizer</title><style>:root{color-scheme:dark}body{margin:0;background:radial-gradient(circle at 10% 0,#2b1856,transparent 30rem),linear-gradient(135deg,#05060b,#090d16);color:#f8fafc;font-family:Inter,system-ui,Arial}.app{width:min(1200px,calc(100% - 28px));margin:auto;padding:24px 0}.top,.panel{border:1px solid rgba(255,255,255,.14);background:rgba(15,23,42,.86);border-radius:28px;box-shadow:0 26px 90px #0008}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:16px 18px}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:950}.brand{display:flex;gap:13px;align-items:center}h1{font-size:18px;margin:0}p{color:#9aa4b2;line-height:1.55}.hero{padding:38px 0 22px}.hero h2{max-width:900px;margin:10px 0;font-size:clamp(36px,5vw,72px);line-height:.94;letter-spacing:-.06em}.grid{display:grid;grid-template-columns:420px 1fr;gap:18px}.head{padding:20px 20px 0}.body{padding:20px}label{display:block;margin:0 0 13px;font-size:12px;font-weight:900}input,select{width:100%;margin-top:7px;padding:14px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12;color:#fff}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12}.check input{width:auto}.btn{width:100%;margin-top:14px;padding:15px;border:0;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:white;font-weight:950;cursor:pointer}.toast,.card,.log{margin-top:13px;padding:13px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:rgba(0,0,0,.18);color:#cbd5e1}.ok{border-color:#22c55e;color:#bbf7d0}.warn{border-color:#f59e0b;color:#fde68a}.err{border-color:#ef4444;color:#fecaca}.phonewrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:18px}.phone{aspect-ratio:9/16;border:1px solid rgba(255,255,255,.14);border-radius:34px;padding:12px;background:#02030a}.screen{position:relative;width:100%;height:100%;overflow:hidden;border-radius:24px;background:radial-gradient(circle at 50% 40%,#22d3ee44,transparent 30%),linear-gradient(#141827,#03040a)}.safe{position:absolute;inset:8%;border:1px dashed #22d3ee88;border-radius:18px}.title{position:absolute;left:8%;bottom:14%;font-size:23px;line-height:1.1;font-weight:950;letter-spacing:.11em;text-transform:uppercase;color:#f7f3ea;text-shadow:0 3px 18px #000}.title small{display:block;margin-top:8px;font-size:13px;letter-spacing:.42em;color:rgba(255,255,255,.72)}.title:after{content:'';display:block;width:155px;height:2px;margin-top:13px;background:#22d3ee;box-shadow:0 0 14px #22d3ee88}.mark{position:absolute;right:4%;top:50%;transform:translateY(-50%) rotate(90deg);font-size:11px;font-weight:900;letter-spacing:.42em;color:rgba(255,255,255,.38);text-shadow:0 2px 12px #000}.subs{position:absolute;left:8%;right:8%;bottom:9%;padding:10px;border-radius:14px;background:#0009;text-align:center;font-weight:900}.bar{height:13px;border:1px solid rgba(255,255,255,.14);border-radius:999px;overflow:hidden;background:#05070d}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,#8b5cf6,#22d3ee);transition:.2s}.log{min-height:210px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}.download{display:none;margin-top:12px;padding:14px;border-radius:16px;background:#22c55e22;border:1px solid #22c55e;color:#bbf7d0;text-decoration:none;font-weight:950;text-align:center}@media(max-width:980px){.grid,.phonewrap{grid-template-columns:1fr}.phone{width:min(380px,100%);margin:auto}}</style></head><body><main class='app'><header class='top'><div class='brand'><div class='logo'>TX</div><div><h1>TELONYX Cinema Finalizer</h1><p>Готовый момент → vertical edit с титром и автосабами</p></div></div><span>__VERSION__</span></header><section class='hero'><p>NEW FORMAT</p><h2>Доводим твой готовый момент до премиального Shorts/TikTok вида.</h2><p>Титр снова чистый: только название фильма и год выхода. Без REC, archive, memory cut, иконок и лишнего шума.</p></section><section class='grid'><form id='form' class='panel'><div class='head'><p>01 / INPUT</p><h3>Данные ролика</h3></div><div class='body'><label>Готовый момент из фильма<input name='video' type='file' accept='video/*' required></label><label>Название фильма<input name='movie_title' placeholder='Drive' required></label><div class='row'><label>Год<input name='movie_year' placeholder='2011' required></label><label>Язык речи<select name='language'><option value='auto'>Auto</option><option value='ru'>Русский</option><option value='en'>English</option><option value='uk'>Українська</option></select></label></div><label class='check'><input name='subtitles_enabled' type='checkbox' checked> Включить автоматические субтитры</label><button id='submit' class='btn' type='submit'>Сделать финальный vertical edit</button><div id='toast' class='toast'>Готов к загрузке.</div></div></form><section class='panel'><div class='head'><p>02 / PREVIEW</p><h3>Как будет выглядеть ролик</h3></div><div class='body phonewrap'><div class='phone'><div class='screen'><div class='safe'></div><div class='title' id='previewTitle'>MOVIE<small>YEAR</small></div><div class='mark'>TELONYX</div><div class='subs'>Субтитры появляются в зоне диалога</div></div></div><div><div class='card'><b>Clean movie title · year · TELONYX trademark</b><p>Название и год выкатываются в начале, висят весь ролик и уходят только под конец.</p></div><div class='card'><div class='bar'><span id='progress'></span></div><p id='status'>Ожидание файла</p></div><a id='download' class='download' href='#'>Скачать готовое видео</a><div id='log' class='log'>WAITING_FOR_UPLOAD</div></div></div></section></section></main><script>const form=document.getElementById('form'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),logEl=document.getElementById('log'),download=document.getElementById('download'),submit=document.getElementById('submit'),previewTitle=document.getElementById('previewTitle');function setToast(t,c){toast.className='toast '+(c||'');toast.textContent=t}function setProgress(p){progress.style.width=(p||0)+'%'}function refreshPreview(){previewTitle.innerHTML=(form.movie_title.value||'MOVIE')+'<small>'+(form.movie_year.value||'YEAR')+'</small>'}function poll(id){fetch('/api/jobs/'+id,{cache:'no-store'}).then(r=>r.json()).then(j=>{setProgress(j.progress||0);statusEl.textContent=j.message||j.status;logEl.textContent=JSON.stringify(j,null,2);if(j.status==='done'){setToast('Готово. Можно скачать итоговый MP4.','ok');download.href=j.download_url;download.style.display='block';submit.disabled=false}else if(j.status==='failed'){setToast('Ошибка рендера: '+j.message,'err');submit.disabled=false}else{setTimeout(()=>poll(id),1500)}}).catch(e=>{setToast('Ошибка статуса: '+e.message,'err');submit.disabled=false})}form.movie_title.addEventListener('input',refreshPreview);form.movie_year.addEventListener('input',refreshPreview);form.addEventListener('submit',e=>{e.preventDefault();download.style.display='none';submit.disabled=true;setToast('Загружаю файл и запускаю рендер...','warn');setProgress(3);const fd=new FormData(form);fetch('/api/jobs',{method:'POST',body:fd}).then(r=>r.json().then(j=>{if(!r.ok)throw new Error(JSON.stringify(j));return j})).then(j=>{setToast('Задача создана: '+j.job_id,'ok');poll(j.job_id)}).catch(e=>{setToast('Ошибка старта: '+e.message,'err');submit.disabled=false})})</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    response = HTMLResponse(HTML.replace("__VERSION__", APP_VERSION))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": APP_VERSION, "storage_dir": str(STORAGE_DIR), "whisper_enabled": ENABLE_WHISPER, "whisper_model": WHISPER_MODEL}


@app.post("/api/jobs")
def create_job(background_tasks: BackgroundTasks, video: UploadFile = File(...), movie_title: str = Form(...), movie_year: str = Form(...), language: str = Form("auto"), subtitles_enabled: bool = Form(False)) -> dict[str, Any]:
    if not video.filename:
        raise HTTPException(status_code=400, detail="Видео не выбрано")
    job_id = uuid.uuid4().hex[:16]
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    suffix = Path(video.filename).suffix.lower() or ".mp4"
    input_path = d / f"input{suffix}"
    save_upload(video, input_path)
    write_state(job_id, {"job_id": job_id, "status": "queued", "progress": 1, "message": "Задача поставлена в очередь", "movie_title": movie_title.strip(), "movie_year": movie_year.strip(), "language": language, "subtitles_enabled": subtitles_enabled, "input_path": str(input_path), "created_at": now_iso()})
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
    return FileResponse(output, media_type="video/mp4", filename=f"telonyx_{job_id}_vertical.mp4")
