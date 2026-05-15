from pathlib import Path


def write_placeholder_ass(path: str, title: str = 'TELONYX CINEMA') -> None:
    clean_title = title.replace('{', '').replace('}', '').strip() or 'TELONYX CINEMA'
    content = f'''[Script Info]
Title: TELONYX Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,64,&H00FFFFFF,&H00101010,&H99000000,-1,0,0,0,100,100,0,0,1,4,2,2,80,80,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.20,0:00:02.40,Main,,0,0,0,,{clean_title}
'''
    Path(path).write_text(content, encoding='utf-8')
