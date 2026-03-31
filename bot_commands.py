from aiogram.types import BotCommand

async def set_bot_commands(bot):
    """Установка команд для кнопки меню"""
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="generate", description="🎨 Создать стикерпак"),
        BotCommand(command="stats", description="📊 Моя статистика"),
        BotCommand(command="referral", description="🎁 Реферальная система"),
        BotCommand(command="buy", description="💳 Купить генерации"),
        BotCommand(command="history", description="📜 История платежей"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands)