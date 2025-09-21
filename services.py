from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from db import Loan, Payment

def periods_in_month(freq: str) -> int:
    return {"diaria":30, "semanal":4, "quincenal":2, "mensual":1}.get(freq, 1)

def periods_total(loan: Loan) -> int:
    return max(1, periods_in_month(loan.frequency) * max(int(loan.term_months), 1))


def build_schedule(loan: Loan):
    """
    Genera las fechas de vencimiento. La primera cuota vence *después* del start_date
    (no el mismo día). Ej.: mensual -> start + 1 mes; semanal -> start + 1 semana; diaria -> start + 1 día.
    """
    n = periods_total(loan)
    freq = loan.frequency
    start = loan.start_date
    step = {"diaria": ("days",1), "semanal": ("weeks",1), "quincenal": ("days",15), "mensual": ("months",1)}.get(freq, ("months",1))
    dates = []
    cur = start
    for i in range(n):
        # siempre avanzar primero
        if step[0]=="days":
            cur = cur + timedelta(days=step[1])
        elif step[0]=="weeks":
            cur = cur + timedelta(weeks=step[1])
        else:
            cur = cur + relativedelta(months=step[1])
        dates.append(cur)
    return dates


def loan_totals(session: Session, loan: Loan):
    total_interes = loan.principal * loan.monthly_rate * loan.term_months
    total = loan.principal + total_interes
    n = periods_total(loan)
    cuota = total / n
    paid = session.execute(select(func.coalesce(func.sum(Payment.amount),0.0)).where(Payment.loan_id==loan.id)).scalar() or 0.0
    balance = max(0.0, total - paid)
    return {"principal": loan.principal, "interes_total": total_interes, "total": total, "quota_periodica": cuota, "paid": paid, "balance": balance}


def delinquency(session: Session, loan: Loan, today: date=None):
    if today is None:
        today = date.today()
    sched = build_schedule(loan)
    t = loan_totals(session, loan)
    cuota = t["quota_periodica"]
    expected_paid = 0.0
    last_due = None
    next_due = None
    for d in sched:
        if d < today:  # solo vencimientos estrictamente anteriores a hoy generan exigibilidad
            expected_paid += cuota
            last_due = d
        elif next_due is None:
            next_due = d
    paid = t["paid"]
    overdue_amount = max(0.0, expected_paid - paid)
    days_late = (today - last_due).days if overdue_amount>0 and last_due else 0
    days_until_next = (next_due - today).days if next_due else None
    return {"overdue_amount": overdue_amount, "days_late": days_late, "days_until_next": days_until_next, "next_due": next_due, "last_due": last_due}


def loan_state_with_threshold(session: Session, loan: Loan, upcoming_days:int=3, today:date=None)->str:
    t = loan_totals(session, loan)
    if t["balance"] <= 0.005:
        return "pagado"
    d = delinquency(session, loan, today=today)
    if d["overdue_amount"] > 0:
        return "vencido"
    if d["days_until_next"] is not None and d["days_until_next"] <= max(upcoming_days,0):
        return "por vencer"
    return "vigente"