"""
Сервис для работы с базой данных
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from database import User, Generation, Payment, ReferralReward
from utils import generate_referral_code
import logging

logger = logging.getLogger(__name__)


class DatabaseService:
    """Сервис для работы с БД"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_or_create_user(self, telegram_id: int, username: str = None, 
                                 first_name: str = None, last_name: str = None) -> User:
        """Получить или создать пользователя"""
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Генерируем уникальный реферальный код
            referral_code = generate_referral_code()
            while await self._referral_code_exists(referral_code):
                referral_code = generate_referral_code()
            
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                referral_code=referral_code
            )
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            logger.info(f"Создан новый пользователь: {telegram_id}")
        
        return user
    
    async def _referral_code_exists(self, code: str) -> bool:
        """Проверка существования реферального кода"""
        result = await self.session.execute(
            select(User).where(User.referral_code == code)
        )
        return result.scalar_one_or_none() is not None
    
    async def use_free_generation(self, user_id: int) -> bool:
        """Использовать бесплатную генерацию"""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        if user.free_generations_left > 0:
            user.free_generations_left -= 1
            await self.session.commit()
            return True
        return False
    
    async def create_generation(self, user_id: int, prompt: str) -> Generation:
        """Создать запись о генерации"""
        generation = Generation(
            user_id=user_id,
            prompt=prompt,
            status="pending"
        )
        self.session.add(generation)
        await self.session.commit()
        await self.session.refresh(generation)
        return generation
    
    async def update_generation(
        self, 
        generation_id: int, 
        status: str,
        sticker_pack_id: str = None,
        images_count: int = 0,
        error_message: str = None,
        sticker_pack_name: str = None
    ) -> None:
        """Обновить статус генерации"""
        await self.session.execute(
            update(Generation)
            .where(Generation.id == generation_id)
            .values(
                status=status,
                sticker_pack_id=sticker_pack_id,
                images_count=images_count,
                error_message=error_message,
                sticker_pack_name=sticker_pack_name
            )
        )
        await self.session.commit()
    
    async def process_referral(self, referrer_code: str, referred_user_id: int) -> bool:
        """Обработка реферального кода"""
        result = await self.session.execute(
            select(User).where(User.referral_code == referrer_code)
        )
        referrer = result.scalar_one_or_none()
        
        if not referrer or referrer.id == referred_user_id:
            return False
        
        # Проверяем, не использовал ли уже этот пользователь реферальный код
        result = await self.session.execute(
            select(User).where(User.id == referred_user_id)
        )
        referred_user = result.scalar_one_or_none()
        
        if not referred_user:
            return False
        
        if referred_user.referred_by is not None:
            return False  # Уже использовал реферальный код
        
        # Назначаем реферера
        referred_user.referred_by = referrer.id
        # Даем бонус рефереру (например, +1 бесплатная генерация)
        referrer.free_generations_left += 1
        
        # Создаем запись о награде
        reward = ReferralReward(
            referrer_id=referrer.id,
            referred_id=referred_user_id,
            reward_amount=1,
            reward_type="generation"
        )
        self.session.add(reward)
        
        await self.session.commit()
        return True
    
    async def get_user_stats(self, user_id: int) -> dict:
        """Получить статистику пользователя"""
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            return {
                "free_generations_left": 0,
                "total_generations": 0,
                "completed_generations": 0,
                "referrals_count": 0,
                "referral_code": "",
                "is_premium": False
            }
        
        generations_result = await self.session.execute(
            select(func.count(Generation.id))
            .where(Generation.user_id == user_id)
        )
        total_generations = generations_result.scalar() or 0
        
        completed_result = await self.session.execute(
            select(func.count(Generation.id))
            .where(
                Generation.user_id == user_id,
                Generation.status == "completed"
            )
        )
        completed_generations = completed_result.scalar() or 0
        
        referrals_result = await self.session.execute(
            select(func.count(User.id))
            .where(User.referred_by == user_id)
        )
        referrals_count = referrals_result.scalar() or 0
        
        return {
            "free_generations_left": user.free_generations_left,
            "total_generations": total_generations,
            "completed_generations": completed_generations,
            "referrals_count": referrals_count,
            "referral_code": user.referral_code,
            "is_premium": user.is_premium
        }

# В db_service.py

    async def get_user_discount(self, user_id: int) -> dict:
        """
        Возвращает информацию о скидке пользователя
        """
        # Получаем пользователя
        user = await self.get_user_by_id(user_id)
        if not user:
            return {'has_discount': False, 'discount_percent': 0}
        
        # Проверяем, есть ли активные реферальные бонусы
        # Вариант 1: Скидка за рефералов (50%)
        referrals_count = await self.get_referrals_count(user_id)
        
        if referrals_count > 0:
            return {
                'has_discount': True,
                'discount_percent': 50,
                'reason': f'Привел {referrals_count} друзей',
                'original_price': settings.STICKER_PACK_PRICE,
                'final_price': settings.STICKER_PACK_PRICE * 0.5
            }
        
        # Вариант 2: Скидка если сам перешел по реферальной ссылке
        # (нужно поле в таблице users: referred_by)
        if user.referred_by:
            return {
                'has_discount': True,
                'discount_percent': 50,
                'reason': 'Пришел по реферальной ссылке',
                'original_price': settings.STICKER_PACK_PRICE,
                'final_price': settings.STICKER_PACK_PRICE * 0.5
            }
        
        return {'has_discount': False, 'discount_percent': 0}


    async def get_referrals_count(self, user_id: int) -> int:
        """Возвращает количество рефералов пользователя"""
        # Запрос к таблице referrals
        query = "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1"
        result = await self.conn.fetchval(query, user_id)
        return result or 0