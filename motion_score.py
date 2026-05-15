import cv2
import numpy as np


def score_motion(video_path: str, start: float, duration: float) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(start * fps)
    end_frame = int((start + duration) * fps)
    step = max(int(fps / 4), 1)

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    previous = None
    scores = []
    frame_index = start_frame

    while frame_index < end_frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if previous is not None:
            diff = cv2.absdiff(previous, gray)
            value = float(np.mean(diff))
            scores.append(value)

        previous = gray
        frame_index += step

    cap.release()

    if not scores:
        return 0.0

    return float(np.mean(scores))
