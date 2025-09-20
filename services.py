from datetime import date, datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from db import Loan, Payment, Customer, AuditLog
from utils import next_date, periods_in_month, round2

def periods_total(loan: Loan) -> int:
    return periods_in_month(loan.frequency) * max(loan.term_months, 1)

def total_interest(loan: Loan) -> float:
    return round2(loan.principal * loan.monthly_rate * max(loan.term_months, 1))

def loan_quota_flat(loan: Loan) -> float:
    n = periods_total(loan)
    return round2((loan.principal + total_interest(loan)) / n) if n>0 else 0.0

def build_schedule(loan: Loan) -> List[Dict[str, Any]]:
    n = periods_total(loan)
    if n<=0: return []
    total_int = total_interest(loan)
    int_per = round2(total_int / n)
    cap_per = round2(loan.principal / n)
    from utils import next_date
    d = loan.start_date
    bal = loan.principal
    out = []
    for k in range(1, n+1):
        principal_pay = cap_per if k < n else round2(bal)
        interest = int_per if k < n else round2(total_int - int_per*(n-1))
        bal = round2(bal - principal_pay)
        out.append({"n":k,"date":d,"quota":round2(principal_pay+interest),"interest":interest,"principal":principal_pay,"capital_pendiente":bal})
        d = next_date(loan.frequency, d)
    return out

def paid_amount(session: Session, loan: Loan) -> float:
    return session.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(Payment.loan_id==loan.id, Payment.method!="ajuste_renovación").scalar() or 0.0

def loan_totals(session: Session, loan: Loan) -> Dict[str, float]:
    sched = build_schedule(loan)
    total_due = sum(r["quota"] for r in sched)
    paid = paid_amount(session, loan)
    balance = round2(max(total_due - paid, 0.0))
    return {"quota_periodica": loan_quota_flat(loan), "paid": round2(paid), "total_due": round2(total_due), "balance": balance}

def delinquency(session: Session, loan: Loan, today: date = None) -> Dict[str, Any]:
    if today is None: today = date.today()
    sched = build_schedule(loan)
    expected_due = sum(r["quota"] for r in sched if r["date"] <= today)
    paid = paid_amount(session, loan)
    overdue_amount = round2(max(expected_due - paid, 0.0))
    last_due_date = None
    cum = 0.0
    for r in sched:
        cum += r["quota"]
        if cum > paid:
            last_due_date = r["date"]
            break
    days_late = (today - last_due_date).days if last_due_date and overdue_amount > 0 else 0
    next_due_date = None
    cum2 = 0.0
    for r in sched:
        cum2 += r["quota"]
        if cum2 > paid and r["date"] > today:
            next_due_date = r["date"]
            break
    days_until_next = (next_due_date - today).days if next_due_date else None
    return {"overdue_amount": overdue_amount, "days_late": days_late, "next_due": next_due_date, "days_until_next": days_until_next}

def loan_state_with_threshold(session: Session, loan: Loan, upcoming_days: int = 3, today: date = None) -> str:
    t = loan_totals(session, loan)
    if t["balance"] <= 0.005: return "pagado"
    d = delinquency(session, loan, today=today)
    if getattr(loan, "promesa_pago", None):
        if d["overdue_amount"] > 0 and (today or date.today()) <= loan.promesa_pago:
            return "promesa de pago"
    if d["overdue_amount"] > 0:
        return "mora 30+" if d["days_late"] >= 30 else "mora 1-29"
    if d["days_until_next"] is not None and 0 <= d["days_until_next"] <= upcoming_days:
        return "pago próximo"
    return "pagado al día"

def global_stats(session: Session, include_pagados: bool = False, exclude_renovados: bool = True, only_visible: bool = True, upcoming_days: int = 3):
    from sqlalchemy import select
    loans = session.execute(select(Loan)).scalars().all()
    rows = []
    estados_conteo = {}
    estados_saldo = {}
    total_cartera = 0.0
    total_mora = 0.0
    for l in loans:
        if only_visible and getattr(l, "visible", 1)==0: continue
        if exclude_renovados and getattr(l, "status", "")=="renovado": continue
        state = loan_state_with_threshold(session, l, upcoming_days=upcoming_days)
        if not include_pagados and state=="pagado": continue
        t = loan_totals(session, l)
        d = delinquency(session, l)
        rows.append({"Prestamo": l.id,"Cliente": l.customer.name,"Estado": state,"Saldo": t["balance"],"Mora": d["overdue_amount"],"DiasMora": d["days_late"],"Collector": l.collector or "","Zone": getattr(l.customer,"zone","") or ""})
        total_cartera += t["balance"]; total_mora += d["overdue_amount"]
        estados_conteo[state] = estados_conteo.get(state,0)+1
        estados_saldo[state] = estados_saldo.get(state,0.0)+t["balance"]
    total_dia = max(total_cartera - total_mora, 0.0)
    buckets = {"1-7":0,"8-15":0,"16-30":0,"30+":0}; buckets_saldo={"1-7":0.0,"8-15":0.0,"16-30":0.0,"30+":0.0}
    for r in rows:
        dm = r["DiasMora"]
        if dm<=0: continue
        b = "1-7" if dm<=7 else "8-15" if dm<=15 else "16-30" if dm<=30 else "30+"
        buckets[b]+=1
        buckets_saldo[b]+= r["Mora"]
    agg = {"saldo_cartera": round2(total_cartera),"en_mora": round2(total_mora),"al_dia": round2(total_dia),"conteos": estados_conteo,"saldos_por_estado": {k:round2(v) for k,v in estados_saldo.items()},"aging_conteo": buckets,"aging_saldo": {k:round2(v) for k,v in buckets_saldo.items()}}
    return rows, agg

def monthly_interest_due(loan: Loan) -> float:
    return round2(loan.principal * loan.monthly_rate)

def add_audit(session: Session, action: str, loan_id: int, info: str = ""):
    try:
        session.add(AuditLog(loan_id=loan_id, action=action, info=info, ts=datetime.utcnow()))
        session.commit()
    except Exception:
        session.rollback()

def compute_priority(balance: float, days_late: int) -> str:
    if days_late >= 30 or balance >= 1_000_000: return "Alta"
    if days_late >= 8 or balance >= 300_000: return "Media"
    return "Baja"

def compute_score(balance: float, days_late: int, has_promise: bool) -> float:
    return float(days_late) * 2.0 + (balance / 100000.0) + (5.0 if has_promise else 0.0)

def has_active_promise(loan: Loan, today=None) -> bool:
    if getattr(loan, "promesa_pago", None) is None: return False
    from datetime import date as _d
    if today is None: today = _d.today()
    return loan.promesa_pago >= today

def get_active_loans_by_customer(session: Session, customer_id: int):
    from sqlalchemy import select
    loans = session.execute(select(Loan).where(Loan.customer_id==customer_id)).scalars().all()
    active = []
    for l in loans:
        if getattr(l,"status","")=="renovado" or getattr(l,"visible",1)==0: continue
        if loan_state_with_threshold(session,l) != "pagado": active.append(l)
    active.sort(key=lambda x: x.start_date, reverse=True)
    return active

def has_active_visible_loan(session: Session, customer_id: int) -> bool:
    return len(get_active_loans_by_customer(session, customer_id))>0
