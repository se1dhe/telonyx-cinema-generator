def build_video_filter(enable_color: bool = True) -> str:
    base = 'scale=-2:1920,crop=1080:1920'
    if enable_color:
        return base + ',eq=contrast=1.12:saturation=1.08:brightness=-0.015,unsharp=5:5:0.8:3:3:0.4'
    return base
