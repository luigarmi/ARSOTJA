import os, hashlib, datetime as _dt

# 1) Primero ENV
DB_URL = os.getenv("DATABASE_URL")

# 2) Intentar st.secrets de forma segura (sólo si existe y sin exigir secrets.toml)
if not DB_URL:
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
            DB_URL = st.secrets["DATABASE_URL"]
    except Exception:
        DB_URL = None

# 3) Fallback local
if not DB_URL:
    DB_URL = "sqlite:///data.db"

from sqlalchemy import create_engine, Column, Integer, Float, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

def _hash_password(pw: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()
    return f"sha256${salt}${h}"

def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, salt, h = stored.split("$")
        return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest() == h
    except Exception:
        return False

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=_dt.datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    document = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    zone = Column(String, nullable=True)
    neighborhood = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    loans = relationship("Loan", back_populates="customer")

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    principal = Column(Float, nullable=False)
    monthly_rate = Column(Float, nullable=False, default=0.2)
    term_months = Column(Integer, nullable=False, default=1)
    start_date = Column(Date, nullable=False)
    n_periods = Column(Integer, nullable=False)
    frequency = Column(String, nullable=False, default="mensual")
    collector = Column(String, nullable=True)
    status = Column(String, nullable=False, default="activo")
    visible = Column(Integer, nullable=False, default=1)
    promesa_pago = Column(Date, nullable=True)
    priority = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    customer = relationship("Customer", back_populates="loans")
    payments = relationship("Payment", back_populates="loan")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=True)
    note = Column(Text, nullable=True)

    loan = relationship("Loan", back_populates="payments")

def init_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        from sqlalchemy import select
        u = s.execute(select(User).where(User.username=="elcy_jaramillo")).scalar()
        if not u:
            s.add(User(username="elcy_jaramillo", password_hash=_hash_password("Elcyja066@")))
            s.commit()
    return engine, SessionLocal