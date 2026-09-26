def judge(cyan_mm: float, magenta_mm: float, tolerance_mm: float) -> tuple[str, str]:
    """按领取瞬间记下的允差判定：青品偏差绝对值都不大于允差才套准。"""
    tol = abs(tolerance_mm)
    if abs(cyan_mm) <= tol and abs(magenta_mm) <= tol:
        return "套准", f"青品两色偏差都在允差 {tol:g} 毫米内"
    return "套不准", f"至少一色偏差超出允差 {tol:g} 毫米"
