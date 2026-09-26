def judge(cyan_mm: float, magenta_mm: float, tolerance_mm: float) -> tuple[str, str]:
    if abs(cyan_mm) <= tolerance_mm and abs(magenta_mm) <= tolerance_mm:
        return "套准", f"青品两色偏差绝对值都不大于允差 {tolerance_mm:g} 毫米"
    return "套不准", f"至少一色偏差超出允差 {tolerance_mm:g} 毫米"
