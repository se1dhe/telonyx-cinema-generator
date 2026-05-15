# TELONYX Cinema Generator - Project Structure

## Target layout

```text
telonyx-cinema-generator/
├── src/
│   └── telonyx_cinema/
│       ├── api/
│       │   ├── main.py
│       │   ├── routes.py
│       │   └── web_ui.py
│       ├── worker/
│       │   ├── main.py
│       │   └── tasks.py
│       ├── pipeline/
│       │   ├── beat_detector.py
│       │   ├── color_presets.py
│       │   ├── concat_builder.py
│       │   ├── crop_math.py
│       │   ├── focus_detector.py
│       │   ├── motion_score.py
│       │   ├── scene_analyzer.py
│       │   ├── smart_filters.py
│       │   ├── subtitle_builder.py
│       │   ├── video_probe.py
│       │   ├── whisper_subtitles.py
│       │   └── yolo_focus.py
│       ├── config/
│       │   ├── model_config.py
│       │   └── render_options.py
│       └── __init__.py
├── railway/
│   ├── api.toml
│   └── worker.toml
├── scripts/
│   └── local_dev.sh
├── docs/
│   ├── AI_MODELS.md
│   ├── FEATURES.md
│   ├── PRODUCT_SPEC.md
│   └── ROADMAP.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── .env.example
```

## Service boundaries

### API service

Responsible for:

- web UI;
- upload rough video;
- upload music track;
- collect render options;
- create render job in Redis;
- return job status;
- return final MP4 download.

Start command:

```bash
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port $PORT
```

### Worker service

Responsible for:

- picking RQ jobs from Redis;
- scene analysis;
- motion scoring;
- local model analysis;
- smart crop;
- beat detection;
- subtitles;
- color grade;
- final FFmpeg render.

Start command:

```bash
python -m telonyx_cinema.worker.main
```

## Railway resources

Required:

- API service;
- Worker service;
- Redis;
- persistent volume mounted to `/data/storage`.

Optional later:

- PostgreSQL for users, plans, job history;
- GPU worker for heavy models.
```
