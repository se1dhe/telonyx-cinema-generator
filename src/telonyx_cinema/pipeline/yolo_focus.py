from functools import lru_cache

import cv2

from telonyx_cinema.config.model_config import ENABLE_YOLO, YOLO_MODEL


@lru_cache(maxsize=1)
def get_model():
    if not ENABLE_YOLO:
        return None
    try:
        from ultralytics import YOLO
        return YOLO(YOLO_MODEL)
    except Exception:
        return None


def detect_yolo_center(video_path: str, start: float, duration: float) -> tuple[float, float] | None:
    model = get_model()
    if model is None:
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_index = int((start + duration / 2.0) * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None

    result = model.predict(source=frame, conf=0.35, verbose=False)[0]
    if result.boxes is None or len(result.boxes) == 0:
        return None

    best = None
    for box in result.boxes:
        cls_id = int(box.cls[0].item())
        if cls_id not in (0, 2, 3, 5, 7):
            continue
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
        area = max(1.0, (x2 - x1) * (y2 - y1))
        if best is None or area > best[0]:
            best = (area, x1, y1, x2, y2)

    if best is None:
        return None

    _, x1, y1, x2, y2 = best
    return (float((x1 + x2) / 2.0), float((y1 + y2) / 2.0))
