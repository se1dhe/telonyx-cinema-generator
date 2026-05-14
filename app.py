from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title='TELONYX Cinema Generator')

@app.get('/')
def index():
    return HTMLResponse('<h1>TELONYX Cinema Generator</h1><p>API online</p>')

@app.get('/api/health')
def health():
    return {'status': 'ok'}
