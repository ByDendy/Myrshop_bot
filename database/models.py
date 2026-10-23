from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, Text, BigInteger, Boolean,
)
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[str] = mapped_column(String(100), nullable=False)

    # standard | premium
    tier: Mapped[str] = mapped_column(String(20), default="standard")

    email: Mapped[str] = mapped_column(String(255), nullable=True)
    email_password: Mapped[str] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="free")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str] = mapped_column(String(255), nullable=True)

    price_3h: Mapped[float] = mapped_column(Float, nullable=False)
    price_6h: Mapped[float] = mapped_column(Float, nullable=False)
    price_12h: Mapped[float] = mapped_column(Float, nullable=False)

    lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    payment_invoice_id: Mapped[str] = mapped_column(String(100), nullable=True)
    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    rental_hours: Mapped[int] = mapped_column(Integer, nullable=True)
    rented_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RentalHistory(Base):
    __tablename__ = "rental_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    method: Mapped[str] = mapped_column(String(50), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ended_reason: Mapped[str] = mapped_column(String(30), nullable=True)


class Lot(Base):
    __tablename__ = "lots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank: Mapped[str] = mapped_column(String(100), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="standard")
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    funpay_lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    order: Mapped[int] = mapped_column(Integer, default=0)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
