# AI Models

## Local first

- YOLO: object detection and action centering.
- MediaPipe or RetinaFace: face detection and face centering.
- CLIP or SigLIP: prompt based frame ranking.
- PySceneDetect: scene boundary detection.
- faster-whisper: speech transcription.
- WhisperX: word level subtitle alignment.
- librosa: beat detection.
- RIFE: frame interpolation.
- Real-ESRGAN: upscaling.

## Optional external providers

- Runway: image to video, text to video, character consistency, generated b-roll.
- Pika: social effects, image animation, object edits, sound effects.
- Kling: cinematic image to video and realistic motion.
- Luma: atmospheric b-roll and camera motion.
- Adobe Firefly: commercially safer generative video and editing.

## Railway note

CPU Railway workers are enough for MVP FFmpeg, scene detection and light object detection. Heavy models should be moved to a separate GPU worker or external provider adapter.
