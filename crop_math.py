def crop_x_expr(source_width: int, source_height: int, center_x: float) -> int:
    crop_width = int(source_height * 9 / 16)
    if crop_width > source_width:
        return 0
    x = int(center_x - crop_width / 2)
    if x < 0:
        return 0
    max_x = source_width - crop_width
    if x > max_x:
        return max_x
    return x
