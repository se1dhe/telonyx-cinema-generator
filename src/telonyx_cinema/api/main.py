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

from telonyx_cinema.api.publishing import router as publishing_router

APP_VERSION = "dialogue-shorts-v14-preview-normalize-2026-05-18"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1200"))
ENABLE_WHISPER = os.getenv("ENABLE_WHISPER", "true").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

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
    title = ass_escape((movie_title.strip() or "MOVIE").upper())
    year = ass_escape(movie_year.strip() or "YEAR")
    enter_end_ms = 760
    outro_start = max(0.8, duration - 1.2)
    outro_move_end_ms = 880
    x_text, y_text = 96, 1504
    x_axis, y_axis = 74, 1507
    hidden_text_x, hidden_axis_x = -920, -120
    cyan = "&H00EED322"
    cyan_soft = "&H66EED322"
    axis_shape = r"{\p1}m 0 0 l 4 0 l 4 116 l 0 116{\p0}"
    text_block = (
        r"{\fs18\fsp2.4\c&H9CFFFFFF&\3c&H7A000000&\bord0.35\shad0.12}TXC UKRAINE"
        r"\N{\fs58\fsp0.25\c&H00F6F2EA&\3c&H00000000&\bord1.65\shad0.65}" + title +
        r"\N{\fs30\fsp3.4\c" + cyan + r"\3c&H00000000&\bord0.85\shad0.25}" + year
    )
    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TitleBlock,DejaVu Sans,48,&H00F6F2EA,&H000000FF,&HAA000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0.4,7,0,0,0,1
Style: Axis,DejaVu Sans,16,{cyan_soft},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,{ass_time(0.00)},{ass_time(outro_start)},Axis,,0,0,0,,{{\\move({hidden_axis_x},{y_axis},{x_axis},{y_axis},0,{enter_end_ms})\\fad(120,0)}}{axis_shape}
Dialogue: 3,{ass_time(0.02)},{ass_time(outro_start)},TitleBlock,,0,0,0,,{{\\an7\\move({hidden_text_x},{y_text},{x_text},{y_text},0,{enter_end_ms})\\blur0.08\\fad(120,0)}}{text_block}
Dialogue: 1,{ass_time(outro_start)},{ass_time(duration)},Axis,,0,0,0,,{{\\move({x_axis},{y_axis},{hidden_axis_x},{y_axis},0,{outro_move_end_ms})\\fad(0,190)}}{axis_shape}
Dialogue: 3,{ass_time(outro_start)},{ass_time(duration)},TitleBlock,,0,0,0,,{{\\an7\\move({x_text},{y_text},{hidden_text_x},{y_text},0,{outro_move_end_ms})\\blur0.08\\fad(0,190)}}{text_block}
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
        lines.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\fad(60,120)\\blur0.8}}{ass_escape(text)}\n")
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
        write_state(job_id, {"progress": 22, "duration": duration, "message": "Готовлю TXC Ukraine титр"})
        write_title_ass(title_ass, state["movie_title"], state["movie_year"], duration)
        segments: list[dict[str, Any]] = []
        if state.get("subtitles_enabled"):
            write_state(job_id, {"progress": 38, "message": "Распознаю диалоги через Whisper"})
            segments = transcribe(job_id, input_path, state.get("language", "auto"))
            write_subs_ass(subs_ass, segments)
        write_state(job_id, {"progress": 68, "message": "Рендерю vertical MP4 1080x1920"})
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.07:saturation=1.08:brightness=-0.018,unsharp=5:5:0.55:3:3:0.25,subtitles='" + ass_filter_path(title_ass) + "'"
        if segments:
            vf += ",subtitles='" + ass_filter_path(subs_ass) + "'"
        cmd = [FFMPEG, "-y", "-i", str(input_path), "-vf", vf, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-shortest", str(output_path)]
        run_cmd(job_id, cmd)
        write_state(job_id, {"status": "done", "progress": 100, "message": "Готово", "output_path": str(output_path), "download_url": f"/api/jobs/{job_id}/download", "segments": len(segments)})
    except Exception as exc:
        log(job_id, f"FAILED: {exc}")
        write_state(job_id, {"status": "failed", "progress": 100, "message": str(exc)})


HTML = r"""
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TXC Ukraine Cinema Finalizer</title><style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#2b1856,transparent 30rem),linear-gradient(135deg,#05060b,#090d16);color:#f8fafc;font-family:Inter,system-ui,Arial}.app{width:min(1200px,calc(100% - 28px));margin:auto;padding:24px 0}.top,.panel{border:1px solid rgba(255,255,255,.14);background:rgba(15,23,42,.86);border-radius:28px;box-shadow:0 26px 90px #0008}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:16px 18px}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);font-weight:950}.brand{display:flex;gap:13px;align-items:center}h1{font-size:18px;margin:0}p{color:#9aa4b2;line-height:1.55}.hero{padding:38px 0 22px}.hero h2{max-width:900px;margin:10px 0;font-size:clamp(36px,5vw,72px);line-height:.94;letter-spacing:-.06em}.grid{display:grid;grid-template-columns:420px 1fr;gap:18px}.head{padding:20px 20px 0}.body{padding:20px}label{display:block;margin:0 0 13px;font-size:12px;font-weight:900}input,select{width:100%;margin-top:7px;padding:14px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12;color:#fff}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:#070a12}.check input{width:auto}.btn{width:100%;margin-top:14px;padding:15px;border:0;border-radius:18px;background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:white;font-weight:950;cursor:pointer}.btn:disabled{opacity:.45;cursor:not-allowed}.btn.secondary{background:linear-gradient(135deg,#111827,#334155);border:1px solid rgba(34,211,238,.35)}.btn.publish{background:linear-gradient(135deg,#16a34a,#22d3ee)}.toast,.card,.log,.post{margin-top:13px;padding:13px;border:1px solid rgba(255,255,255,.14);border-radius:16px;background:rgba(0,0,0,.18);color:#cbd5e1}.ok{border-color:#22c55e;color:#bbf7d0}.warn{border-color:#f59e0b;color:#fde68a}.err{border-color:#ef4444;color:#fecaca}.phonewrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:18px}.phone{aspect-ratio:9/16;border:1px solid rgba(255,255,255,.14);border-radius:34px;padding:12px;background:#02030a}.screen{position:relative;width:100%;height:100%;overflow:hidden;border-radius:24px;background:radial-gradient(circle at 50% 40%,#22d3ee44,transparent 30%),linear-gradient(#141827,#03040a)}.safe{position:absolute;inset:8%;border:1px dashed #22d3ee88;border-radius:18px}.title{position:absolute;left:8%;bottom:14%;padding-left:14px;text-transform:uppercase;text-shadow:0 3px 16px #000;border-left:3px solid rgba(34,211,238,.64)}.title b{display:block;margin-bottom:7px;font-size:9px;letter-spacing:.22em;color:rgba(255,255,255,.66)}.title strong{display:block;font-size:30px;line-height:.98;font-weight:950;letter-spacing:.025em;color:#f6f2ea}.title small{display:block;margin-top:8px;font-size:15px;letter-spacing:.26em;color:#22d3ee;font-weight:950}.subs{position:absolute;left:8%;right:8%;bottom:9%;padding:10px;border-radius:14px;background:#0009;text-align:center;font-weight:900}.bar{height:13px;border:1px solid rgba(255,255,255,.14);border-radius:999px;overflow:hidden;background:#05070d}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,#8b5cf6,#22d3ee);transition:.2s}.log{min-height:210px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12px/1.5 monospace}.download{display:none;margin-top:12px;padding:14px;border-radius:16px;background:#22c55e22;border:1px solid #22c55e;color:#bbf7d0;text-decoration:none;font-weight:950;text-align:center}.publishBox{display:none;margin-top:18px}.post{white-space:pre-wrap}.imgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px}.imgs img{width:100%;border-radius:16px;border:1px solid rgba(255,255,255,.14)}.telegramPreview{margin-top:12px;padding:14px;border-radius:22px;border:1px solid rgba(34,211,238,.22);background:linear-gradient(135deg,rgba(34,211,238,.08),rgba(139,92,246,.06))}@media(max-width:980px){.grid,.phonewrap{grid-template-columns:1fr}.phone{width:min(380px,100%);margin:auto}}</style></head><body><main class="app"><header class="top"><div class="brand"><div class="logo">TXC</div><div><h1>TXC Ukraine Cinema Finalizer</h1><p>Готовый момент → vertical edit → Telegram/TikTok/Shorts package</p></div></div><span>__VERSION__</span></header><section class="hero"><p>TXC UKRAINE</p><h2>Фирменные Shorts/TikTok и готовый украинский пост для киноканала.</h2><p>После рендера нажми «Генерація»: приложение подготовит текст, хештеги и фирменные изображения.</p></section><section class="grid"><form id="form" class="panel" action="javascript:void(0)" onsubmit="return false;"><div class="head"><p>01 / INPUT</p><h3>Данные ролика</h3></div><div class="body"><label>Готовый момент из фильма<input id="videoInput" name="video" type="file" accept="video/*" required></label><label>Название фильма<input id="movieTitle" name="movie_title" placeholder="Drive" required></label><div class="row"><label>Год<input id="movieYear" name="movie_year" placeholder="2011" required></label><label>Язык речи<select id="language" name="language"><option value="auto">Auto</option><option value="ru">Русский</option><option value="en">English</option><option value="uk">Українська</option></select></label></div><label class="check"><input id="subtitlesEnabled" name="subtitles_enabled" type="checkbox" checked> Включить автоматические субтитры</label><button id="renderBtn" class="btn" type="button">Сделать финальный vertical edit</button><div id="toast" class="toast">Готов к загрузке.</div></div></form><section class="panel"><div class="head"><p>02 / PREVIEW</p><h3>Айдентика титра</h3></div><div class="body phonewrap"><div class="phone"><div class="screen"><div class="safe"></div><div class="title" id="previewTitle"><b>TXC UKRAINE</b><strong>MOVIE</strong><small>YEAR</small></div><div class="subs">Субтитры появляются в зоне диалога</div></div></div><div><div class="card"><b>No right-side watermark</b><p>TXC Ukraine, название и год остаются только в основном титре слева.</p></div><div class="card"><div class="bar"><span id="progress"></span></div><p id="status">Ожидание файла</p></div><a id="download" class="download" href="#">Скачать готовое видео</a><button id="generate" class="btn secondary" style="display:none" type="button">Генерація</button><div id="log" class="log">WAITING_FOR_UPLOAD</div></div></div></section></section><section id="publishBox" class="panel publishBox"><div class="head"><p>03 / CONTENT PACKAGE</p><h3>Предпросмотр публикации</h3></div><div class="body"><div id="packageStatus" class="toast warn">Ожидание генерации</div><div class="telegramPreview"><h3>Telegram preview</h3><div class="imgs" id="packageImages"></div><div id="telegramPost" class="post"></div></div><h3>TikTok</h3><div id="tiktokPost" class="post"></div><h3>YouTube Shorts</h3><div id="youtubePost" class="post"></div><button id="publishTelegram" class="btn publish" type="button">Публікувати в Telegram</button><div id="publishResult" class="log">PUBLISH_RESULT</div></div></section></main><script>(function(){'use strict';let currentJobId=null,currentPackageId=null;const form=document.getElementById('form'),videoInput=document.getElementById('videoInput'),movieTitle=document.getElementById('movieTitle'),movieYear=document.getElementById('movieYear'),toast=document.getElementById('toast'),progress=document.getElementById('progress'),statusEl=document.getElementById('status'),logEl=document.getElementById('log'),download=document.getElementById('download'),renderBtn=document.getElementById('renderBtn'),previewTitle=document.getElementById('previewTitle'),generateBtn=document.getElementById('generate'),publishBox=document.getElementById('publishBox'),packageStatus=document.getElementById('packageStatus'),packageImages=document.getElementById('packageImages'),telegramPost=document.getElementById('telegramPost'),tiktokPost=document.getElementById('tiktokPost'),youtubePost=document.getElementById('youtubePost'),publishTelegram=document.getElementById('publishTelegram'),publishResult=document.getElementById('publishResult');function setToast(text,cls){toast.className='toast '+(cls||'');toast.textContent=text}function setProgress(value){progress.style.width=(value||0)+'%'}function esc(value){return String(value||'').replace(/[&<>]/g,function(ch){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]})}function asList(value){if(Array.isArray(value))return value.map(String).filter(Boolean);if(value===null||value===undefined)return[];if(typeof value==='string')return value.split(/[\s,]+/).map(function(x){return x.trim()}).filter(Boolean);if(typeof value==='object')return Object.values(value).flatMap(asList);return[String(value)]}function hashtags(value){return asList(value).join(' ')}function refreshPreview(){previewTitle.innerHTML='<b>TXC UKRAINE</b><strong>'+esc(movieTitle.value||'MOVIE')+'</strong><small>'+esc(movieYear.value||'YEAR')+'</small>'}async function parseJsonResponse(response){const data=await response.json().catch(function(){return{}});if(!response.ok)throw new Error(JSON.stringify(data));return data}function pollJob(jobId){fetch('/api/jobs/'+jobId,{cache:'no-store'}).then(parseJsonResponse).then(function(job){setProgress(job.progress||0);statusEl.textContent=job.message||job.status;logEl.textContent=JSON.stringify(job,null,2);if(job.status==='done'){currentJobId=jobId;setToast('Готово. Можно скачать итоговый MP4 или генерировать пост.','ok');download.href=job.download_url;download.style.display='block';generateBtn.style.display='block';renderBtn.disabled=false;return}if(job.status==='failed'){setToast('Ошибка рендера: '+(job.message||'unknown'),'err');renderBtn.disabled=false;return}window.setTimeout(function(){pollJob(jobId)},1500)}).catch(function(error){setToast('Ошибка статуса: '+error.message,'err');renderBtn.disabled=false})}function renderPackage(pack){const images=Array.isArray(pack.images)?pack.images:[];packageStatus.className='toast '+(pack.status==='ready'?'ok':pack.status==='failed'?'err':'warn');packageStatus.textContent=pack.message||pack.status;packageImages.innerHTML=images.length?images.map(function(img){return '<img src="'+esc(img.url)+'" alt="'+esc(img.alt_text_uk||'TELONYX Cinema image')+'">'}).join(''):'<div class="toast warn">Картинки ещё генерируются или не найдены.</div>';telegramPost.innerHTML=esc(pack.telegram_text_uk||'');tiktokPost.innerHTML=esc((pack.tiktok_title||'')+'\n\n'+(pack.tiktok_description||'')+'\n\n'+hashtags(pack.tiktok_hashtags));youtubePost.innerHTML=esc((pack.youtube_title||'')+'\n\n'+(pack.youtube_description||'')+'\n\n'+hashtags(pack.youtube_hashtags));publishResult.textContent=JSON.stringify(pack.publish_results||pack.generator_meta||{},null,2)}function pollPackage(packageId){fetch('/api/publish-packages/'+packageId,{cache:'no-store'}).then(parseJsonResponse).then(function(pack){renderPackage(pack);if(pack.status==='queued'||pack.status==='generating')window.setTimeout(function(){pollPackage(packageId)},1500)}).catch(function(error){packageStatus.className='toast err';packageStatus.textContent='Ошибка пакета: '+error.message})}function startRender(){refreshPreview();if(!videoInput.files||!videoInput.files.length){setToast('Выбери видеофайл.','err');return}if(!movieTitle.value.trim()){setToast('Введи название фильма.','err');return}if(!movieYear.value.trim()){setToast('Введи год выхода.','err');return}download.style.display='none';generateBtn.style.display='none';publishBox.style.display='none';renderBtn.disabled=true;setToast('Загружаю файл и запускаю рендер...','warn');setProgress(3);fetch('/api/jobs',{method:'POST',body:new FormData(form)}).then(parseJsonResponse).then(function(result){setToast('Задача создана: '+result.job_id,'ok');pollJob(result.job_id)}).catch(function(error){setToast('Ошибка старта: '+error.message,'err');renderBtn.disabled=false})}function startGenerate(){if(!currentJobId)return;publishBox.style.display='block';packageStatus.className='toast warn';packageStatus.textContent='Запускаю генерацию контент-пакета...';fetch('/api/jobs/'+currentJobId+'/generate-package',{method:'POST'}).then(parseJsonResponse).then(function(result){currentPackageId=result.package_id;pollPackage(result.package_id)}).catch(function(error){packageStatus.className='toast err';packageStatus.textContent='Ошибка генерации: '+error.message})}function startTelegramPublish(){if(!currentPackageId)return;publishResult.textContent='PUBLISHING_TELEGRAM...';fetch('/api/publish-packages/'+currentPackageId+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({targets:['telegram']})}).then(parseJsonResponse).then(function(result){publishResult.textContent=JSON.stringify(result,null,2);pollPackage(currentPackageId)}).catch(function(error){publishResult.textContent='ERROR: '+error.message})}form.addEventListener('submit',function(event){event.preventDefault();return false});renderBtn.addEventListener('click',startRender);generateBtn.addEventListener('click',startGenerate);publishTelegram.addEventListener('click',startTelegramPublish);movieTitle.addEventListener('input',refreshPreview);movieYear.addEventListener('input',refreshPreview);refreshPreview()})();</script></body></html>
"""


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
    return FileResponse(output, media_type="video/mp4", filename=f"txc_{job_id}_vertical.mp4")
