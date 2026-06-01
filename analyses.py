"""
Симуляция реферального перехода в БД
"""
import asyncio
from sqlalchemy import select, update, insert
from database import engine, User, DiscountCoupon, ReferralReward
from datetime import datetime

async def simulate_referral_flow():
    """
    Симулируем шаги, которые делает процесс_referral()
    """
    
    print("="*60)
    print("🔍 СИМУЛЯЦИЯ РЕФЕРАЛЬНОГО ПЕРЕХОДА")
    print("="*60)
    
    async with engine.begin() as conn:
        
        # ШАГ 1: Савва переходит по ссылке и бот получает его данные
        print("\n📥 ШАГ 1: Савва переходит по ссылке")
        print("   Бот получает: from_user.id = 847890186 (Савва)")
        print("   Параметр start = 'JMS7PLKZ' (код пользователя 1)")
        
        # ШАГ 2: Бот ищет или создает пользователя Савву
        print("\n🔍 ШАГ 2: Поиск/создание пользователя с telegram_id = 847890186")
        
        result = await conn.execute(
            select(User).where(User.telegram_id == 847890186)
        )
        referred_user = result.first()
        
        if referred_user:
            print(f"   ✅ Найден существующий пользователь:")
            print(f"      ID: {referred_user.id}")
            print(f"      Telegram ID: {referred_user.telegram_id}")
            print(f"      Имя: {referred_user.first_name}")
            print(f"      referred_by: {referred_user.referred_by}")
        else:
            print(f"   ⚠️ Пользователь не найден")
        
        # ШАГ 3: Бот ищет реферера по коду JMS7PLKZ
        print("\n🔍 ШАГ 3: Поиск реферера по коду 'JMS7PLKZ'")
        
        result = await conn.execute(
            select(User).where(User.referral_code == 'JMS7PLKZ')
        )
        referrer = result.first()
        
        if referrer:
            print(f"   ✅ Найден реферер:")
            print(f"      ID: {referrer.id}")
            print(f"      Telegram ID: {referrer.telegram_id}")
            print(f"      Реферальный код: {referrer.referral_code}")
        else:
            print(f"   ❌ РЕФЕРЕР НЕ НАЙДЕН!")
        
        # ШАГ 4: Проверка, не использовал ли Савва уже рефералку
        print("\n🔍 ШАГ 4: Проверка referred_by у Саввы")
        
        if referred_user and referred_user.referred_by is not None:
            print(f"   ❌ referred_by уже = {referred_user.referred_by}")
            print(f"   Награда НЕ будет выдана (уже есть реферер)")
        elif referred_user:
            print(f"   ✅ referred_by = None - можно выдавать награду")
        
        # ШАГ 5: Если все ок - выдаем награду
        if referrer and referred_user and referred_user.referred_by is None:
            print("\n✅ ШАГ 5: Выдача награды")
            
            # 5.1 Обновляем referred_user
            print("   5.1 Обновляем referred_by у Саввы")
            await conn.execute(
                update(User)
                .where(User.id == referred_user.id)
                .values(referred_by=referrer.id)
            )
            print(f"       Савва (ID {referred_user.id}) теперь referred_by = {referrer.id}")
            
            # 5.2 Создаем купон для реферера
            print("   5.2 Создаем купон для реферера")
            await conn.execute(
                insert(DiscountCoupon).values(
                    user_id=referrer.id,
                    source_user_id=referred_user.id,
                    used=False,
                    created_at=datetime.now()
                )
            )
            print(f"       Купон создан для user_id={referrer.id} (это вы)")
            
            # 5.3 Создаем запись о награде
            print("   5.3 Создаем запись в ReferralReward")
            await conn.execute(
                insert(ReferralReward).values(
                    referrer_id=referrer.id,
                    referred_id=referred_user.id,
                    reward_amount=1,
                    reward_type="generation",
                    created_at=datetime.now()
                )
            )
            print(f"       Запись о награде создана")
            
            await conn.commit()
            print("\n✅ НАГРАДА УСПЕШНО ВЫДАНА!")
            
        else:
            print("\n❌ НАГРАДА НЕ ВЫДАНА по причине:")
            if not referrer:
                print("   - Реферер не найден по коду")
            if not referred_user:
                print("   - Пользователь Савва не найден")
            if referred_user and referred_user.referred_by is not None:
                print(f"   - У Саввы уже есть реферер: {referred_user.referred_by}")

    # Отдельный блок для финальной проверки (новая транзакция)
    print("\n" + "="*60)
    print("📊 ФИНАЛЬНОЕ СОСТОЯНИЕ БД")
    print("="*60)
    
    async with engine.begin() as conn:
        # Все пользователи
        result = await conn.execute(select(User).order_by(User.id))
        users = result.fetchall()
        print("\n👥 ПОЛЬЗОВАТЕЛИ:")
        for user in users:
            ref_by = user.referred_by if hasattr(user, 'referred_by') else None
            print(f"   ID {user.id}: telegram_id={user.telegram_id}, referred_by={ref_by}, код={user.referral_code}")
        
        # Купоны
        result = await conn.execute(select(DiscountCoupon))
        coupons = result.fetchall()
        print(f"\n🎫 КУПОНЫ (всего: {len(coupons)}):")
        for coupon in coupons:
            print(f"   ID {coupon.id}: user_id={coupon.user_id}, source_user_id={coupon.source_user_id}, used={coupon.used}")
        
        # Награды
        result = await conn.execute(select(ReferralReward))
        rewards = result.fetchall()
        print(f"\n🏆 НАГРАДЫ (всего: {len(rewards)}):")
        for reward in rewards:
            print(f"   ID {reward.id}: referrer_id={reward.referrer_id}, referred_id={reward.referred_id}")


async def check_current_state():
    """Проверка текущего состояния БД"""
    print("\n" + "="*60)
    print("📊 ТЕКУЩЕЕ СОСТОЯНИЕ БД")
    print("="*60)
    
    async with engine.begin() as conn:
        # Проверяем пользователя 1 (вас)
        result = await conn.execute(select(User).where(User.id == 1))
        user1 = result.first()
        if user1:
            print(f"\n✅ Ваш аккаунт (ID 1):")
            print(f"   Telegram ID: {user1.telegram_id}")
            print(f"   Реферальный код: {user1.referral_code}")
        
        # Проверяем пользователя 7 (Савву)
        result = await conn.execute(select(User).where(User.id == 7))
        user7 = result.first()
        if user7:
            print(f"\n✅ Аккаунт Саввы (ID 7):")
            print(f"   Telegram ID: {user7.telegram_id}")
            print(f"   referred_by: {user7.referred_by}")
        
        # Проверяем купоны для вас
        result = await conn.execute(
            select(DiscountCoupon).where(DiscountCoupon.user_id == 1)
        )
        coupons = result.fetchall()
        print(f"\n🎫 Ваши купоны (user_id=1): {len(coupons)}")
        for coupon in coupons:
            print(f"   ID {coupon.id}: от пользователя ID {coupon.source_user_id}, использован: {coupon.used}")
        
        # Проверяем проблемного пользователя ID 3
        result = await conn.execute(select(User).where(User.id == 3))
        user3 = result.first()
        if user3:
            print(f"\n⚠️ Пользователь ID 3:")
            print(f"   Telegram ID: {user3.telegram_id} (аномалия!)")
            print(f"   referred_by: {user3.referred_by}")


async def manual_fix():
    """Ручное исправление - добавить награду если ее нет"""
    print("\n" + "="*60)
    print("🔧 ПРОВЕРКА И ДОБАВЛЕНИЕ НАГРАДЫ")
    print("="*60)
    
    async with engine.begin() as conn:
        # Проверяем, есть ли уже купон для вас от Саввы
        result = await conn.execute(
            select(DiscountCoupon).where(
                DiscountCoupon.user_id == 1,
                DiscountCoupon.source_user_id == 7
            )
        )
        existing = result.first()
        
        if existing:
            print(f"\n✅ Купон уже существует:")
            print(f"   ID: {existing.id}")
            print(f"   user_id: {existing.user_id}")
            print(f"   source_user_id: {existing.source_user_id}")
            print(f"   used: {existing.used}")
        else:
            print("\n❌ Купона нет! Создаем...")
            
            # Создаем купон
            await conn.execute(
                insert(DiscountCoupon).values(
                    user_id=1,
                    source_user_id=7,
                    used=False,
                    created_at=datetime.now()
                )
            )
            
            # Обновляем referred_by у Саввы если нужно
            result = await conn.execute(
                select(User).where(User.id == 7)
            )
            savva = result.first()
            
            if savva and savva.referred_by is None:
                await conn.execute(
                    update(User)
                    .where(User.id == 7)
                    .values(referred_by=1)
                )
                print("   ✅ referred_by у Саввы обновлен")
            
            await conn.commit()
            print("   ✅ Награда добавлена!")


if __name__ == "__main__":
    asyncio.run(simulate_referral_flow())
    asyncio.run(check_current_state())