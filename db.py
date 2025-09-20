from sqlalchemy import create_engine, Column, Integer, Float, String, Date, DateTime, ForeignKey, func, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os, sqlite3, hashlib, datetime as _dt

DB_PATH = os.environ.get("COBROS_DB_PATH", "data.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    document = Column(String(60), nullable=True)
    phone = Column(String(60), nullable=True)
    address = Column(String(180), nullable=True)
    zone = Column(String(80), nullable=True)
    neighborhood = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    loans = relationship("Loan", back_populates="customer", cascade="all, delete-orphan")

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    principal = Column(Float, nullable=False)
    monthly_rate = Column(Float, nullable=False, default=0.1)
    term_months = Column(Integer, nullable=False, default=1)
    start_date = Column(Date, nullable=False)
    n_periods = Column(Integer, nullable=False)
    frequency = Column(String(20), nullable=False)
    collector = Column(String(80), nullable=True)
    status = Column(String(30), nullable=False, default="activo")  # activo, renovado
    visible = Column(Integer, nullable=False, default=1)           # 1 visible en cartera
    promesa_pago = Column(Date, nullable=True)
    priority = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)

    customer = relationship("Customer", back_populates="loans")
    payments = relationship("Payment", back_populates="loan", cascade="all, delete-orphan")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), index=True, nullable=False)
    customer_id = Column(Integer, index=True, nullable=True)
    date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String(40), nullable=True)
    note = Column(Text, nullable=True)
    loan = relationship("Loan", back_populates="payments")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, index=True, nullable=True)
    action = Column(String(80), nullable=False)
    info = Column(Text, nullable=True)
    ts = Column(DateTime, nullable=False)

def ensure_columns():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    def cols(table):
        cur.execute(f"PRAGMA table_info({table});")
        return {r[1] for r in cur.fetchall()}
    # payments.customer_id
    p = cols("payments")
    if "customer_id" not in p:
        try: cur.execute("ALTER TABLE payments ADD COLUMN customer_id INTEGER;")
        except Exception: pass
    # customers extras
    c = cols("customers")
    if "zone" not in c:
        try: cur.execute("ALTER TABLE customers ADD COLUMN zone TEXT;")
        except Exception: pass
    if "neighborhood" not in c:
        try: cur.execute("ALTER TABLE customers ADD COLUMN neighborhood TEXT;")
        except Exception: pass
    # loans extras
    l = cols("loans")
    if "visible" not in l:
        try: cur.execute("ALTER TABLE loans ADD COLUMN visible INTEGER DEFAULT 1;")
        except Exception: pass
    if "promesa_pago" not in l:
        try: cur.execute("ALTER TABLE loans ADD COLUMN promesa_pago DATE;")
        except Exception: pass
    if "priority" not in l:
        try: cur.execute("ALTER TABLE loans ADD COLUMN priority TEXT;")
        except Exception: pass
    conn.commit(); conn.close()

def _hash_password(pw: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()
    return f"sha256${salt}${h}"

def _verify_password(pw: str, stored: str) -> bool:
    try:
        algo, salt, h = stored.split("$", 2)
        if algo != "sha256":
            return False
        return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest() == h
    except Exception:
        return False

def ensure_admin_user():
    from sqlalchemy import select
    with SessionLocal() as s:
        try:
            u = s.execute(select(User).limit(1)).scalars().first()
        except Exception:
            return
        if not u:
            s.add(User(username="admin", password_hash=_hash_password("admin"), created_at=_dt.datetime.utcnow()))
            s.commit()

def verify_password(username: str, password: str) -> bool:
    from sqlalchemy import select
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.username==username)).scalars().first()
        return bool(u and _verify_password(password, u.password_hash))


def ensure_user(username: str, password: str):
    """Crea el usuario si no existe."""
    from sqlalchemy import select, delete
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.username == username)).scalars().first()
        if not u:
            s.add(User(username=username, password_hash=_hash_password(password), created_at=_dt.datetime.utcnow()))
            s.commit()

def remove_user(username: str):
    """Elimina un usuario por username (si existe)."""
    from sqlalchemy import select, delete
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.username == username)).scalars().first()
        if u:
            s.delete(u)
            s.commit()

def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    ensure_user('elcy_jaramillo', 'Elcyja066@')
    remove_user('admin')
    return engine, SessionLocal
