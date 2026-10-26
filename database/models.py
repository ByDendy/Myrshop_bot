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

    status: Mapped[str] = mapped_column(String(30), default="free")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str] = mapped_column(String(255), nullable=True)

    price_3h: Mapped[float] = mapped_column(Float, nullable=False)
    price_6h: Mapped[float] = mapped_column(Float, nullable=False)
    price_12h: Mapped[float] = mapped_column(Float, nullable=False)

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
    promo_id: Mapped[int] = mapped_column(Integer, nullable=True)
    promo_discount: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Новые поля для корректного списания
    final_price: Mapped[float] = mapped_column(Float, nullable=True)
    bonus_spent: Mapped[float] = mapped_column(Float, nullable=True)

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
    avatar_id: Mapped[str] = mapped_column(String(255), nullable=True)

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
    status: Mapped[str] = mapped_column(String(20), default="frozen")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class PartnerPayout(Base):
    __tablename__ = "partner_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partner_id: Mapped[int] = mapped_column(Integer, ForeignKey("partners.id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
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


class Customer(Base):
    __tablename__ = "customers"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    avatar_id: Mapped[str] = mapped_column(String(255), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str] = mapped_column(Text, nullable=True)
    banned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    agreed_to_terms: Mapped[bool] = mapped_column(Boolean, default=False)
    agreed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    bonus_balance: Mapped[float] = mapped_column(Float, default=0.0)
    referred_by: Mapped[int] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    referred_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    orders_completed: Mapped[int] = mapped_column(Integer, default=0)
    bonus_paid: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BonusTransaction(Base):
    __tablename__ = "bonus_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Promocode(Base):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    discount_type: Mapped[str] = mapped_column(String(20), default="percent")
    discount_value: Mapped[float] = mapped_column(Float, nullable=False)
    condition_type: Mapped[str] = mapped_column(String(30), default="any_order")
    max_uses: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PromocodeUse(Base):
    __tablename__ = "promocode_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promocode_id: Mapped[int] = mapped_column(Integer, ForeignKey("promocodes.id"))
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    original_price: Mapped[float] = mapped_column(Float, nullable=False)
    discount_applied: Mapped[float] = mapped_column(Float, nullable=False)
    final_price: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)