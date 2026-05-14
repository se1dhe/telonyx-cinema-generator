from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from api_jobs import create_job_handler, download_handler, get_job_handler

app = FastAPI(title='TELONYX Cinema Generator')

HTML = '''
<h1>TELONYX Cinema Generator</h1>
<form action="/api/jobs" method="post" enctype="multipart/form-data">
  <p>Video: <input type="file" name="video" required></p>
  <p>Music: <input type="file" name="music"></p>
  <p>Focus: <input name="focus_prompt" value="Darth Vader"></p>
  <p>Seconds: <input type="number" name="target_seconds" value="30"></p>
  <button>Create vertical edit</button>
</form>
<p>Health: <a href="/api/health">/api/health</a></p>
'''

@app.get('/')
def index():
    return HTMLResponse(HTML)

@app.get('/api/health')
def health():
    return {'status': 'ok'}

app.post('/api/jobs')(create_job_handler)
app.get('/api/jobs/{job_id}')(get_job_handler)
app.get('/api/jobs/{job_id}/download')(download_handler)
