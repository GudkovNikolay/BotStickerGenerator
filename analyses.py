"""
Скрипт для быстрой аналитики базы данных
"""
import asyncio
from database import engine, User, Payment
from sqlalchemy import select, func


async def get_analytics():
    """Быстрая аналитика: уникальные платящие пользователи, всего пользователей, общий доход"""
    try:
        async with engine.begin() as conn:
            # Получаем все метрики одним запросом
            result = await conn.execute(
                select(
                    func.count(func.distinct(User.id)).label('total_users'),
                    func.count(func.distinct(Payment.user_id)).filter(Payment.status == 'succeeded').label('paying_users'),
                    func.sum(Payment.amount).filter(Payment.status == 'succeeded').label('total_revenue')
                )
            )
            stats = result.first()
            
            print(f"\n{'='*50}")
            print(f"📊 АНАЛИТИКА БОТА")
            print(f"{'='*50}")
            print(f"👥 Всего уникальных пользователей: {stats.total_users}")
            print(f"💰 Уникальных платящих пользователей: {stats.paying_users or 0}")
            print(f"💵 Всего заработано: {stats.total_revenue or 0:.2f} ₽")
            
            if stats.total_users > 0:
                conversion = (stats.paying_users or 0) / stats.total_users * 100
                print(f"📈 Конверсия в платеж: {conversion:.1f}%")
            
            print(f"{'='*50}\n")
            
    except Exception as e:
        print(f"\n❌ Ошибка при получении аналитики: {e}")
        print("Убедитесь, что база данных существует (запустите бота хотя бы раз)")


if __name__ == "__main__":
    asyncio.run(get_analytics())