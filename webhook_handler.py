from aiohttp import web
import logging
from yookassa_payment import get_yookassa_payment
from database import get_session
from db_service import DatabaseService

logger = logging.getLogger(__name__)

async def yookassa_webhook(request):
    """Обработчик вебхука от ЮKassa"""
    try:
        data = await request.json()
        logger.info(f"Yookassa webhook received: {data}")
        
        event = data.get('event')
        payment_id = data.get('object', {}).get('id')
        
        if event == 'payment.succeeded' and payment_id:
            # Получаем информацию о платеже
            payment_info = get_yookassa_payment(payment_id)
            
            if payment_info and payment_info.paid:
                metadata = payment_info.metadata
                telegram_id = int(metadata.get('telegram_id', 0))
                user_id = int(metadata.get('user_id', 0))
                
                if telegram_id:
                    session = await get_session()
                    try:
                        db_service = DatabaseService(session)
                        
                        # Добавляем генерации пользователю
                        await db_service.add_paid_generations(user_id, 1)
                        
                        # Сохраняем информацию о платеже
                        await db_service.save_payment(
                            user_id=user_id,
                            payment_id=payment_id,
                            amount=int(float(payment_info.amount.value) * 100),  # в копейки
                            currency="RUB",
                            generations_added=1,
                            provider="yookassa",
                        )
                        
                        logger.info(f"Payment {payment_id} processed for user {telegram_id}")
                        
                    finally:
                        await session.close()
        
        return web.Response(status=200)
        
    except Exception as e:
        logger.error(f"Error in yookassa webhook: {e}")
        return web.Response(status=500)
        