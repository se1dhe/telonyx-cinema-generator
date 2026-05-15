import cv2

from yolo_focus import detect_yolo_center


def detect_focus_center(video_path: str, start: float, duration: float) -> tuple[float, float] | None:
    yolo_center = detect_yolo_center(video_path, start, duration)
    if yolo_center is not None:
        return yolo_center

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

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return (width / 2.0, height / 2.0)

    contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(contour)
    if w * h < width * height * 0.01:
        return (width / 2.0, height / 2.0)

    return (float(x + w / 2.0), float(y + h / 2.0))
