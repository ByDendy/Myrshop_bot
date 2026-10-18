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

    # Всегда 'free' | 'reserved' | 'rented'
    status: Mapped[str] = mapped_column(String(20), default="free")

    description: Mapped[str] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str] = mapped_column(String(255), nullable=True)

    # Цены аренды (только)
    price_3h: Mapped[float] = mapped_column(Float, nullable=False)
    price_6h: Mapped[float] = mapped_column(Float, nullable=False)
    price_12h: Mapped[float] = mapped_column(Float, nullable=False)

    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    rental_hours: Mapped[int] = mapped_column(Integer, nullable=True)
    rented_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lot(Base):
    """Один лот FunPay = комбинация (rank, hours)."""
    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rank: Mapped[str] = mapped_column(String(100), nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)  # 3, 6, 12
    price: Mapped[float] = mapped_column(Float, nullable=False)
    funpay_lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)