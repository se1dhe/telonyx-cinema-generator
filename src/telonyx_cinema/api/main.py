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

APP_VERSION = "dialogue-shorts-v4-telonyx-dossier-title-2026-05-18"
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
    # Новый фирменный стиль TELONYX:
    # не обычная плашка с названием, а маленький cinematic dossier tag.
    # Идея: будто кадр прошёл через архивную систему TELONYX — corner marks, micro-code, REC dot и frame id.
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")

    enter_end_ms = 820
    outro_start = max(0.8, duration - 1.28)
    outro_move_end_ms = 960

    x = 72
    y = 1392
    hidden_x = -900

    corner_shape = r"{\p1}m 0 0 l 84 0 m 0 0 l 0 46 m 526 0 l 442 0 m 526 0 l 526 46 m 0 104 l 0 58 m 0 104 l 84 104{\p0}"
    scan_shape = r"{\p1}m 0 0 l 420 0 l 420 2 l 0 2{\p0}"
    dot_shape = r"{\p1}m 0 6 b 0 2 2 0 6 0 b 10 0 12 2 12 6 b 12 10 10 12 6 12 b 2 12 0 10 0 6{\p0}"
    plus_shape = r"{\p1}m 10 0 l 14 0 l 14 10 l 24 10 l 24 14 l 14 14 l 14 24 l 10 24 l 10 14 l 0 14 l 0 10 l 10 10{\p0}"

    micro = ass_escape(f"TX-CINEMA  /  FRAME.ID:{year}  /  MEMORY CUT")
    reel = ass_escape("◈")

    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,DejaVu Sans,40,&H00F4F1EA,&H000000FF,&HAF020304,&H00000000,-1,0,0,0,100,100,0,0,1,1.25,0.65,1,0,0,0,1
Style: Micro,DejaVu Sans,19,&H70FFFFFF,&H000000FF,&H8A000000,&H00000000,-1,0,0,0,100,100,0,0,1,0.45,0.25,1,0,0,0,1
Style: Line,DejaVu Sans,16,&H0019D7D0,&H000000FF,&H0019D7D0,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Ghost,DejaVu Sans,16,&H55FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Red,DejaVu Sans,16,&H003E3EFF,&H000000FF,&H003E3EFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Icon,DejaVu Sans,28,&H0019D7D0,&H000000FF,&H9A000000,&H00000000,-1,0,0,0,100,100,0,0,1,0.4,0.2,5,0,0,0,1
Style: Mark,DejaVu Sans,22,&H72FFFFFF,&H000000FF,&H66000000,&H00000000,-1,0,0,0,100,100,0,0,1,0.8,0.4,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_time(0.00)},{ass_time(outro_start)},Ghost,,0,0,0,,{{\\move({hidden_x},{y},{x},{y},0,{enter_end_ms})\\fad(130,0)}}{corner_shape}
Dialogue: 1,{ass_time(0.04)},{ass_time(outro_start)},Line,,0,0,0,,{{\\move({hidden_x + 24},{y + 116},{x + 24},{y + 116},0,{enter_end_ms})\\fad(130,0)}}{scan_shape}
Dialogue: 2,{ass_time(0.07)},{ass_time(outro_start)},Red,,0,0,0,,{{\\move({hidden_x + 18},{y + 23},{x + 18},{y + 23},0,{enter_end_ms})\\fad(110,0)}}{dot_shape}
Dialogue: 2,{ass_time(0.10)},{ass_time(outro_start)},Micro,,0,0,0,,{{\\move({hidden_x + 40},{y + 17},{x + 40},{y + 17},0,{enter_end_ms})\\fsp3\\alpha&H48&\\fad(110,0)}}REC / TELONYX ARCHIVE
Dialogue: 2,{ass_time(0.13)},{ass_time(outro_start)},Icon,,0,0,0,,{{\\move({hidden_x + 28},{y + 63},{x + 28},{y + 63},0,{enter_end_ms})\\fad(110,0)}}{reel}
Dialogue: 3,{ass_time(0.16)},{ass_time(outro_start)},Title,,0,0,0,,{{\\move({hidden_x + 70},{y + 48},{x + 70},{y + 48},0,{enter_end_ms})\\fsp2.2\\blur0.28\\fad(110,0)}}{title}
Dialogue: 2,{ass_time(0.19)},{ass_time(outro_start)},Micro,,0,0,0,,{{\\move({hidden_x + 72},{y + 91},{x + 72},{y + 91},0,{enter_end_ms})\\fsp3.6\\fad(110,0)}}{micro}
Dialogue: 1,{ass_time(0.22)},{ass_time(outro_start)},Line,,0,0,0,,{{\\move({hidden_x + 514},{y + 91},{x + 514},{y + 91},0,{enter_end_ms})\\fad(110,0)}}{plus_shape}

Dialogue: 0,{ass_time(outro_start)},{ass_time(duration)},Ghost,,0,0,0,,{{\\move({x},{y},{hidden_x},{y},0,{outro_move_end_ms})\\fad(0,190)}}{corner_shape}
Dialogue: 1,{ass_time(outro_start)},{ass_time(duration)},Line,,0,0,0,,{{\\move({x + 24},{y + 116},{hidden_x + 24},{y + 116},0,{outro_move_end_ms})\\fad(0,190)}}{scan_shape}
Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},Red,,0,0,0,,{{\\move({x + 18},{y + 23},{hidden_x + 18},{y + 23},0,{outro_move_end_ms})\\fad(0,190)}}{dot_shape}
Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},Micro,,0,0,0,,{{\\move({x + 40},{y + 17},{hidden_x + 40},{y + 17},0,{outro_move_end_ms})\\fsp3\\alpha&H48&\\fad(0,190)}}REC / TELONYX ARCHIVE
Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},Icon,,0,0,0,,{{\\move({x + 28},{y + 63},{hidden_x + 28},{y + 63},0,{outro_move_end_ms})\\fad(0,190)}}{reel}
Dialogue: 3,{ass_time(outro_start)},{ass_time(duration)},Title,,0,0,0,,{{\\move({x + 70},{y + 48},{hidden_x + 70},{y + 48},0,{outro_move_end_ms})\\fsp2.2\\blur0.28\\fad(0,190)}}{title}
Dialogue: 2,{ass_time(outro_start)},{ass_time(duration)},Micro,,0,0,0,,{{\\move({x + 72},{y + 91},{hidden_x + 72},{y + 91},0,{outro_move_end_ms})\\fsp3.6\\fad(0,190)}}{micro}
Dialogue: 1,{ass_time(outro_start)},{ass_time(duration)},Line,,0,0,0,,{{\\move({x + 514},{y + 91},{hidden_x + 514},{y + 91},0,{outro_move_end_ms})\\fad(0,190)}}{plus_shape}

Dialogue: 5,{ass_time(0.25)},{ass_time(max(0.3, duration - 0.18))},Mark,,0,0,0,,{{\\pos(1032,960)\\frz90\\fsp5\\alpha&H54&\\fad(420,420)}}TELONYX
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
        write_state(job_id, {"progress": 22, "duration": duration, "message": "Готовлю TELONYX dossier title"})
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


HTML = """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TELONYX Cinema Finalizer</title><style>:root{color-scheme:dark}body{margin:0;background:radial-gradient(circle at 10% 0,#2b1856,transparent 30rem),linear-gradient(135deg,#05060b,#090d16);color:#f8fafc;font-family:Inter,system-ui,Arial}.app{width:min(1200px,calc(100% - 28px));margin:auto;padding:24px 0}.top,.panel{border:1px solid rgba(255,255,255,.14);background:rgba(15,23,42,.86);border-radius:28px;box-shadow:0 26px 90px #0008}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:16px 18px}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:950}.brand{display:flex;gap:13px;align-items:center}h1{font-size:18px;margin:0}p{color:#9aa4b2;line-height:1.55}.hero{padding:38px 0 22px}.hero h2{max-width:900px;margin:10px 0;font-size:clamp(36px,5vw,72px);line-height:.94;letter-spacing:-.06em}.grid{display:grid;grid-template-columns:420px 1fr;gap:18px}.head{padding:20px 20px 0}.body{padding:20px}label{display:block;margin:0 0 13px;font-size:12px;font-weight:900}input,select{width:100%;margin-top:7px;padding:14px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12;color:#fff}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12}.check input{width:auto}.btn{width:100%;margin-top:14px;padding:15px;border:0;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:white;font-weight:950;cursor:pointer}.toast,.card,.log{margin-top:13px;padding:13px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:rgba(0,0,0,.18);color:#cbd5e1}.ok{border-color:#22c55e;color:#bbf7d0}.warn{border-color:#f59e0b;color:#fde68a}.err{border-color:#ef4444;color:#fecaca}.phonewrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:18px}.phone{aspect-ratio:9/16;border:1px solid rgba(255,255,255,.14);border-radius:34px;padding:12px;background:#02030a}.screen{position:relative;width:100%;height:100%;overflow:hidden;border-radius:24px;background:radial-gradient(circle at 50% 40%,#22d3ee44,transparent 30%),linear-gradient(#141827,#03040a)}.safe{position:absolute;inset:8%;border:1px dashed #22d3ee88;border-radius:18px}.dossier{position:absolute;left:7%;bottom:25%;width:55%;height:76px;border:1px solid rgba(255,255,255,.34);border-right:0;border-bottom:0;color:#f4f1ea;text-shadow:0 3px 18px #000}.dossier:before{content:'● REC / TELONYX ARCHIVE';position:absolute;left:22px;top:-18px;font-size:9px;letter-spacing:.28em;color:rgba(255,255,255,.58)}.dossier:after{content:'';position:absolute;left:22px;bottom:-14px;width:72%;height:2px;background:#19d7d0;box-shadow:0 0 14px #19d7d088}.reel{position:absolute;left:20px;top:25px;color:#19d7d0;font-size:22px}.title{position:absolute;left:55px;top:22px;font-size:19px;line-height:1.05;font-weight:950;letter-spacing:.13em;text-transform:uppercase}.title small{display:block;margin-top:7px;font-size:8px;letter-spacing:.26em;color:rgba(255,255,255,.62)}.plus{position:absolute;right:-10px;bottom:-11px;color:#19d7d0;font-size:20px}.mark{position:absolute;right:4%;top:50%;transform:translateY(-50%) rotate(90deg);font-size:11px;font-weight:900;letter-spacing:.42em;color:rgba(255,255,255,.42);text-shadow:0 2px 12px #000}.subs{position:absolute;left:8%;right:8%;bottom:9%;padding:10px;border-radius:14px;background:#0009;text-align:center;font-weight:900}.bar{height:13px;border:1px solid rgba(255,255,255,.14);border-radius:999px;overflow:hidden;background:#05070d}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,#8b5cf6,#22d3ee);transition:.2s}.log{min-height:210px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}.download{display:none;margin-top:12px;padding:14px;border-radius:16px;background:#22c55e22;border:1px solid #22c55e;color:#bbf7d0;text-decoration:none;font-weight:950;text-align:center}@media(max-width:980px){.grid,.phonewrap{grid-template-columns:1fr}.phone{width:min(380px,100%);margin:auto}}</style></head><body><main class='app'><header class='top'><div class='brand'><div class='logo'>TX</div><div><h1>TELONYX Cinema Finalizer</h1><p>Готовый момент → vertical edit с титром и автосабами</p></div></div><span>__VERSION__</span></header><section class='hero'><p>NEW FORMAT</p><h2>Доводим твой готовый момент до премиального Shorts/TikTok вида.</h2><p>Новый титр — не шаблонная плашка, а фирменный TELONYX dossier tag: frame marks, REC, micro-code, год внутри архивного идентификатора и trademark справа.</p></section><section class='grid'><form id='form' class='panel'><div class='head'><p>01 / INPUT</p><h3>Данные ролика</h3></div><div class='body'><label>Готовый момент из фильма<input name='video' type='file' accept='video/*' required></label><label>Название фильма<input name='movie_title' placeholder='Drive' required></label><div class='row'><label>Год<input name='movie_year' placeholder='2011' required></label><label>Язык речи<select name='language'><option value='auto'>Auto</option><option value='ru'>Русский</option><option value='en'>English</option><option value='uk'>Українська</option></select></label></div><label class='check'><input name='subtitles_enabled' type='checkbox' checked> Включить автоматические субтитры</label><button id='submit' class='btn' type='submit'>Сделать финальный vertical edit</button><div id='toast' class='toast'>Готов к загрузке.</div></div></form><section class='panel'><div class='head'><p>02 / PREVIEW</p><h3>Как будет выглядеть ролик</h3></div><div class='body phonewrap'><div class='phone'><div class='screen'><div class='safe'></div><div class='dossier'><span class='reel'>◈</span><div class='title' id='previewTitle'>MOVIE<small>TX-CINEMA / FRAME.ID:YEAR / MEMORY CUT</small></div><span class='plus'>✚</span></div><div class='mark'>TELONYX</div><div class='subs'>Субтитры появляются в зоне диалога</div></div></div><div><div class='card'><b>TELONYX dossier tag · REC mark · frame id · right trademark</b><p>Название выглядит как часть авторской системы разметки кадра, а не как стандартный шаблон.</p></div><div class='card'><div class='bar'><span id='progress'></span></div><p id='status'>Ожидание файла</p></div><a id='download' class='download' href='#'>Скачать готовое видео</a><div id='log' class='log'>WAITING_FOR_UPLOAD</div></div></div></section></section></main><script>const form=document.getElementById('form'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),logEl=document.getElementById('log'),download=document.getElementById('download'),submit=document.getElementById('submit'),previewTitle=document.getElementById('previewTitle');function setToast(t,c){toast.className='toast '+(c||'');toast.textContent=t}function setProgress(p){progress.style.width=(p||0)+'%'}function refreshPreview(){previewTitle.innerHTML=(form.movie_title.value||'MOVIE')+'<small>TX-CINEMA / FRAME.ID:'+(form.movie_year.value||'YEAR')+' / MEMORY CUT</small>'}function poll(id){fetch('/api/jobs/'+id,{cache:'no-store'}).then(r=>r.json()).then(j=>{setProgress(j.progress||0);statusEl.textContent=j.message||j.status;logEl.textContent=JSON.stringify(j,null,2);if(j.status==='done'){setToast('Готово. Можно скачать итоговый MP4.','ok');download.href=j.download_url;download.style.display='block';submit.disabled=false}else if(j.status==='failed'){setToast('Ошибка рендера: '+j.message,'err');submit.disabled=false}else{setTimeout(()=>poll(id),1500)}}).catch(e=>{setToast('Ошибка статуса: '+e.message,'err');submit.disabled=false})}form.movie_title.addEventListener('input',refreshPreview);form.movie_year.addEventListener('input',refreshPreview);form.addEventListener('submit',e=>{e.preventDefault();download.style.display='none';submit.disabled=true;setToast('Загружаю файл и запускаю рендер...','warn');setProgress(3);const fd=new FormData(form);fetch('/api/jobs',{method:'POST',body:fd}).then(r=>r.json().then(j=>{if(!r.ok)throw new Error(JSON.stringify(j));return j})).then(j=>{setToast('Задача создана: '+j.job_id,'ok');poll(j.job_id)}).catch(e=>{setToast('Ошибка старта: '+e.message,'err');submit.disabled=false})})</script></body></html>"""


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
