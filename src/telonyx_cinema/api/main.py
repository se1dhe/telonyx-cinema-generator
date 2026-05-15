from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from telonyx_cinema.api.routes import create_job_handler, download_handler, get_job_handler
from telonyx_cinema.api.web_ui import render_home_page

app = FastAPI(title='TELONYX Cinema Generator', version='0.1.0')


@app.get('/')
def index():
    return HTMLResponse(render_home_page())


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'api'}


app.post('/api/jobs')(create_job_handler)
app.get('/api/jobs/{job_id}')(get_job_handler)
app.get('/api/jobs/{job_id}/download')(download_handler)
