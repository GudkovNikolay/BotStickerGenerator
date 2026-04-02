"""
Главный файл запуска бота
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import settings
from database import init_db
from handlers import router
from bot_commands import set_bot_commands
from aiogram.types import MenuButtonCommands
from webhook_handler import yookassa_webhook
from aiohttp import web

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Добавьте в основной файл бота
async def start_webhook():
    app = web.Application()
    app.router.add_post('/yookassa-webhook', yookassa_webhook)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    
    logger.info("Webhook server started on port 8000")

async def main():
    """Главная функция запуска бота"""
    # Инициализация базы данных
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных инициализирована")
    
    # Создание бота и диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    logger.info(1)
    
    await set_bot_commands(bot)
    logger.info(2)
    await bot.set_chat_menu_button(
        menu_button=MenuButtonCommands()
    )
    logger.info('try webhook')
    await start_webhook()
    logger.info('webhook succesful')

    dp = Dispatcher()
    dp.include_router(router)
    
    # Запуск бота
    logger.info("Запуск бота...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)



