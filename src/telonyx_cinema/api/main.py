from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from telonyx_cinema.api.diagnostics import diagnostics_handler
from telonyx_cinema.api.routes import create_job_handler, download_handler, get_job_handler, timeline_handler
from telonyx_cinema.api.web_ui import UI_VERSION, render_home_page

app = FastAPI(title='TELONYX Cinema Generator', version='0.1.0')


@app.get('/')
def index():
    response = HTMLResponse(render_home_page())
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Telonyx-UI-Version'] = UI_VERSION
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'api'}


@app.get('/api/version')
def version():
    return {'service': 'api', 'ui_version': UI_VERSION}


app.get('/api/diagnostics')(diagnostics_handler)
app.post('/api/jobs')(create_job_handler)
app.get('/api/jobs/{job_id}')(get_job_handler)
app.get('/api/jobs/{job_id}/timeline')(timeline_handler)
app.get('/api/jobs/{job_id}/download')(download_handler)
