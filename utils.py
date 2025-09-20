from datetime import date, timedelta

def round2(x: float) -> float:
    return float(f"{x:.2f}")

def periods_in_month(freq: str) -> int:
    return {"diaria": 30, "semanal": 4, "quincenal": 2, "mensual": 1}.get(freq, 30)

def next_date(freq: str, d: date) -> date:
    if freq == "diaria":
        return d + timedelta(days=1)
    if freq == "semanal":
        return d + timedelta(days=7)
    if freq == "quincenal":
        return d + timedelta(days=15)
    return add_month(d, 1)

def add_month(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31,29 if y%4==0 and (y%100!=0 or y%400==0) else 28,31,30,31,30,31,31,30,31,30,31][m-1])
    return date(y, m, day)
