from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, BigInteger
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[str] = mapped_column(String(100), nullable=False)

    type: Mapped[str] = mapped_column(String(20), default="sale")
    status: Mapped[str] = mapped_column(String(20), default="free")

    description: Mapped[str] = mapped_column(Text, nullable=True)
    photo_id: Mapped[str] = mapped_column(String(255), nullable=True)

    price: Mapped[float] = mapped_column(Float, nullable=True)
    price_3h: Mapped[float] = mapped_column(Float, nullable=True)
    price_6h: Mapped[float] = mapped_column(Float, nullable=True)
    price_12h: Mapped[float] = mapped_column(Float, nullable=True)

    lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    order_id: Mapped[str] = mapped_column(String(100), nullable=True)
    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=True)

    payment_method: Mapped[str] = mapped_column(String(20), nullable=True)

    reserved_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    rented_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    crypto_invoice_id: Mapped[int] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sold_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    buyer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    funpay_order: Mapped[str] = mapped_column(String(100), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
