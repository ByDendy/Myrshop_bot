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

    tier: Mapped[str] = mapped_column(String(20), default="standard")
    riot_id: Mapped[str] = mapped_column(String(100), nullable=True)

    email: Mapped[str] = mapped_column(String(255), nullable=True)
    email_password: Mapped[str] = mapped_column(String(255), nullable=True)

    # Статусы: free | reserved | rented | awaiting_password_change |
    #          pending_approval | rejected | awaiting_review | awaiting_approval
    status: Mapped[str] = mapped_column(String(30), default="free")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str] = mapped_column(String(255), nullable=True)

    price_3h: Mapped[float] = mapped_column(Float, nullable=False)
    price_6h: Mapped[float] = mapped_column(Float, nullable=False)
    price_12h: Mapped[float] = mapped_column(Float, nullable=False)

    # ─── Партнёрские поля ───
    partner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partners.id"), nullable=True,
    )
    password_changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_rental_ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[str] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    payment_invoice_id: Mapped[str] = mapped_column(String(100), nullable=True)
    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    rental_hours: Mapped[int] = mapped_column(Integer, nullable=True)
    rented_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)

    # Если NULL — используется глобальная комиссия из settings
    commission_percent: Mapped[float] = mapped_column(Float, nullable=True)

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    frozen_balance: Mapped[float] = mapped_column(Float, default=0.0)
    total_earned: Mapped[float] = mapped_column(Float, default=0.0)
    total_paid: Mapped[float] = mapped_column(Float, default=0.0)

    payment_details: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RankSetting(Base):
    __tablename__ = "rank_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    min_price_3h: Mapped[float] = mapped_column(Float, default=0.0)
    min_price_6h: Mapped[float] = mapped_column(Float, default=0.0)
    min_price_12h: Mapped[float] = mapped_column(Float, default=0.0)


class PartnerEarning(Base):
    __tablename__ = "partner_earnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partner_id: Mapped[int] = mapped_column(Integer, ForeignKey("partners.id"))
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    rental_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rental_history.id"), nullable=True,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    platform_amount: Mapped[float] = mapped_column(Float, nullable=False)
    # frozen | available | paid | refunded
    status: Mapped[str] = mapped_column(String(20), default="frozen")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class PartnerPayout(Base):
    __tablename__ = "partner_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partner_id: Mapped[int] = mapped_column(Integer, ForeignKey("partners.id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # requested | paid | rejected
    status: Mapped[str] = mapped_column(String(20), default="requested")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=True)


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
