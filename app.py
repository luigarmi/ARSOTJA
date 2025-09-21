import os
import pandas as pd
import streamlit as st
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from db import init_db, SessionLocal, User, Customer, Loan, Payment, verify_password
from services import periods_in_month, periods_total, loan_totals, delinquency, loan_state_with_threshold, build_schedule


# --- Ensure users & session timeout ---
import hashlib, time
def _hash_password(pw: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()
    return f"sha256${salt}${h}"

def _upsert_user(username: str, plain_password: str):
    with SessionLocal() as db:
        from sqlalchemy import select
        u = db.execute(select(User).where(User.username==username)).scalar()
        if u:
            # update password only if plain provided (rotate)
            u.password_hash = _hash_password(plain_password)
            db.commit()
        else:
            db.add(User(username=username, password_hash=_hash_password(plain_password)))
            db.commit()

def _apply_session_timeout(minutes=30):
    now = time.time()
    key="last_activity_ts"
    ts = st.session_state.get(key, now)
    if now - ts > minutes*60 and st.session_state.get("auth_user"):
        st.session_state.clear()
        st.toast("⚠️ Sesión cerrada por inactividad")
        st.experimental_rerun()
    st.session_state[key] = now

# --- Utilidades de exportación ---
from io import BytesIO
def export_df_to_excel(df, filename="reporte.xlsx"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reporte")
    output.seek(0)
    return output, filename

def build_payment_receipt_pdf(payment, customer, loan):
    """
    Genera PDF del recibo con número consecutivo (R-000001) y QR (ID del pago).
    """
    try:
        from fpdf import FPDF
        import qrcode
        from io import BytesIO
    except Exception:
        return None, None
    rno = f"R-{int(payment.id):06d}"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "ARGSOJA - Recibo de Pago", ln=True, align="C")
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 8, f"Recibo: {rno}", ln=True)
    pdf.cell(0, 8, f"Fecha: {payment.date}", ln=True)
    pdf.ln(2)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 8, f"Cliente: {customer.name}", ln=True)
    pdf.cell(0, 8, f"Documento: {customer.document or '-'}", ln=True)
    pdf.cell(0, 8, f"Préstamo: #{loan.id}", ln=True)
    pdf.cell(0, 8, f"Monto: ${payment.amount:,.2f}", ln=True)
    if getattr(payment, "method", None):
        pdf.cell(0, 8, f"Método: {payment.method}", ln=True)
    if getattr(payment, "note", None):
        pdf.multi_cell(0, 8, f"Nota: {payment.note}")
    # QR con ID de pago + recibo
    qr = qrcode.QRCode(box_size=2, border=2)
    qr.add_data(f"ARGSOJA|{rno}|PAY:{payment.id}|LOAN:{loan.id}|CUST:{customer.id}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    qr_img.save(bio, format="PNG"); bio.seek(0)
    # Guardar QR temporal en memoria
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(bio.read()); tmp.flush()
        tmp_path = tmp.name
    try:
        pdf.image(tmp_path, x=165, y=20, w=30)
    except Exception:
        pass
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    pdf.ln(10)
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 8, "Gracias por su pago.", ln=True, align="C")
    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        raw = raw.encode("latin1")
    else:
        raw = bytes(raw)
    pdf_out = BytesIO(raw)
    return pdf_out, f"recibo_{rno}.pdf"

engine, SessionLocal = init_db()
# Seed/rotate credentials as requested
_upsert_user('luis_argumedo','Armi2025*')
_upsert_user('elcy_jaramillo','Elcyja0214@')

st.set_page_config(page_title='ARGSOJA', layout='wide', page_icon='assets/logo_argsoja.png')







# ====== Estilos (único punto) ======
def inject_global_css():
    st.markdown("""<style>
      :root{ --brand:#1F3C88; --ring:#2BB673; }
      .stButton > button,
      .stDownloadButton > button,
      .stDownloadButton > a,
      form button[type="submit"],
      .stForm button {
        background: var(--brand) !important;
        color:#fff!important;border:none!important;
        padding:10px 18px!important;border-radius:12px!important;
        font-weight:700!important;
        box-shadow:0 6px 18px rgba(31,60,136,.18)!important;
        transition:transform .12s, box-shadow .12s, filter .12s!important;
      }
      .stButton > button:hover,
      .stDownloadButton > button:hover,
      .stDownloadButton > a:hover,
      form button[type="submit"]:hover,
      .stForm button:hover {
        transform:translateY(-1px)!important;filter:brightness(.98)!important;
        box-shadow:0 10px 22px rgba(31,60,136,.22)!important;
      }
      .stButton > button:active,
      .stDownloadButton > button:active,
      .stDownloadButton > a:active,
      form button[type="submit"]:active,
      .stForm button:active {
        transform:translateY(0)!important;
        box-shadow:0 4px 12px rgba(31,60,136,.14)!important;
      }
      .stButton > button:focus-visible,
      .stDownloadButton > button:focus-visible,
      .stDownloadButton > a:focus-visible,
      form button[type="submit"]:focus-visible,
      .stForm button:focus-visible {
        outline:3px solid var(--ring)!important;outline-offset:2px!important;
      }
      .stButton > button:disabled,
      .stDownloadButton > button:disabled,
      form button[type="submit"]:disabled,
      .stForm button:disabled {
        opacity:1!important;filter:brightness(1)!important;
        background:var(--brand)!important;color:#fff!important;
        box-shadow:none!important;cursor:not-allowed!important;
      }
    </style>""", unsafe_allow_html=True)
# ====== Fin estilos ======

inject_global_css()
def _inject_css_once():
    if st.session_state.get("_css_injected"):
        return
    st.session_state["_css_injected"] = True
    st.markdown("""<style>
      .stButton > button,
      .stDownloadButton > button,
      .stDownloadButton > a,
      form button[type="submit"],
      .stForm button {
        background: var(--brand) !important;
        color: #fff !important;
        border: none !important;
        padding: 10px 18px !important;
        border-radius: 12px !important;
        font-weight: 700 !important;
        box-shadow: 0 6px 18px rgba(31,60,136,.18) !important;
        transition: transform .12s ease, box-shadow .12s ease, filter .12s ease !important;
      }
      .stButton > button:hover,
      .stDownloadButton > button:hover,
      .stDownloadButton > a:hover,
      form button[type="submit"]:hover,
      .stForm button:hover {
        transform: translateY(-1px) !important;
        filter: brightness(.98) !important;
        box-shadow: 0 10px 22px rgba(31,60,136,.22) !important;
      }
      .stButton > button:active,
      .stDownloadButton > button:active,
      .stDownloadButton > a:active,
      form button[type="submit"]:active,
      .stForm button:active {
        transform: translateY(0) !important;
        box-shadow: 0 4px 12px rgba(31,60,136,.14) !important;
      }
      .stButton > button:focus-visible,
      .stDownloadButton > button:focus-visible,
      .stDownloadButton > a:focus-visible,
      form button[type="submit"]:focus-visible,
      .stForm button:focus-visible {
        outline: 3px solid var(--ring) !important;
        outline-offset: 2px !important;
      }
      .stButton > button:disabled,
      .stDownloadButton > button:disabled,
      form button[type="submit"]:disabled,
      .stForm button:disabled {
        opacity: 1 !important;
        filter: brightness(1) !important;
        background: var(--brand) !important;
        color: #fff !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
      }
    </style>""", unsafe_allow_html=True)

_inject_css_once()
# --- Global CSS (unificado de botones) ---
def _inject_css():
    st.markdown("""
    <style>
      .stButton > button:hover,
      .stDownloadButton > button:hover,
      .stDownloadButton > a:hover,
      form button[type="submit"]:hover,
      .stForm button:hover {
        transform: translateY(-1px) !important;
        filter: brightness(.98) !important;
        box-shadow: 0 10px 22px rgba(31,60,136,.22) !important;
      }
      .stButton > button:active,
      .stDownloadButton > button:active,
      .stDownloadButton > a:active,
      form button[type="submit"]:active,
      .stForm button:active {
        transform: translateY(0) !important;
        box-shadow: 0 4px 12px rgba(31,60,136,.14) !important;
      }
      .stButton > button:focus-visible,
      .stDownloadButton > button:focus-visible,
      .stDownloadButton > a:focus-visible,
      form button[type="submit"]:focus-visible,
      .stForm button:focus-visible {
        outline: 3px solid var(--ring) !important;
        outline-offset: 2px !important;
      }
      .stButton > button:disabled,
      .stDownloadButton > button:disabled,
      form button[type="submit"]:disabled,
      .stForm button:disabled {
        opacity: 1 !important;
        filter: brightness(1) !important;
        background: var(--brand) !important;
        color: #fff !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
      }
    </style>
    """, unsafe_allow_html=True)

_inject_css()
st.markdown("""
<style>
:root {
  --bg: #f6f7fb; --card:#fff; --border:#e5e7eb; --muted:#6b7280;
  --ok-bg:#ecfdf5; --ok-b:#86efac; --ok-t:#065f46;
  --warn-bg:#fffbeb; --warn-b:#fcd34d; --warn-t:#92400e;
  --danger-bg:#fef2f2; --danger-b:#fca5a5; --danger-t:#991b1b;
}
.block { background: var(--card); border:1px solid var(--border); border-radius:16px; padding:16px; box-shadow: 0 1px 6px rgba(16,24,40,.06); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }
.pill { display:inline-flex; align-items:center; gap:8px; padding:4px 10px; border-radius:999px; border:1px solid; font-size:12px; font-weight:700; letter-spacing:.2px; }
.pill.ok { background:var(--ok-bg); border-color:var(--ok-b); color:var(--ok-t); }
.pill.warn { background:var(--warn-bg); border-color:var(--warn-b); color:var(--warn-t); }
.pill.danger { background:var(--danger-bg); border-color:var(--danger-b); color:var(--danger-t); }
.kpi { font-size:22px; font-weight:800; }
.state-table td, .state-table th { padding:6px 10px; }
</style>


<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&family=Open+Sans:wght@400;600&display=swap');
:root {
  --brand:#1F3C88; /* azul */
  --accent:#2BB673; /* verde */
  --muted:#6b7280;
  --surface:#FFFFFF;
  --bg:#F2F2F2;
  --warn:#F9B234;
  --danger:#EF4444;
}
html, body, [class*="css"] { font-family: 'Open Sans', sans-serif; }
h1,h2,h3 { font-family: 'Montserrat', sans-serif; color: var(--brand); letter-spacing:.3px; }


.block { background: var(--surface); border:1px solid #e5e7eb; border-radius:16px; padding:16px; box-shadow: 0 1px 6px rgba(16,24,40,.06); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
.pill { display:inline-flex; align-items:center; gap:8px; padding:4px 10px; border-radius:999px; border:1px solid; font-size:12px; font-weight:700; letter-spacing:.2px; }
.pill.ok { background:#e8f8f0; border-color:#b8efd2; color:#0b5a37; }       /* verde */
.pill.warn { background:#fff5e6; border-color:#fde1a8; color:#8a5800; }     /* amarillo */
.pill.danger { background:#ffe5e5; border-color:#f3b4b4; color:#9a1a1a; }   /* rojo */
.kpi { font-size:22px; font-weight:800; color:#0f172a; }
.muted { color:var(--muted); font-size:12px; }
</style>

<style>
:root { --brand:#ef4444; --text:#0f172a; }
h1, h2, h3 { color: var(--text); letter-spacing:.3px; }


.stSelectbox>div>div>div { border-radius:12px !important; }
.stNumberInput input, .stTextInput input, .stTextArea textarea { border-radius:12px !important; }
.card { background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:14px 16px; box-shadow:0 1px 6px rgba(16,24,40,.06); }
.kpi { font-size:22px; font-weight:800; }
.muted { color:#6b7280; font-size:12px; }
</style>

<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&family=Open+Sans:wght@400;600&display=swap');
:root {
  --brand:#1F3C88; /* azul */
  --accent:#2BB673; /* verde */
  --muted:#6b7280;
  --surface:#FFFFFF;
  --bg:#F2F2F2;
  --warn:#F9B234;
  --danger:#EF4444;
}
html, body, [class*="css"] { font-family: 'Open Sans', sans-serif; }
h1,h2,h3 { font-family: 'Montserrat', sans-serif; color: var(--brand); letter-spacing:.3px; }


.block { background: var(--surface); border:1px solid #e5e7eb; border-radius:16px; padding:16px; box-shadow: 0 1px 6px rgba(16,24,40,.06); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
.pill { display:inline-flex; align-items:center; gap:8px; padding:4px 10px; border-radius:999px; border:1px solid; font-size:12px; font-weight:700; letter-spacing:.2px; }
.pill.ok { background:#e8f8f0; border-color:#b8efd2; color:#0b5a37; }       /* verde */
.pill.warn { background:#fff5e6; border-color:#fde1a8; color:#8a5800; }     /* amarillo */
.pill.danger { background:#ffe5e5; border-color:#f3b4b4; color:#9a1a1a; }   /* rojo */
.kpi { font-size:22px; font-weight:800; color:#0f172a; }
.muted { color:var(--muted); font-size:12px; }
</style>
""", unsafe_allow_html=True)

def state_chip(state: str) -> str:
    s = (state or "").lower()
    if "vencido" in s: return '<span class="pill danger">Vencido</span>'
    if "por vencer" in s: return '<span class="pill warn">Por vencer</span>'
    if "vigente" in s: return '<span class="pill ok">Vigente</span>'
    if "pagado" in s: return '<span class="pill ok">Pagado</span>'
    return f'<span class="pill">{state}</span>'

if "user" not in st.session_state:
    st.session_state.user = None

def login_box():
    st.title("ARGSOJA")
    st.subheader("Inicia sesión")
    u = st.text_input("Usuario", key="login_user")
    p = st.text_input("Contraseña", type="password", key="login_pass")
    if st.button("Entrar", type="primary"):
        with SessionLocal() as s:
            from sqlalchemy import select
            rec = s.execute(select(User).where(User.username==u)).scalar()
            if rec and verify_password(p, rec.password_hash):
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Credenciales inválidas.")
    
if not st.session_state.user:
    login_box()
    st.stop()

with st.sidebar:
    st.image('assets/logo_argsoja.png', width=160)
    st.caption('**Tu confianza, nuestro respaldo**')

    st.success(f"Conectado: {st.session_state.user}")
    if st.button("Cerrar sesión"):
        st.session_state.user = None; st.rerun()
    page = st.radio("Navegación", ["Dashboard","Clientes","Préstamos","Pagos","Reportes","Estadísticas"])

def ensure_seed():
    with SessionLocal() as s:
        from sqlalchemy import select, func
        has = s.execute(select(func.count(Customer.id))).scalar()
        if has and has>0: return
        seed = [
            ("ANGELA HERNANDEZ",   "mensual", 800000, None),
            ("LUCIA MULASCO",      "mensual", 400000, None),
            ("MIRIAM CIFUENTES",   "mensual", 440000, None),
            ("ANA MILENA FABRA",   "mensual", 250000, None),
            ("CARMELO S",          "mensual", 600000, None),
            ("YULY DIAZ BONILLA",  "mensual", 200000, None),
            ("DANIEL HERNANDEZ",   "mensual", 600000, None),
            ("ROBERTO ARBELAEZ M", "mensual", 200000, None),
            ("JOSE N VELEZ",       "mensual", 300000, None),
            ("JORGE ARGUMEDO",     "mensual", 1000000, None),
            ("JAVIER GARCIA",      "mensual", 1000000, "10933084"),
        ]
        from datetime import date
        for name, freq, amt, doc in seed:
            c = Customer(name=name, document=doc)
            s.add(c); s.flush()
            l = Loan(customer_id=c.id, principal=amt, monthly_rate=0.2, term_months=1, start_date=date.today(), n_periods=1, frequency=freq)
            s.add(l)
        s.commit()
ensure_seed()

def money(x):
    try: return f"${float(x):,.2f}"
    except: return str(x)



# Dashboard
if page == "Dashboard":
    st.header("Dashboard")
    with SessionLocal() as db:
        loans = db.execute(select(Loan)).scalars().all()
        saldo = vencido = al_dia = por_vencer = 0.0
        for l in loans:
            t = loan_totals(db, l)
            stt = loan_state_with_threshold(db, l, upcoming_days=3)
            saldo += t["balance"]
            if stt=="vencido": vencido += t["balance"]
            elif stt=="por vencer": por_vencer += t["balance"]
            elif stt in ("vigente","pagado"): al_dia += t["balance"]
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="block"><div class="muted">Saldo de cartera</div><div class="kpi">{money(saldo)}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="block"><div class="muted">Vencido</div><div class="kpi">{money(vencido)}</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="block"><div class="muted">Por vencer</div><div class="kpi">{money(por_vencer)}</div></div>', unsafe_allow_html=True)



# Clientes
if page == "Clientes":
    st.header("Clientes")

    # Cargar clientes
    with SessionLocal() as db:
        customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()

    # UI superior: selector + crear nuevo
    left, right = st.columns([3,1])
    labels = [f"{c.id} · {c.name} · doc {c.document or '-'}" for c in customers]
    id_by_label = {labels[i]: customers[i].id for i in range(len(customers))}

    sel_label = left.selectbox("Selecciona un cliente", options=(labels if labels else ["-"]), key="cli_sel")

    if right.button("➕ Nuevo cliente", key="btn_new_customer"):
        st.session_state["new_customer"] = True

    # Form para crear nuevo cliente
    if st.session_state.get("new_customer", False):
        st.subheader("Crear nuevo cliente")
        with st.form("form_new_customer", clear_on_submit=False):
            name  = st.text_input("Nombre completo", key="nc_name")
            doc   = st.text_input("Documento", key="nc_doc")
            phone = st.text_input("Teléfono", key="nc_phone")
            zone  = st.text_input("Zona", key="nc_zone")
            neigh = st.text_input("Barrio", key="nc_neigh")
            addr  = st.text_area("Dirección", key="nc_addr")
            notes = st.text_area("Notas", key="nc_notes")
            submitted = st.form_submit_button("💾 Crear cliente")
        if submitted:
            with SessionLocal() as db:
                c = Customer(name=name.strip(), document=(doc or "").strip() or None,
                             phone=(phone or "").strip() or None, zone=(zone or "").strip() or None,
                             neighborhood=(neigh or "").strip() or None, address=(addr or "").strip() or None,
                             notes=(notes or "").strip() or None)
                db.add(c); db.commit(); new_id = c.id
            st.toast("🆕 Cliente creado")
            # Seleccionar automáticamente el nuevo cliente
            st.session_state["cli_sel"] = f"{new_id} · {name} · doc {doc or '-'}"
            st.session_state["new_customer"] = False
            st.rerun()

    # Si hay clientes y selección válida, mostrar gestión
    if customers and sel_label and sel_label in id_by_label:
        sel_id = id_by_label[sel_label]
        with SessionLocal() as db:
            c = db.get(Customer, sel_id)
            loans = db.execute(select(Loan).where(Loan.customer_id==sel_id, Loan.visible==1).order_by(Loan.id.desc())).scalars().all()
            saldo = 0.0
            for l in loans:
                t = loan_totals(db, l); saldo += t["balance"]

        # Tarjeta del cliente
        st.markdown(f"<div class='block'><div class='muted'>Doc: {c.document or '-'} · Tel: {c.phone or '-'}</div><h3 style='margin:.2rem 0'>{c.name}</h3><div class='muted'>Zona: {c.zone or '-'} · Barrio: {c.neighborhood or '-'}</div></div>", unsafe_allow_html=True)
        k1,k2,k3,k4 = st.columns([1,1,1,1])
        k1.markdown(f"<div class='block'><div class='muted'>Préstamos activos</div><div class='kpi'>{len(loans)}</div></div>", unsafe_allow_html=True)
        k2.markdown(f"<div class='block'><div class='muted'>Saldo</div><div class='kpi'>{money(saldo)}</div></div>", unsafe_allow_html=True)
        k3.markdown(f"<div class='block'><div class='muted'>Zona</div><div class='kpi'>{c.zone or '-'}</div></div>", unsafe_allow_html=True)
        k4.markdown(f"<div class='block'><div class='muted'>Cobrador</div><div class='kpi'>{getattr(c,'collector','-') or '-'}</div></div>", unsafe_allow_html=True)

        # Tabla compacta de préstamos del cliente
        from pandas import DataFrame
        rows=[]
        # Usar UNA sola sesión y pasarla a todas las funciones para evitar Detached/TypeError
        with SessionLocal() as s:
            for l in loans:
                t = loan_totals(s, l)
                d = delinquency(s, l)
                rows.append({
                    'ID': l.id,
                    'Saldo': money(t['balance']),
                    'Próxima': (d['next_due'].strftime('%Y-%m-%d') if d['next_due'] else '-'),
                    'Estado': loan_state_with_threshold(s, l)
                })
        if rows:
            df=DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        # Acciones
        a1,a2,a3 = st.columns(3)
        if a1.button("✏️ Editar", key=f"act_edit_{sel_id}"):
            st.session_state["cli_edit_open"] = True
        if a2.button("➕ Nuevo préstamo", key=f"act_newloan_{sel_id}"):
            st.session_state["cli_newloan_open"] = True
        if a3.button("💵 Registrar pago", key=f"act_pay_{sel_id}"):
            st.session_state["cli_pay_open"] = True

        # Edición
        if st.session_state.get("cli_edit_open"):
            with st.expander("Editar cliente", expanded=True):
                name  = st.text_input("Nombre", value=c.name or "", key=f"ed_name_{sel_id}")
                doc   = st.text_input("Documento", value=c.document or "", key=f"ed_doc_{sel_id}")
                phone = st.text_input("Teléfono", value=c.phone or "", key=f"ed_phone_{sel_id}")
                zone  = st.text_input("Zona", value=c.zone or "", key=f"ed_zone_{sel_id}")
                neigh = st.text_input("Barrio", value=c.neighborhood or "", key=f"ed_nei_{sel_id}")
                addr  = st.text_area("Dirección", value=c.address or "", key=f"ed_addr_{sel_id}")
                notes = st.text_area("Notas", value=c.notes or "", key=f"ed_notes_{sel_id}")
                if st.button("💾 Guardar cambios", key=f"ed_save_{sel_id}"):
                    with SessionLocal() as db:
                        cc = db.get(Customer, sel_id)
                        cc.name, cc.document, cc.phone = name, doc, phone
                        cc.zone, cc.neighborhood, cc.address, cc.notes = zone, neigh, addr, notes
                        db.commit()
                    st.toast("✅ Cliente actualizado")
                    st.session_state["cli_edit_open"] = False
                    st.rerun()

        # Nuevo préstamo
        if st.session_state.get("cli_newloan_open"):
            with st.expander("Crear nuevo préstamo", expanded=True):
                principal = st.number_input("Capital", min_value=0.0, step=100.0, key=f"nl_cap_{sel_id}")
                rate      = st.number_input("Interés mensual (0.2 = 20%)", min_value=0.0, step=0.01, key=f"nl_rate_{sel_id}")
                term      = st.number_input("Plazo (meses)", min_value=1, step=1, value=1, key=f"nl_term_{sel_id}")
                freq      = st.selectbox("Frecuencia", ["DIARIO","SEMANAL","QUINCENAL","MENSUAL"], key=f"nl_freq_{sel_id}")
                if st.button("📝 Crear", key=f"nl_go_{sel_id}"):
                    with SessionLocal() as db:
                        l = Loan(customer_id=sel_id, principal=principal, monthly_rate=rate, term_months=term, start_date=date.today(),
                                 n_periods=periods_in_month(freq)*int(term), frequency=freq, collector=None, notes=None)
                        db.add(l); db.commit()
                    st.toast("🆕 Préstamo creado")
                    st.session_state["cli_newloan_open"] = False
                    st.rerun()

        # Registrar pago
        if st.session_state.get("cli_pay_open"):
            with st.expander("Registrar pago", expanded=True):
                with SessionLocal() as db:
                    loans = db.execute(select(Loan).where(Loan.customer_id==sel_id, Loan.visible==1)).scalars().all()
                    labels2, map2 = [], {}
                    for l in loans:
                        t = loan_totals(db, l); d = delinquency(db, l)
                        nxt = d["next_due"].strftime("%Y-%m-%d") if d["next_due"] else "-"
                        lab = f"{l.id} · saldo {money(t['balance'])} · vence {nxt}"
                        labels2.append(lab); map2[lab] = l.id
                if labels2:
                    sel2 = st.selectbox("Préstamo", labels2, key=f"qp_sel_{sel_id}")
                    amt  = st.number_input("Monto", min_value=0.0, step=100.0, key=f"qp_amt_{sel_id}")
                    mtd  = st.selectbox("Método", ["efectivo","transferencia","otro"], key=f"qp_mtd_{sel_id}")
                    note = st.text_input("Nota", key=f"qp_note_{sel_id}")
                    if st.button("💾 Registrar", key=f"qp_go_{sel_id}"):
                        with SessionLocal() as db:
                            lid = map2[sel2]
                            l = db.get(Loan, lid)
                            db.add(Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(), amount=amt, method=mtd or None, note=note or None))
                            db.commit()
                        st.toast("💰 Pago registrado")
                        st.session_state["cli_pay_open"] = False
                        st.rerun()
                else:
                    st.info("Este cliente no tiene préstamos activos.")
# Préstamos
if page == "Préstamos":
    st.header("Préstamos")
    with SessionLocal() as db:
        loans = db.execute(select(Loan).options(joinedload(Loan.customer)).order_by(Loan.id.desc())).scalars().all()
        loan_opts = [f"{l.id} - {l.customer.name if l.customer else '-'}" for l in loans]
    tab1, tab2, tab3 = st.tabs(["Crear","Gestionar/Editar","Cronograma"])

    with tab1:
        with SessionLocal() as db:
            customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
        cust = st.selectbox("Cliente", options=[f"{c.id} - {c.name}" for c in customers], key="create_loan_customer")
        principal = st.number_input("Principal", min_value=0.0, step=100.0, key="create_principal")
        rate = st.number_input("Interés mensual (0.2 = 20%)", min_value=0.0, max_value=5.0, step=0.01, value=0.2, key="create_rate")
        term = st.number_input("Plazo (meses)", min_value=1, step=1, value=1, key="create_term")
        start = st.date_input("Fecha inicio", value=date.today(), key="create_start")
        freq = st.selectbox("Frecuencia", ["diaria","semanal","quincenal","mensual"], key="create_freq")
        collector = st.text_input("Cobrador (opcional)", key="create_coll")
        notes = st.text_area("Notas", value="", key="create_notes")
        if st.button("Crear préstamo", type="primary"):
            with SessionLocal() as db:
                cid = int(cust.split(" - ")[0])
                l = Loan(customer_id=cid, principal=principal, monthly_rate=rate, term_months=int(term), start_date=start,
                         n_periods=periods_in_month(freq)*int(term), frequency=freq, collector=collector or None, notes=notes or None)
                db.add(l); db.commit()
                st.success("Préstamo creado."); st.rerun()

    with tab2:
        if loans:
            sel = st.selectbox("Selecciona un préstamo", options=loan_opts, key="edit_loan_sel")
            cur = next(l for l in loans if f"{l.id} - {l.customer.name}"==sel)
            with SessionLocal() as db:
                l = db.get(Loan, cur.id)
                st.write(f"Cliente: **{l.customer.name}**")
                c1,c2 = st.columns(2)
                with c1:
                    principal = st.number_input("Principal", min_value=0.0, step=100.0, value=float(l.principal), key=f"edit_p_{l.id}")
                    rate = st.number_input("Interés mensual (0.2 = 20%)", min_value=0.0, max_value=5.0, step=0.01, value=float(l.monthly_rate), key=f"edit_r_{l.id}")
                    term = st.number_input("Plazo (meses)", min_value=1, step=1, value=int(l.term_months), key=f"edit_t_{l.id}")
                with c2:
                    start = st.date_input("Fecha inicio", value=l.start_date, key=f"edit_start_{l.id}")
                    freq = st.selectbox("Frecuencia", ["diaria","semanal","quincenal","mensual"], index=["diaria","semanal","quincenal","mensual"].index(l.frequency), key=f"edit_f_{l.id}")
                    collector = st.text_input("Cobrador (opcional)", value=l.collector or "", key=f"edit_c_{l.id}")
                notes = st.text_area("Notas", value=l.notes or "", key=f"edit_n_{l.id}")
                if st.button("Guardar cambios del préstamo", key=f"btn_save_{l.id}"):
                    l.principal = principal; l.monthly_rate = rate; l.term_months = int(term)
                    l.start_date = start; l.frequency = freq; l.collector = collector or None; l.notes = notes or None
                    l.n_periods = periods_in_month(freq) * int(term)
                    db.commit(); st.success("Cambios guardados."); st.rerun()

                st.markdown("---")
                st.subheader("Renovar con pago solo intereses")
                t = loan_totals(db, l)
                st.caption(f"Interés de un mes: {money(l.principal * l.monthly_rate)}. Registra el pago de sólo interés y crea un nuevo préstamo desde hoy o sólo paga intereses sin renovar.")
                cerrar = st.checkbox("Cerrar con ajuste contable (recomendado)", value=True, key=f"aj_{l.id}")
                bcol1, bcol2 = st.columns(2)
                with bcol1:
                    if st.button("Pago SOLO intereses", key=f"btn_solo_interes_{l.id}"):
                        # Registrar pago de intereses sin renovar ni duplicar
                        db.add(Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(), amount=l.principal*l.monthly_rate, method="solo_interes", note="Pago solo intereses"))
                        db.commit()
                        st.success("Interés registrado.")
                        st.toast("✅ Pago de solo intereses registrado")
                        st.rerun()
                with bcol2:
                    if st.button("Pago solo intereses (renovar)", key=f"btn_ren_{l.id}"):
                        db.add(Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(), amount=l.principal*l.monthly_rate, method="solo_interes_renovación", note="Renovación"))
                        if cerrar:
                            tot = loan_totals(db, l)
                            if tot["balance"]>0:
                                db.add(Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(), amount=tot["balance"], method="ajuste_renovación", note="Cierre por renovación"))
                        l.status = "renovado"; l.visible = 0
                        newL = Loan(customer_id=l.customer_id, principal=l.principal, monthly_rate=l.monthly_rate, term_months=l.term_months,
                                    start_date=date.today(), n_periods=periods_in_month(l.frequency)*int(l.term_months), frequency=l.frequency,
                                    collector=l.collector, notes=l.notes)
                        db.add(newL); db.commit(); 
                        st.success(f"Renovado. Nuevo préstamo #{newL.id}.")
                        st.toast(f"🔁 Préstamo #{l.id} renovado → nuevo #{newL.id}")
                

    with tab3:
        if loans:
            sel = st.selectbox("Préstamo", options=loan_opts, key="sch_sel")
            cur = next(l for l in loans if f"{l.id} - {l.customer.name}"==sel)
            with SessionLocal() as db:
                l = db.get(Loan, cur.id)
                sched = build_schedule(l)
                t = loan_totals(db,l)
                df = pd.DataFrame({"#":[i+1 for i in range(len(sched))],"Vencimiento":sched,"Cuota":[t["quota_periodica"]]*len(sched)})
                df["Cuota"] = df["Cuota"].map(money); st.table(df)

# Pagos
# ---------- Pagos ----------

if page == "Pagos":
    st.header("Pagos")
    # Selector de cliente
    with SessionLocal() as db:
        customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    cust = st.selectbox("Cliente", options=[f"{c.id} - {c.name}" for c in customers], key="pg_pay_cust")

    # Cargar préstamos del cliente (eager load) y crear etiquetas amigables
    from sqlalchemy.orm import joinedload
    with SessionLocal() as db:
        cid = int(cust.split(" - ")[0])
        loans = db.execute(
            select(Loan).options(joinedload(Loan.customer)).where(Loan.customer_id==cid).order_by(Loan.id.desc())
        ).scalars().all()

        loan_labels = []
        label_to_id = {}
        for l in loans:
            t = loan_totals(db, l)
            d = delinquency(db, l)
            stt = loan_state_with_threshold(db, l, upcoming_days=3)
            next_due = d["next_due"].strftime("%Y-%m-%d") if d["next_due"] else "-"
            label = f"{l.id} · saldo {money(t['balance'])} · {stt.capitalize()} · vence {next_due}"
            loan_labels.append(label)
            label_to_id[label] = l.id

    if not loans:
        st.info("Este cliente no tiene préstamos activos.")
    else:
        loan_sel_label = st.selectbox("Préstamo", options=loan_labels, key="pg_pay_loan")
        loan_id = label_to_id[loan_sel_label]

        # Resumen del préstamo
        with SessionLocal() as db:
            l = db.get(Loan, loan_id)
            t = loan_totals(db, l); d = delinquency(db, l)
            stt = loan_state_with_threshold(db, l, upcoming_days=3)
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f'<div class="block"><div class="muted">Saldo</div><div class="kpi">{money(t["balance"])}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="block"><div class="muted">Cuota</div><div class="kpi">{money(t["quota_periodica"])}</div></div>', unsafe_allow_html=True)
        next_due = d["next_due"].strftime("%Y-%m-%d") if d["next_due"] else "-"
        c3.markdown(f'<div class="block"><div class="muted">Próximo vencimiento</div><div class="kpi">{next_due}</div></div>', unsafe_allow_html=True)
        c4.markdown(f'<div class="block"><div class="muted">Estado</div><div class="kpi">{state_chip(stt)}</div></div>', unsafe_allow_html=True)

        # --- Registrar pago ---
        st.markdown("### Registrar pago")
        amount = st.number_input("💵 Monto", min_value=0.0, step=100.0, key="pg_pay_amount")
        method = st.selectbox("🧾 Método", ["efectivo", "transferencia", "otro"], key="pg_pay_method")
        note = st.text_input("🗒️ Nota", key="pg_pay_note")

        st.divider()
        st.markdown("**Acciones**")
        colL, colR = st.columns(2)

        with colL:
            if st.button("💾 Registrar pago", type="primary", key="pg_pay_btn"):
                with SessionLocal() as db:
                    l = db.get(Loan, loan_id)
                    db.add(Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(), amount=amount, method=method or None, note=note or None))
                    db.commit()
                st.success("Pago registrado.")
                st.toast("💰 Pago registrado")
                # Recibo PDF
                with SessionLocal() as db2:
                    from sqlalchemy import select
                    from sqlalchemy.orm import joinedload
                    p = db2.execute(select(Payment).where(Payment.loan_id==loan_id).order_by(Payment.id.desc())).scalars().first()
                    l2 = db2.execute(select(Loan).options(joinedload(Loan.customer)).where(Loan.id==loan_id)).scalars().first()
                    if p and l2:
                        pdf_io, fname = build_payment_receipt_pdf(p, l2.customer, l2)
                        if pdf_io:
                            st.download_button("📄 Descargar recibo (PDF)", data=pdf_io, file_name=fname, mime="application/pdf", key=f"dl_pdf_{p.id}")
                st.rerun()

        with colR:
            cerrar = True  # Cierre contable forzado para evitar errores en cartera
        if st.button("🔁 Pago solo intereses (renovar)", key=f"pg_pay_renovar_{loan_id}"):
                with SessionLocal() as db:
                    l = db.get(Loan, loan_id)
                    interes = (l.principal or 0.0) * (l.monthly_rate or 0.0)
                    p_int = Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(),
                                    amount=interes, method="solo_interes_renovación", note="Renovación")
                    db.add(p_int)
                    if cerrar:
                        tot = loan_totals(db, l)
                        if tot["balance"] > 0:
                            p_adj = Payment(loan_id=l.id, customer_id=l.customer_id, date=date.today(),
                                            amount=tot["balance"], method="ajuste_renovación", note="Cierre por renovación")
                            db.add(p_adj)
                    l.status = "renovado"; l.visible = 0
                    newL = Loan(customer_id=l.customer_id, principal=l.principal, monthly_rate=l.monthly_rate,
                                term_months=l.term_months, start_date=date.today(),
                                n_periods=periods_in_month(l.frequency)*int(l.term_months), frequency=l.frequency,
                                collector=l.collector, notes=l.notes)
                    db.add(newL); db.commit()
                    new_id = newL.id; p_id = p_int.id
                st.success(f"Renovado. Nuevo préstamo #{new_id}.")
                st.toast(f"🔁 Préstamo #{loan_id} renovado → nuevo #{new_id}")
                # Recibo
                with SessionLocal() as db2:
                    from sqlalchemy.orm import joinedload
                    from sqlalchemy import select
                    p = db2.get(Payment, p_id)
                    l2 = db2.execute(select(Loan).options(joinedload(Loan.customer)).where(Loan.id==loan_id)).scalars().first()
                    if p and l2:
                        pdf_io, fname = build_payment_receipt_pdf(p, l2.customer, l2)
                        if pdf_io:
                            st.download_button("📄 Recibo de intereses (PDF)", data=pdf_io, file_name=fname, mime="application/pdf", key=f"dl_pdf_int_{p.id}")
                st.rerun()
# Reportes
# Aging y exportación


if page == "Reportes":
    st.header("📄 Reportes")
    upcoming_days = st.slider("Días para 'por vencer'", 1, 14, 3, key="rep_days")
    with SessionLocal() as db:
        loans = db.execute(select(Loan).options(joinedload(Loan.customer)).order_by(Loan.id.desc())).scalars().all()
        loan_opts = [f"{l.id} - {l.customer.name if l.customer else '-'}" for l in loans]
        rows = []
        for l in loans:
            tot = loan_totals(db, l); d = delinquency(db, l)
            estado = loan_state_with_threshold(db, l, upcoming_days=upcoming_days)
            rows.append({"Préstamo": l.id, "Cliente": l.customer.name if l.customer else "-", "Principal": tot["principal"], "Saldo": tot["balance"], "Cuota": tot["quota_periodica"], "Frecuencia": l.frequency, "Inicio": l.start_date, "Días mora": d["days_late"], "Estado": estado})
        df = pd.DataFrame(rows)
    # Filtro por estado
    estados_validos = ["Todos","vigente","pagado","vencido"]
    estado_sel = st.selectbox("Filtrar por estado", estados_validos, index=0, key="rep_estado")
    if estado_sel != "Todos" and not df.empty:
        # Filtramos antes de mapear chips por si hubiera estilos
        if "Estado" in df.columns:
            df = df[df["Estado"].str.lower()==estado_sel.lower()].reset_index(drop=True)
    if not df.empty:
        # Botón de exportación a Excel
        xls_io, xls_name = export_df_to_excel(df.rename(columns={"Préstamo":"Prestamo"}))
        st.download_button("Exportar a Excel", data=xls_io, file_name=xls_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="rep_excel")
        order = {"vencido":0,"por vencer":1,"vigente":2,"pagado":3}
        df["_o"] = df["Estado"].str.lower().map(lambda s: order.get(s,9))
        df = df.sort_values(["_o","Saldo"], ascending=[True,False]).drop(columns=["_o"])
        from html import escape as _esc
        headers = df.columns.tolist()
        html = '<table class="state-table" style="width:100%;border-collapse:collapse">'
        html += '<thead><tr>' + ''.join([f'<th style="text-align:left;padding:8px;border-bottom:1px solid #eee;">{_esc(str(h))}</th>' for h in headers]) + '</tr></thead><tbody>'
        for _, row in df.iterrows():
            stt = str(row["Estado"]).lower()
            bg = "#ffe5e5" if "vencido" in stt else "#fff4cc" if "por vencer" in stt else "#e8f5e9"
            tds = []
            for h in headers:
                v = row[h]
                if h=="Estado": val_html = state_chip(str(v))
                elif h in ["Principal","Saldo","Cuota"]:
                    try: val_html = money(v)
                    except: val_html = _esc(str(v))
                else: val_html = _esc(str(v))
                tds.append(f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{val_html}</td>')
            html += f'<tr style="background:{bg}">' + ''.join(tds) + '</tr>'
        html += '</tbody></table>'
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("Sin datos para mostrar.")

# Estadísticas
if page == "Estadísticas":
    st.header("📈 Estadísticas (sin gráficas)")
    upcoming_days = st.slider("Días para 'por vencer'", 1, 14, 3, key="stats_days")
    with SessionLocal() as db:
        loans = db.execute(select(Loan)).scalars().all()
        rows = []
        saldo = vencido = por_vencer = vigente = 0.0
        for l in loans:
            t = loan_totals(db,l); stt = loan_state_with_threshold(db,l, upcoming_days=upcoming_days)
            rows.append({"Cliente": l.customer.name if l.customer else "-", "Saldo": t["balance"], "Estado": stt})
            saldo += t["balance"]
            if stt=="vencido": vencido += t["balance"]
            elif stt=="por vencer": por_vencer += t["balance"]
            elif stt in ("vigente","pagado"): vigente += t["balance"]
        st.markdown('<div class="grid">', unsafe_allow_html=True)
        st.markdown(f'<div class="block"><div class="muted">Saldo de cartera</div><div class="kpi">{money(saldo)}</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="block"><div class="muted">Vencido</div><div class="kpi">{money(vencido)}</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="block"><div class="muted">Por vencer</div><div class="kpi">{money(por_vencer)}</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="block"><div class="muted">Vigente</div><div class="kpi">{money(vigente)}</div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        df = pd.DataFrame(rows)
        if not df.empty:
            df2 = df.copy()
            df2["Estado"] = df2["Estado"].map(state_chip)
            st.markdown(df2.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("Sin datos.")

# --- Safe fallback for state label ---
from datetime import date
def loan_state_with_threshold(delin, loan=None, warn_days:int=3):
    """Devuelve Vigente/Por vencer/Vence hoy/Vencido según fechas en `delin`. """
    if not delin:
        return "Vigente"
    try:
        days_late = int(delin.get("days_late") or 0)
    except Exception:
        days_late = 0
    nxt = delin.get("next_due")
    today = date.today()
    if days_late > 0:
        return "Vencido"
    if nxt is None:
        return "Vigente"
    if nxt == today:
        return "Vence hoy"
    diff = (nxt - today).days
    if 0 < diff <= warn_days:
        return "Por vencer"
    return "Vigente"
