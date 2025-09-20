
import streamlit as st
from datetime import date
from sqlalchemy import select
from db import init_db, SessionLocal, Customer, Loan, Payment, AuditLog, User, verify_password
from services import loan_quota_flat, build_schedule, loan_totals, delinquency, loan_state_with_threshold, global_stats, monthly_interest_due, add_audit, compute_priority, compute_score, has_active_promise, get_active_loans_by_customer, has_active_visible_loan
from utils import round2, periods_in_month
import os
from pdfs import gen_payment_receipt_pdf, gen_statement_pdf
import pandas as pd

engine, SessionLocal = init_db()
st.set_page_config(page_title="ARGSOJA", page_icon="💼", layout="wide")

# --- Autenticación ---
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

def do_logout():
    st.session_state["auth_user"] = None

with st.sidebar:
    st.title("ARGSOJA")
    if st.session_state["auth_user"]:
        st.success(f"Conectado: {st.session_state['auth_user']}")
        if st.button("Cerrar sesión"):
            do_logout()

if not st.session_state["auth_user"]:
    st.title("Iniciar sesión")
    st.caption("Ingresa con tus credenciales")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar"):
        if verify_password(u, p):
            st.session_state["auth_user"] = u
            st.experimental_rerun()
        else:
            st.error("Credenciales inválidas")
    st.stop()

# --- Navegación ---
page = st.sidebar.radio("Navegación", ["Dashboard", "Clientes", "Préstamos", "Pagos", "Reportes", "Estadísticas"])

# --- CSS ---

st.markdown("""

<style>
:root {
  --bg: #f6f7fb;
  --card: #ffffff;
  --border: #e5e7eb;
  --muted: #6b7280;
  --ok-bg:#ecfdf5; --ok-b:#86efac; --ok-t:#065f46;      /* verde */
  --warn-bg:#fffbeb; --warn-b:#fcd34d; --warn-t:#92400e; /* amarillo */
  --danger-bg:#fef2f2; --danger-b:#fca5a5; --danger-t:#991b1b; /* rojo */
  --today-bg:#fde2e4; --today-b:#f8b4b8; --today-t:#7a1e26;    /* rosa suave */
  --info-bg:#eef2ff; --info-b:#c7d2fe; --info-t:#3730a3;
}
.app { background: var(--bg); }
.block { background: var(--card); border:1px solid var(--border); border-radius:16px; padding:16px; box-shadow: 0 1px 6px rgba(16,24,40,.06); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }
.card { background: var(--card); border:1px solid var(--border); border-radius:16px; padding:14px; box-shadow: 0 1px 6px rgba(16,24,40,.06); }
.card h4 { margin:0 0 6px 0; }
.card small { color: var(--muted); }
.pill { display:inline-flex; align-items:center; gap:8px; padding:4px 10px; border-radius:999px; border:1px solid; font-size:12px; font-weight:700; letter-spacing:.2px; }
.pill.ok { background:var(--ok-bg); border-color:var(--ok-b); color:var(--ok-t); }
.pill.warn { background:var(--warn-bg); border-color:var(--warn-b); color:var(--warn-t); }
.pill.danger { background:var(--danger-bg); border-color:var(--danger-b); color:var(--danger-t); }
.pill.today { background:var(--today-bg); border-color:var(--today-b); color:var(--today-t); }
.pill.info { background:var(--info-bg); border-color:var(--info-b); color:var(--info-t); }
.kpi { font-size:22px; font-weight:800; }
.muted { color: var(--muted); }
table.state-table td { padding:6px 10px; }
</style>

""", unsafe_allow_html=True)






def state_chip(state: str) -> str:
    s = (state or "").lower().strip()
    if "vencido" in s:
        label, cls = "Vencido", "danger"
    elif "por vencer" in s:
        label, cls = "Por vencer", "warn"
    elif "vigente" in s or "al día" in s or "al dia" in s:
        label, cls = "Vigente", "ok"
    elif "pagado" in s:
        label, cls = "Pagado", "ok"
    else:
        label, cls = (state or "Estado"), "info"
    return f'<span class="pill {cls}">{label}</span>'



def get_session():
    return SessionLocal()

# --- Dashboard ---
if page == "Dashboard":
    st.header("📊 Dashboard")

    colf1, colf2, colf3, colf4 = st.columns(4)
    with colf1:
        upcoming_days = st.slider("Días para 'pago próximo'", min_value=1, max_value=14, value=3)
    with colf2:
        only_visible = st.checkbox("Sólo visibles en cartera", value=True)
    with colf3:
        only_mora = st.checkbox("Sólo con mora", value=False)
    with colf4:
        hide_pagados = st.checkbox("Ocultar pagados", value=True)

    with get_session() as db:
        rows, agg = global_stats(db, include_pagados=not hide_pagados, exclude_renovados=True, only_visible=only_visible, upcoming_days=upcoming_days)
        collectors = sorted({r["Collector"] for r in rows if r["Collector"]})
        zones = sorted({r["Zone"] for r in rows if r["Zone"]})
        
        if collectors or zones:
            colsel1, colsel2 = st.columns(2)
            with colsel1:
                sel_coll = st.multiselect("Cobrador", collectors or [], default=[])
            with colsel2:
                sel_zone = st.multiselect("Zona", zones or [], default=[])
        else:
            sel_coll, sel_zone = [], []


        def row_pass(r):
            if sel_coll and r["Collector"] not in sel_coll: return False
            if sel_zone and r["Zone"] not in sel_zone: return False
            if only_mora and r["Mora"] <= 0: return False
            return True

        rows_f = [r for r in rows if row_pass(r)]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total préstamos", len(rows_f))
        c2.metric("Saldo cartera", f"${sum(r['Saldo'] for r in rows_f):,.2f}")
        c3.metric("En mora", f"${sum(r['Mora'] for r in rows_f):,.2f}")
        c4.metric("Al día", f"${max(sum(r['Saldo'] for r in rows_f) - sum(r['Mora'] for r in rows_f), 0):,.2f}")

        st.subheader("Detalle rápido (filtrado)")
        with get_session() as db2:
            # Alertas de promesa
            from datetime import date as _d, timedelta as _td
            today = _d.today()
            prom_hoy = [r for r in rows_f if db2.get(Loan, r["Prestamo"]).promesa_pago == today]
            prom_man = [r for r in rows_f if db2.get(Loan, r["Prestamo"]).promesa_pago == today + _td(days=1)]
            prom_venc = [r for r in rows_f if db2.get(Loan, r["Prestamo"]).promesa_pago and db2.get(Loan, r["Prestamo"]).promesa_pago < today and r["Mora"]>0]
            if prom_venc: st.error(f"Promesas vencidas: {len(prom_venc)}")
            if prom_hoy: st.warning(f"Promesas para hoy: {len(prom_hoy)}")
            if prom_man: st.info(f"Promesas para mañana: {len(prom_man)}")

            # Ranking
            st.subheader("Ranking de gestión (Top 20)")
            ranked = []
            for r in rows_f:
                loan = db2.get(Loan, r["Prestamo"])
                d = delinquency(db2, loan)
                score = compute_score(r["Saldo"], d["days_late"], has_active_promise(loan))
                ranked.append((score, loan, d))
            ranked.sort(key=lambda x: x[0], reverse=True)
            for score, loan, d in ranked[:20]:
                st.write(f"**Score {score:.1f}** — #{loan.id} {loan.customer.name} | Saldo ${loan_totals(db2,loan)['balance']:,.2f} | Días mora {d['days_late']} | Promesa: {loan.promesa_pago or '-'}")

# --- Clientes ---
if page == "Clientes":
    st.header("👤 Clientes")
    with get_session() as db:
        tab1, tab2 = st.tabs(["Listado", "Nuevo/Editar"])
        with tab1:
            q = st.text_input("Buscar por nombre, documento, teléfono, dirección, zona o barrio")
            customers = db.execute(select(Customer)).scalars().all()
            if q:
                ql = q.lower()
                def match(c):
                    return any(ql in (getattr(c, f, "") or "").lower() for f in ["name","document","phone","address","zone","neighborhood","notes"])
                customers = [c for c in customers if match(c)]
            st.markdown('<div class="grid">', unsafe_allow_html=True)
            for c in customers:
                st.markdown(f'''
                <div class="card">
                  <h4>{c.name}</h4>
                  <small>Doc: {c.document or '-'} | Tel: {c.phone or '-'} | Zona: {c.zone or '-'} | Barrio: {c.neighborhood or '-'}</small>
                  <div>Dirección: {c.address or '-'}</div>
                  <div>Notas: {c.notes or '-'}</div>
                </div>
                ''', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        with tab2:
            mode = st.selectbox("Acción", ["Crear", "Editar"])
            allc = db.execute(select(Customer)).scalars().all()
            sel = st.selectbox("Selecciona cliente", allc, format_func=lambda x: f"#{x.id} {x.name}") if (mode=="Editar" and allc) else None
            name = st.text_input("Nombre", value=(sel.name if sel else ""))
            document = st.text_input("Documento", value=(sel.document if sel else ""))
            phone = st.text_input("Teléfono", value=(sel.phone if sel else ""))
            address = st.text_input("Dirección", value=(sel.address if sel else ""))
            zone = st.text_input("Zona", value=(sel.zone if sel else ""))
            neighborhood = st.text_input("Barrio", value=(sel.neighborhood if sel else ""))
            notes = st.text_area("Notas", value=(sel.notes if sel else ""), key="cust_notes")
            if st.button("Guardar"):
                if mode == "Crear":
                    c = Customer(name=name, document=document, phone=phone, address=address, zone=zone or None, neighborhood=neighborhood or None, notes=notes)
                    db.add(c); db.commit(); st.success("Cliente creado")
                else:
                    if sel:
                        sel.name, sel.document, sel.phone, sel.address, sel.zone, sel.neighborhood, sel.notes = name, document, phone, address, (zone or None), (neighborhood or None), notes
                        db.commit(); st.success("Cliente actualizado")
                    else:
                        st.error("Selecciona un cliente para editar.")

# --- Préstamos ---
if page == "Préstamos":
    st.header("💰 Préstamos")
    with get_session() as db:
        tab1, tab2, tab3, tab4 = st.tabs(["Listado", "Crear", "Cronograma", "Gestionar/Editar"])
        with tab1:
            loans = db.execute(select(Loan)).scalars().all()
            by_c = {}
            for l in loans:
                by_c.setdefault(l.customer_id, []).append(l)
            for cid, arr in by_c.items():
                cust = arr[0].customer
                st.markdown(f"### {cust.name} — Doc: `{cust.document or '-'}`")
                activos, historico = [], []
                for l in arr:
                    visible = getattr(l,"visible",1)==1
                    if getattr(l,"status","")=="renovado" or not visible or loan_state_with_threshold(db,l)=="pagado":
                        historico.append(l)
                    else:
                        activos.append(l)
                st.write("**Activos**" if activos else "_Sin préstamos activos_")
                for l in activos:
                    tot = loan_totals(db, l)
                    st.markdown(f'- #{l.id} | Monto: ${l.principal:,.2f} | Frec: {l.frequency} | Cuota: ${tot["quota_periodica"]:,.2f} | Saldo: ${tot["balance"]:,.2f} | Estado: {state_chip(loan_state_with_threshold(db,l))}', unsafe_allow_html=True)
                with st.expander("Histórico"):
                    for l in historico:
                        tot = loan_totals(db, l)
                        st.caption(f"- #{l.id} | {l.status} | Saldo: ${tot['balance']:,.2f}")
        with tab2:
            customers = db.execute(select(Customer)).scalars().all()
            if not customers:
                st.warning("Primero crea un cliente en la pestaña Clientes.")
            else:
                cust = st.selectbox("Cliente", customers, format_func=lambda x: f"#{x.id} {x.name}")
                principal = st.number_input("Monto (principal)", min_value=0.0, step=100.0)
                im = st.number_input("Interés mensual (0.2 = 20%)", min_value=0.0, max_value=5.0, step=0.01, value=0.2, key="create_rate")
                term_months = st.number_input("Plazo (meses)", min_value=1, step=1, value=1, key="create_term")
                start = st.date_input("Fecha inicio", value=date.today(), key="create_start")
                freq = st.selectbox("Frecuencia", ["diaria", "semanal", "quincenal", "mensual"], key="create_freq")
                nper = periods_in_month(freq) * int(term_months)
                st.caption(f"Número total de cuotas: {nper}")
                collector = st.text_input("Cobrador (opcional)", key="create_collector")
                notes = st.text_area("Notas", value="", key="edit_notes")
                if st.button("Crear préstamo"):
                    if has_active_visible_loan(db, cust.id):
                        st.error("Este cliente ya tiene un préstamo activo/visible. Cierra o renueva antes de crear otro.")
                    else:
                        l = Loan(customer_id=cust.id, principal=principal, monthly_rate=im, term_months=int(term_months), start_date=start, n_periods=int(nper), frequency=freq, collector=collector or None, notes=notes or None)
                        db.add(l); db.commit(); st.success(f"Préstamo #{l.id} creado")
                if principal:
                    from types import SimpleNamespace
                    preview = SimpleNamespace(principal=principal, monthly_rate=im, term_months=int(term_months), frequency=freq, start_date=start)
                    st.info(f"Cuota por periodo (flat): ${loan_quota_flat(preview):.2f}")
        with tab3:
            loans = db.execute(select(Loan)).scalars().all()
            if not loans:
                st.warning("No hay préstamos para mostrar.")
            else:
                sel = st.selectbox("Préstamo", loans, format_func=lambda x: f"#{x.id} {x.customer.name}")
                if sel:
                    rows = build_schedule(sel)
                    st.write(f"Cuota por periodo (flat): ${loan_quota_flat(sel):,.2f}")
                    st.dataframe([{**r, "date": r["date"].isoformat()} for r in rows], use_container_width=True)
                    totals = loan_totals(db, sel)
                    if st.button("Generar Estado de Cuenta (PDF)"):
                        out = os.path.join(f"estado_cuenta_loan_{sel.id}.pdf")
                        try:
                            gen_statement_pdf(out, sel, sel.customer, rows, totals)
                            with open(out, "rb") as fh:
                                st.download_button("⬇️ Descargar Estado de Cuenta PDF", fh.read(), file_name=os.path.basename(out), mime="application/pdf")
                        except Exception as e:
                            st.caption(f"No se pudo generar PDF: {e}")
        with tab4:
            loans_all = db.execute(select(Loan)).scalars().all()
            if not loans_all:
                st.info("No hay préstamos para gestionar.")
            else:
                sel = st.selectbox("Selecciona préstamo", loans_all, format_func=lambda x: f"#{x.id} {x.customer.name}")
                if sel:
                    vis = st.checkbox("Visible en cartera", value=bool(getattr(sel, "visible", 1)==1))
                    prom = st.date_input("Promesa de pago", value=getattr(sel, "promesa_pago", None))
                    p_override = st.selectbox("Prioridad", ["Auto","Alta","Media","Baja"], index=0)
                    
                    st.markdown("#### Campos financieros")
                    colf1, colf2 = st.columns(2)
                    with colf1:
                        principal = st.number_input("Principal", key=f"edit_principal_{sel.id}", min_value=0.0, step=100.0, value=float(sel.principal))
                        monthly_rate = st.number_input("Interés mensual (0.2 = 20%)", key=f"edit_rate_{sel.id}", min_value=0.0, max_value=5.0, step=0.01, value=float(sel.monthly_rate))
                        term_months = st.number_input("Plazo (meses)", key=f"edit_term_{sel.id}", min_value=1, step=1, value=int(sel.term_months))
                    with colf2:
                        start_date = st.date_input("Fecha inicio", key=f"edit_start_{sel.id}", value=sel.start_date)
                        freq = st.selectbox("Frecuencia", ["diaria","semanal","quincenal","mensual"], key=f"edit_freq_{sel.id}", index=["diaria","semanal","quincenal","mensual"].index(sel.frequency))
                        collector = st.text_input("Cobrador (opcional)", key=f"edit_collector_{sel.id}", value=sel.collector or "")
                        notes = st.text_area("Notas", key=f"edit_notes_{sel.id}", value=sel.notes or "")
                    st.caption("Al cambiar frecuencia o plazo se recalcula el total de cuotas (n_periods).")
                    if st.button("💾 Guardar cambios del crédito"):
                        from utils import periods_in_month
                        sel.principal = principal
                        sel.monthly_rate = monthly_rate
                        sel.term_months = int(term_months)
                        sel.start_date = start_date
                        sel.frequency = freq
                        sel.collector = collector or None
                        sel.notes = notes or None
                        sel.n_periods = periods_in_month(freq) * int(term_months)
                        db.commit()
                        st.success("Cambios del crédito guardados.")
                    st.markdown("---")
                    if st.button("Guardar cambios de gestión"):
                        sel.visible = 1 if vis else 0
                        sel.promesa_pago = prom
                        sel.priority = None if p_override=="Auto" else p_override
                        db.commit()
                        st.success("Cambios de gestión guardados.")
                    st.subheader("Auditoría (últimos 200 eventos)")
                    logs = db.execute(select(AuditLog).order_by(AuditLog.ts.desc())).scalars().all()[:200]
                    if logs:
                        st.table([{"Fecha": str(l.ts), "Préstamo": l.loan_id, "Acción": l.action, "Info": l.info} for l in logs])
                    else:
                        st.info("Sin eventos aún.")

# --- Pagos ---
if page == "Pagos":
    st.header("💵 Pagos")
    with get_session() as db:
        customers = db.execute(select(Customer)).scalars().all()
        if not customers:
            st.warning("No hay clientes. Crea uno primero."); st.stop()
        colsel1, colsel2 = st.columns([2,1])
        with colsel1:
            sel_customer = st.selectbox("Cliente", customers, format_func=lambda x: f"{x.name} — {x.document or '-'}")
        with colsel2:
            doc_query = st.text_input("Buscar por documento")
            if doc_query:
                match = [c for c in customers if (c.document or "") == doc_query]
                if match: sel_customer = match[0]
        active_loans = get_active_loans_by_customer(db, sel_customer.id) if sel_customer else []

    tab1, tab2 = st.tabs(["Registrar pago", "Historial"])

    with tab1:
        with get_session() as db:
            dest_loan = active_loans[0] if active_loans else None
            if dest_loan is None:
                st.warning("El cliente no tiene préstamo activo/visible. Puedes elegir uno histórico (no recomendado).")
                loans_all = db.execute(select(Loan).where(Loan.customer_id==sel_customer.id)).scalars().all()
                dest_loan = st.selectbox("Seleccionar préstamo (histórico)", loans_all, format_func=lambda x: f"#{x.id} — {x.start_date} — {x.status}") if loans_all else None
            else:
                st.caption(f"Pago se aplicará a: Préstamo #{dest_loan.id} (activo)")

            pay_date = st.date_input("Fecha pago", value=date.today())
            amount = st.number_input("Monto", min_value=0.0, step=10.0)
            method = st.selectbox("Método", ["efectivo", "transferencia", "intereses", "otro"])
            note = st.text_input("Nota", "")
            if st.button("Guardar pago"):
                if dest_loan is None:
                    st.error("No hay préstamo destino para aplicar el pago.")
                else:
                    p = Payment(loan_id=dest_loan.id, date=pay_date, amount=amount, method=method, note=note or None, customer_id=sel_customer.id)
                    db.add(p); db.commit()
                    add_audit(db, "pago", dest_loan.id, info=f"Pago {p.id} por ${p.amount:,.2f} (cliente {sel_customer.id})")
                    st.success("Pago registrado")
                    out = os.path.join("recibo_pago_%d.pdf" % p.id)
                    try:
                        gen_payment_receipt_pdf(out, p, dest_loan, sel_customer)
                        with open(out, "rb") as fh:
                            st.download_button("⬇️ Descargar recibo PDF", fh.read(), file_name=os.path.basename(out), mime="application/pdf")
                    except Exception as e:
                        st.caption(f"No se pudo generar PDF: {e}")

            st.divider()
            st.subheader("Renovar con pago solo intereses")
            mi = monthly_interest_due(dest_loan) if dest_loan else 0.0
            st.caption(f"Interés de un mes: ${mi:,.2f}. Registrar y **renovar**: se marca el préstamo actual como renovado/oculto y se crea uno nuevo con misma configuración, iniciando hoy.")
            close_with_adjust = st.checkbox("Cerrar con ajuste contable (recomendado)", value=True, help="Crea un movimiento 'ajuste_renovación' para dejar el saldo del préstamo viejo en 0 sin contarlo como cobro.")
            if st.button("Pago solo intereses (renovar)"):
                if dest_loan is None:
                    st.error("No hay préstamo activo para renovar.")
                else:
                    p2 = Payment(loan_id=dest_loan.id, date=date.today(), amount=mi, method="intereses", note="Pago solo intereses (renovación)", customer_id=sel_customer.id)
                    db.add(p2)
                    dest_loan.status = "renovado"; dest_loan.visible = 0
                    from services import loan_totals
                    if close_with_adjust:
                        t_tot = loan_totals(db, dest_loan)
                        if t_tot["balance"] > 0:
                            p_adj = Payment(loan_id=dest_loan.id, date=date.today(), amount=t_tot["balance"], method="ajuste_renovación", note=f"Cierre por renovación #{dest_loan.id}", customer_id=sel_customer.id)
                            db.add(p_adj)
                    nper = periods_in_month(dest_loan.frequency) * int(dest_loan.term_months)
                    new_loan = Loan(customer_id=dest_loan.customer_id, principal=dest_loan.principal, monthly_rate=dest_loan.monthly_rate, term_months=dest_loan.term_months, start_date=date.today(), n_periods=int(nper), frequency=dest_loan.frequency, collector=dest_loan.collector, notes=(dest_loan.notes or "") + f" | Renovado desde #{dest_loan.id}")
                    db.add(new_loan); db.commit()
                    add_audit(db, "renovar", dest_loan.id, info=f"Renovación a #{new_loan.id} por ${mi:,.2f}")
                    add_audit(db, "crear", new_loan.id, info=f"Creado por renovación desde #{dest_loan.id}")
                    st.success(f"Renovado: se registró pago de intereses ${mi:,.2f}, se cerró el saldo del préstamo viejo {'(con ajuste)' if close_with_adjust else ''} y se creó el préstamo #{new_loan.id} con fecha {date.today().isoformat()}.")

    with tab2:
        with get_session() as db:
            loans_ids = [l.id for l in db.execute(select(Loan).where(Loan.customer_id==sel_customer.id)).scalars().all()]
            pays = db.execute(select(Payment).where(Payment.loan_id.in_(loans_ids)).order_by(Payment.date.desc())).scalars().all()
            st.table([{"Fecha": p.date.isoformat(), "Monto": f"${p.amount:,.2f}", "Método": p.method, "Nota": p.note or "", "Préstamo": p.loan_id} for p in pays])
            if pays:
                sel_pay = st.selectbox("Generar recibo para:", pays, format_func=lambda x: f"Pago #{x.id} — {x.date.isoformat()} — ${x.amount:,.2f}")
                if st.button("Generar recibo PDF"):
                    loan_map = {l.id: l for l in db.execute(select(Loan).where(Loan.customer_id==sel_customer.id)).scalars().all()}
                    loan_sel = loan_map.get(sel_pay.loan_id)
                    if loan_sel:
                        out = os.path.join(f"recibo_pago_{sel_pay.id}.pdf")
                        try:
                            gen_payment_receipt_pdf(out, sel_pay, loan_sel, sel_customer)
                            with open(out, "rb") as fh:
                                st.download_button("⬇️ Descargar recibo PDF (seleccionado)", fh.read(), file_name=os.path.basename(out), mime="application/pdf")
                        except Exception as e:
                            st.caption(f"No se pudo generar PDF: {e}")

# --- Reportes ---
if page == "Reportes":
    st.header("📑 Reportes")
    include_pagados_r = st.checkbox("Incluir pagados", value=True)
    exclude_renovados_r = st.checkbox("Excluir renovados", value=True)
    with get_session() as db:
        loans_all = db.execute(select(Loan)).scalars().all()
        loans = []
        for l in loans_all:
            if exclude_renovados_r and getattr(l, "status", "")=="renovado": continue
            loans.append(l)
        rows = []
        for l in loans:
            t = loan_totals(db, l); d = delinquency(db, l)
            state = loan_state_with_threshold(db, l)
            if not include_pagados_r and state=="pagado": continue
            rows.append({"Prestamo": l.id,"Cliente": l.customer.name,"Doc": l.customer.document or "","Frecuencia": l.frequency,"Cuota": t["quota_periodica"],"Saldo": t["balance"],"Mora ($)": d["overdue_amount"],"Días en mora (exactos)": d["days_late"],"Próximo pago": d["next_due"].isoformat() if d["next_due"] else "","Estado": state,"Cobrador": l.collector or "","Inicio": l.start_date.isoformat(),"Estatus interno": getattr(l,"status","")})
        
df = pd.DataFrame(rows)
if not df.empty:
    df2 = df.copy()
    from html import escape as _esc
    headers = df2.columns.tolist()
    # Generar tabla HTML con filas coloreadas por estado
    html = '<table class="state-table" style="width:100%;border-collapse:collapse">'
    html += '<thead><tr>' + ''.join([f'<th style="text-align:left;padding:8px;border-bottom:1px solid #eee;">{_esc(str(h))}</th>' for h in headers]) + '</tr></thead><tbody>'
    for _, row in df2.iterrows():
        stt = str(row.get("Estado","")).lower()
        if "vencido" in stt:
            bg = "#ffe5e5"
        elif "por vencer" in stt or "vence hoy" in stt:
            bg = "#fff4cc"
        elif "vigente" in stt or "pagado" in stt or "al día" in stt or "al dia" in stt:
            bg = "#e8f5e9"
        else:
            bg = "#ffffff"
        tds = []
        for h in headers:
            val = row[h]
            if h == "Estado":
                val_html = state_chip(str(val))
            elif h in ["Saldo","Mora ($)","Cuota"]:
                try:
                    val_html = f"${float(val):,.2f}"
                except Exception:
                    val_html = _esc(str(val))
            else:
                val_html = _esc(str(val))
            tds.append(f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{val_html}</td>')
        html += f'<tr style="background:{bg}">' + ''.join(tds) + '</tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
else:
    st.info("Sin datos para mostrar.")


