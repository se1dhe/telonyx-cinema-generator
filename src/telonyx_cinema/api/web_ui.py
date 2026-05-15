def render_home_page() -> str:
    return '''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TELONYX Cinema Generator</title>
  <style>
    :root { color-scheme: dark; }
    body { margin:0; background: radial-gradient(circle at top,#1b1430 0,#06070b 44%,#03040a 100%); color:#f4f4f5; font-family: Inter, Arial, sans-serif; }
    .wrap { max-width:1120px; margin:0 auto; padding:48px 20px; }
    .hero { display:grid; grid-template-columns:1.1fr .9fr; gap:24px; align-items:stretch; }
    .card { background:rgba(13,15,23,.86); border:1px solid rgba(255,255,255,.1); border-radius:28px; padding:28px; box-shadow:0 24px 90px rgba(0,0,0,.45); backdrop-filter: blur(18px); }
    .badge { display:inline-flex; padding:8px 12px; border-radius:999px; background:rgba(139,92,246,.16); border:1px solid rgba(139,92,246,.35); color:#c4b5fd; font-weight:700; font-size:13px; }
    h1 { font-size:54px; line-height:.95; margin:18px 0 14px; letter-spacing:-.05em; }
    p { color:#a1a1aa; font-size:16px; line-height:1.65; }
    label { display:block; margin-top:15px; color:#d4d4d8; font-weight:700; font-size:13px; }
    input, select { width:100%; box-sizing:border-box; margin-top:8px; padding:13px 14px; border-radius:14px; border:1px solid rgba(255,255,255,.1); background:#090a10; color:#fff; outline:none; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .checks { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:14px; }
    .check { display:flex; align-items:center; gap:10px; padding:12px; border-radius:16px; background:#090a10; border:1px solid rgba(255,255,255,.09); color:#e4e4e7; font-size:14px; }
    .check input { width:auto; margin:0; }
    button { width:100%; margin-top:20px; padding:16px; border:0; border-radius:18px; background:linear-gradient(135deg,#8b5cf6,#06b6d4); color:white; font-weight:900; font-size:16px; cursor:pointer; }
    pre { white-space:pre-wrap; min-height:210px; background:#090a10; border:1px solid rgba(255,255,255,.08); border-radius:18px; padding:16px; color:#d4d4d8; overflow:auto; }
    .stat { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:18px; }
    .stat div { padding:14px; border-radius:18px; background:#090a10; border:1px solid rgba(255,255,255,.08); }
    .stat b { display:block; font-size:22px; }
    .hint { color:#71717a; font-size:12px; margin-top:8px; }
    @media(max-width:900px){ .hero{grid-template-columns:1fr;} h1{font-size:42px;} }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <section class="card">
        <span class="badge">Premium AI post-production</span>
        <h1>Черновик фильма → beat-synced vertical edit</h1>
        <p>Preset-based монтаж: xfade/filter_complex, speed ramp, impact zoom/shake, музыкальные пики, intro/dialogue/action режимы и debug timeline.</p>
        <div class="stat"><div><b>9:16</b><span>1080x1920</span></div><div><b>AI</b><span>YOLO + OpenCV</span></div><div><b>FX</b><span>xfade + speed ramp</span></div></div>
      </section>
      <section class="card">
        <form id="form">
          <label>Черновое видео<input type="file" name="video" accept="video/*" required></label>
          <label>Музыка<input type="file" name="music" accept="audio/*"></label>
          <div class="grid">
            <label>Персонаж / фокус<input name="focus_prompt" placeholder="Дарт Вейдер"></label>
            <label>Длительность<input type="number" name="target_seconds" value="30" min="5" max="180"></label>
            <label>Premium Preset<select name="edit_preset"><option value="cinematic" selected>Cinematic</option><option value="aggressive">Aggressive</option><option value="sad">Sad / Loneliness</option><option value="cyberpunk">Cyberpunk</option></select></label>
            <label>Mode<select name="edit_mode"><option value="action" selected>Action Cut</option><option value="intro">Intro + Action</option><option value="dialogue">Dialogue Intro + Action</option></select></label>
            <label>Старт музыки, сек<input type="number" name="music_start_seconds" value="0" min="0" max="600" step="0.1"></label>
            <label>Beat Sync<select name="beat_sync"><option value="soft">Soft</option><option value="strict" selected>Strict</option><option value="off">Off</option></select></label>
            <label>Платформа<select name="platform"><option value="shorts">YouTube Shorts</option><option value="tiktok">TikTok</option><option value="reels">Reels</option></select></label>
            <label>Язык субтитров<select name="subtitle_language"><option value="auto">Auto</option><option value="ru">Русский</option><option value="en">English</option><option value="uk">Українська</option></select></label>
            <label>Цвет<select name="color_preset"><option value="dark_cinema">Dark Cinema</option><option value="cyberpunk_neon">Cyberpunk Neon</option><option value="vader_red">Vader Red</option><option value="drive_night">Drive Night</option><option value="neutral">Neutral</option></select></label>
            <label>Переходы<select name="transition_style"><option value="glitch">Glitch</option><option value="flash">Flash</option><option value="whip">Whip</option><option value="tape">Tape</option><option value="hard_cut">Hard Cut</option></select></label>
            <label>Интенсивность эффектов<select name="effect_intensity"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option><option value="none">None</option></select></label>
            <label>Стиль субтитров<select name="subtitle_style"><option value="cinematic">Cinematic</option><option value="dialogue">Dialogue</option><option value="aggressive">Aggressive</option><option value="minimal">Minimal</option></select></label>
          </div>
          <div class="checks">
            <label class="check"><input type="checkbox" name="subtitle_enabled"> Субтитры</label>
            <label class="check"><input type="checkbox" name="color_enabled" checked> Цветокор</label>
            <label class="check"><input type="checkbox" name="transitions_enabled" checked> Xfade/переходы</label>
            <label class="check"><input type="checkbox" name="centering_enabled" checked> Центрирование</label>
            <label class="check"><input type="checkbox" name="effects_enabled" checked> Эффекты</label>
          </div>
          <p class="hint">Для premium cuts ставь старт музыки на дроп. Aggressive/Cyberpunk лучше с Glitch + Strict. Sad лучше с Tape + Soft.</p>
          <button type="submit">Создать premium edit</button>
        </form>
      </section>
    </div>
    <section class="card" style="margin-top:24px"><h3>Статус задачи</h3><pre id="out">Готов к загрузке.</pre></section>
  </div>
<script>
const form=document.getElementById('form');
const out=document.getElementById('out');
form.onsubmit=async(e)=>{e.preventDefault();out.textContent='Загрузка файлов...';const fd=new FormData(form);const r=await fetch('/api/jobs',{method:'POST',body:fd});const j=await r.json();out.textContent=JSON.stringify(j,null,2);if(j.job_id){const timer=setInterval(async()=>{const s=await fetch('/api/jobs/'+j.job_id);const x=await s.json();out.textContent=JSON.stringify(x,null,2);if(x.status==='done'||x.status==='failed'){clearInterval(timer);}},2500);}};
</script>
</body>
</html>'''
