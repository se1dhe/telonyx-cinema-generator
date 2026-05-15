import os
import subprocess
from pathlib import Path

from model_config import COMPUTE_TYPE, ENABLE_WHISPER, MODEL_DEVICE, WHISPER_MODEL
from subtitle_builder import write_placeholder_ass


def extract_wav(video_path: str, wav_path: str) -> None:
    process = subprocess.run(
        ['ffmpeg', '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', wav_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def escape_ass(text: str) -> str:
    return text.replace('{', '').replace('}', '').replace('\n', ' ').strip()


def write_ass(path: str, segments: list[dict]) -> None:
    header = '''[Script Info]
Title: TELONYX Whisper Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,58,&H00FFFFFF,&H00101010,&H99000000,-1,0,0,0,100,100,0,0,1,4,2,2,80,80,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines = [header]
    for item in segments:
        text = escape_ass(item.get('text', ''))
        if not text:
            continue
        lines.append(f"Dialogue: 0,{format_time(float(item['start']))},{format_time(float(item['end']))},Main,,0,0,0,,{text}\n")
    Path(path).write_text(''.join(lines), encoding='utf-8')


def build_subtitles(video_path: str, output_ass: str, fallback_title: str = 'TELONYX CINEMA') -> str:
    if not ENABLE_WHISPER:
        write_placeholder_ass(output_ass, fallback_title)
        return output_ass

    try:
        from faster_whisper import WhisperModel
    except Exception:
        write_placeholder_ass(output_ass, fallback_title)
        return output_ass

    work_dir = Path(output_ass).parent
    wav_path = str(work_dir / 'speech.wav')
    extract_wav(video_path, wav_path)

    model = WhisperModel(WHISPER_MODEL, device=MODEL_DEVICE, compute_type=COMPUTE_TYPE)
    segments, _ = model.transcribe(wav_path, vad_filter=True)
    data = []
    for segment in segments:
        data.append({'start': float(segment.start), 'end': float(segment.end), 'text': segment.text})

    if not data:
        write_placeholder_ass(output_ass, fallback_title)
    else:
        write_ass(output_ass, data)

    try:
        os.remove(wav_path)
    except OSError:
        pass
    return output_ass
