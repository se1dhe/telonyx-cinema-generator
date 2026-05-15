import os

ENABLE_YOLO = os.getenv('ENABLE_YOLO', 'true').lower() == 'true'
ENABLE_WHISPER = os.getenv('ENABLE_WHISPER', 'false').lower() == 'true'
ENABLE_BEAT_DETECT = os.getenv('ENABLE_BEAT_DETECT', 'true').lower() == 'true'
ENABLE_CLIP = os.getenv('ENABLE_CLIP', 'false').lower() == 'true'

YOLO_MODEL = os.getenv('YOLO_MODEL', 'yolov8n.pt')
WHISPER_MODEL = os.getenv('WHISPER_MODEL', 'small')

MODEL_DEVICE = os.getenv('MODEL_DEVICE', 'cpu')
COMPUTE_TYPE = os.getenv('COMPUTE_TYPE', 'int8')
