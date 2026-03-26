"""
Скрипт для просмотра содержимого базы данных
"""
import asyncio
from database import engine, User, Generation, Payment, ReferralReward
from sqlalchemy import select, func
from datetime import datetime


async def check_db():
    """Просмотр содержимого базы данных"""
    try:
        async with engine.begin() as conn:
            # Пользователи
            result = await conn.execute(select(User))
            users = result.fetchall()
            print(f"\n{'='*60}")
            print(f"👥 ПОЛЬЗОВАТЕЛИ (всего: {len(users)})")
            print(f"{'='*60}")
            if users:
                for user in users:
                    print(f"  ID: {user.id}")
                    print(f"    Telegram ID: {user.telegram_id}")
                    print(f"    Имя: {user.first_name} {user.last_name or ''}")
                    print(f"    Username: @{user.username or 'нет'}")
                    print(f"    Бесплатных генераций: {user.free_generations_left}")
                    print(f"    Premium: {'Да' if user.is_premium else 'Нет'}")
                    print(f"    Реферальный код: {user.referral_code}")
                    print(f"    Реферер: {user.referred_by or 'нет'}")
                    print(f"    Создан: {user.created_at}")
                    print()
            else:
                print("  Пользователей нет")
            
            # Генерации
            result = await conn.execute(select(Generation).order_by(Generation.created_at.desc()).limit(20))
            generations = result.fetchall()
            print(f"\n{'='*60}")
            print(f"🎨 ГЕНЕРАЦИИ (последние 20 из всех)")
            print(f"{'='*60}")
            if generations:
                for gen in generations:
                    print(f"  ID: {gen.id}")
                    print(f"    User ID: {gen.user_id}")
                    print(f"    Статус: {gen.status}")
                    print(f"    Промпт: {gen.prompt[:60]}{'...' if len(gen.prompt) > 60 else ''}")
                    print(f"    Изображений: {gen.images_count}")
                    if gen.error_message:
                        print(f"    Ошибка: {gen.error_message[:50]}...")
                    print(f"    Создано: {gen.created_at}")
                    print()
            else:
                print("  Генераций нет")
            
            # Статистика по генерациям
            result = await conn.execute(
                select(
                    Generation.status,
                    func.count(Generation.id).label('count')
                ).group_by(Generation.status)
            )
            stats = result.fetchall()
            if stats:
                print(f"\n📊 Статистика генераций:")
                for stat in stats:
                    print(f"  {stat.status}: {stat.count}")
            
            # Платежи
            result = await conn.execute(select(Payment).order_by(Payment.created_at.desc()).limit(10))
            payments = result.fetchall()
            print(f"\n{'='*60}")
            print(f"💳 ПЛАТЕЖИ (последние 10)")
            print(f"{'='*60}")
            if payments:
                for pay in payments:
                    print(f"  ID: {pay.id}")
                    print(f"    User ID: {pay.user_id}")
                    print(f"    Сумма: {pay.amount} {pay.currency}")
                    print(f"    Провайдер: {pay.provider}")
                    print(f"    Статус: {pay.status}")
                    print(f"    Payment ID: {pay.payment_id}")
                    print(f"    Создан: {pay.created_at}")
                    print()
            else:
                print("  Платежей нет")
            
            # Реферальные награды
            result = await conn.execute(select(ReferralReward).order_by(ReferralReward.created_at.desc()).limit(10))
            rewards = result.fetchall()
            print(f"\n{'='*60}")
            print(f"🎁 РЕФЕРАЛЬНЫЕ НАГРАДЫ (последние 10)")
            print(f"{'='*60}")
            if rewards:
                for reward in rewards:
                    print(f"  ID: {reward.id}")
                    print(f"    Реферер ID: {reward.referrer_id}")
                    print(f"    Приглашенный ID: {reward.referred_id}")
                    print(f"    Награда: {reward.reward_amount} ({reward.reward_type})")
                    print(f"    Создано: {reward.created_at}")
                    print()
            else:
                print("  Реферальных наград нет")
            
            print(f"\n{'='*60}")
            print("✅ Просмотр завершен")
            print(f"{'='*60}\n")
            
    except Exception as e:
        print(f"\n❌ Ошибка при просмотре БД: {e}")
        print("Убедитесь, что база данных существует (запустите бота хотя бы раз)")


if __name__ == "__main__":
    asyncio.run(check_db())

