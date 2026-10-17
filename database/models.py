from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="free")
    lot_id: Mapped[str] = mapped_column(String(100), nullable=True)
    order_id: Mapped[str] = mapped_column(String(100), nullable=True)
    buyer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    price: Mapped[float] = mapped_column(Float, default=500.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sold_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    buyer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    funpay_order: Mapped[str] = mapped_column(String(100), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)