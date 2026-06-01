"""
Симуляция реферального перехода в БД
"""
import asyncio
from sqlalchemy import select, update, insert
from database import engine, User, DiscountCoupon, ReferralReward
from sqlalchemy import func
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
            print(f"   ⚠️ Пользователь не найден, нужно создавать нового")
            print(f"   (но в вашей выгрузке Савва уже есть - ID 7)")
        
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
            print(f"      Это могло быть причиной!")
        
        # ШАГ 4: Проверка, не использовал ли Савва уже рефералку
        print("\n🔍 ШАГ 4: Проверка referred_by у Саввы")
        
        if referred_user.referred_by is not None:
            print(f"   ❌ referred_by уже = {referred_user.referred_by}")
            print(f"   Награда НЕ будет выдана (уже есть реферер)")
        else:
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
        
        # ШАГ 6: Финальная проверка - смотрим всех пользователей
        print("\n" + "="*60)
        print("📊 ФИНАЛЬНОЕ СОСТОЯНИЕ БД")
        print("="*60)
        
        # Все пользователи
        result = await conn.execute(select(User).order_by(User.id))
        users = result.fetchall()
        print("\n👥 ПОЛЬЗОВАТЕЛИ:")
        for user in users:
            print(f"   ID {user.id}: telegram_id={user.telegram_id}, referred_by={user.referred_by}, код={user.referral_code}")
        
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


async def check_problematic_user():
    """Проверяем проблемного пользователя ID 3"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ПРОБЛЕМНОГО ПОЛЬЗОВАТЕЛЯ ID 3")
    print("="*60)
    
    async with engine.begin() as conn:
        result = await conn.execute(select(User).where(User.id == 3))
        user = result.first()
        
        if user:
            print(f"\n⚠️ НАЙДЕН АНОМАЛЬНЫЙ ПОЛЬЗОВАТЕЛЬ:")
            print(f"   ID: {user.id}")
            print(f"   Telegram ID: {user.telegram_id} ← ЭТО НЕ МОЖЕТ БЫТЬ 1!")
            print(f"   Имя: {user.first_name}")
            print(f"   referred_by: {user.referred_by}")
            
            # Проверяем, нет ли конфликта с вашим реальным Telegram ID
            result = await conn.execute(
                select(User).where(User.telegram_id == 788139267)
            )
            real_you = result.first()
            
            if real_you:
                print(f"\n✅ ВАШ РЕАЛЬНЫЙ АККАУНТ (telegram_id 788139267):")
                print(f"   ID: {real_you.id}")
                print(f"   Telegram ID: {real_you.telegram_id}")
                print(f"   referred_by: {real_you.referred_by}")
                
                if real_you.id == 1:
                    print(f"\n✅ ВСЕ ХОРОШО: Ваш аккаунт ID=1, telegram_id правильный")
                else:
                    print(f"\n❌ ПРОБЛЕМА: Ваш аккаунт имеет ID={real_you.id}, а не 1")
            else:
                print(f"\n❌ ПРОБЛЕМА: Пользователь с telegram_id=788139267 НЕ НАЙДЕН!")
                print(f"   Возможно, ID 3 - это ваш аккаунт с битым telegram_id")
        else:
            print("\n✅ Пользователь ID 3 не найден")


async def manual_fix():
    """Ручное исправление"""
    print("\n" + "="*60)
    print("🔧 РУЧНОЕ ИСПРАВЛЕНИЕ")
    print("="*60)
    
    async with engine.begin() as conn:
        # Проверяем, есть ли уже купон для вас
        result = await conn.execute(
            select(DiscountCoupon).where(
                DiscountCoupon.user_id == 1,
                DiscountCoupon.source_user_id == 7
            )
        )
        existing = result.first()
        
        if existing:
            print(f"\n⚠️ Купон уже существует: {existing}")
        else:
            print("\n✅ Создаем недостающий купон...")
            await conn.execute(
                insert(DiscountCoupon).values(
                    user_id=1,
                    source_user_id=7,
                    used=False,
                    created_at=datetime.now()
                )
            )
            
            # Обновляем referred_by у Саввы
            await conn.execute(
                update(User)
                .where(User.id == 7)
                .values(referred_by=1)
            )
            
            await conn.commit()
            print("✅ Награда добавлена вручную!")


if __name__ == "__main__":
    asyncio.run(simulate_referral_flow())
    asyncio.run(check_problematic_user())