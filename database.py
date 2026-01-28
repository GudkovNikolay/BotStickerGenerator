"""
Модели базы данных и подключение
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, 
    DateTime, ForeignKey, Text, Float, Index
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from config import settings

Base = declarative_base()


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    is_premium = Column(Boolean, default=False)
    free_generations_left = Column(Integer, default=3)
    referral_code = Column(String(50), unique=True, nullable=False, index=True)
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    generations = relationship("Generation", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    referrals = relationship("User", remote_side=[id], backref="referrer")
    
    __table_args__ = (
        Index("idx_telegram_id", "telegram_id"),
        Index("idx_referral_code", "referral_code"),
    )


class Generation(Base):
    """Модель генерации стикеров"""
    __tablename__ = "generations"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    prompt = Column(Text, nullable=False)
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    sticker_pack_id = Column(String(255), nullable=True)
    images_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="generations")
    
    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_status", "status"),
        Index("idx_created_at", "created_at"),
    )


class Payment(Base):
    """Модель платежа"""
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="RUB")
    provider = Column(String(50), nullable=False)  # yookassa, stripe
    payment_id = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(50), default="pending")  # pending, succeeded, failed, canceled
    metadata = Column(Text, nullable=True)  # JSON для дополнительных данных
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    
    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_payment_id", "payment_id"),
        Index("idx_status", "status"),
    )


class ReferralReward(Base):
    """Модель реферальных наград"""
    __tablename__ = "referral_rewards"
    
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    referred_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reward_amount = Column(Float, nullable=False)
    reward_type = Column(String(50), nullable=False)  # generation, payment
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_referrer_id", "referrer_id"),
        Index("idx_referred_id", "referred_id"),
    )


# Создание движка и сессии
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_session() -> AsyncSession:
    """Получить сессию базы данных (контекстный менеджер)"""
    async with async_session_maker() as session:
        return session


async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

