"""
Обработчики команд и сообщений бота
"""
import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_session, DatabaseService
from image_generator import ImageGenerator
from sticker_processor import StickerProcessor
from payment_service import PaymentService
from config import settings

logger = logging.getLogger(__name__)

router = Router()

# Состояния FSM
class GenerationStates(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_referral = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    await state.clear()
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        # Получаем или создаем пользователя
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        
        # Проверяем реферальный код в аргументах
        if len(message.text.split()) > 1:
            referral_code = message.text.split()[1]
            await db_service.process_referral(referral_code, user.id)
        
        # Получаем статистику
        stats = await db_service.get_user_stats(user.id)
        
        welcome_text = (
            f"👋 Привет, {message.from_user.first_name or 'друг'}!\n\n"
            f"Я бот для генерации стикеров по текстовому описанию.\n\n"
            f"📊 Твоя статистика:\n"
            f"• Бесплатных генераций: {stats['free_generations_left']}\n"
            f"• Всего генераций: {stats['total_generations']}\n"
            f"• Успешных: {stats['completed_generations']}\n"
            f"• Рефералов: {stats['referrals_count']}\n\n"
            f"🎁 Твой реферальный код: `{stats['referral_code']}`\n"
            f"Поделись им с друзьями и получай бонусы!\n\n"
            f"Используй /generate чтобы начать генерацию стикеров."
        )
        
        await message.answer(welcome_text, parse_mode="Markdown")
    finally:
        await session.close()


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext):
    """Обработка команды /generate"""
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        
        stats = await db_service.get_user_stats(user.id)
        
        if stats['free_generations_left'] > 0 or stats['is_premium']:
            await message.answer(
                "✍️ Отправь текстовое описание стикеров, которые хочешь создать.\n\n"
                "Например: 'Кот в космосе' или 'Смайлик с пиццей'"
            )
            await state.set_state(GenerationStates.waiting_for_prompt)
        else:
            await message.answer(
                "❌ У тебя закончились бесплатные генерации.\n\n"
                "Используй /buy чтобы купить пак генераций."
            )
    finally:
        await session.close()


@router.message(GenerationStates.waiting_for_prompt)
async def process_prompt(message: Message, state: FSMContext):
    """Обработка промпта от пользователя"""
    prompt = message.text
    
    if not prompt or len(prompt) < 3:
        await message.answer("❌ Промпт слишком короткий. Попробуй еще раз.")
        return
    
    if len(prompt) > 500:
        await message.answer("❌ Промпт слишком длинный (максимум 500 символов).")
        return
    
    # Отправляем сообщение о начале генерации
    status_msg = await message.answer("⏳ Генерирую изображения... Это может занять некоторое время.")
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        # Используем бесплатную генерацию
        can_generate = await db_service.use_free_generation(user.id)
        
        if not can_generate and not (await db_service.get_user_stats(user.id))['is_premium']:
            await status_msg.edit_text("❌ У тебя закончились бесплатные генерации.")
            await state.clear()
            return
        
        # Создаем запись о генерации
        generation = await db_service.create_generation(user.id, prompt)
        
        try:
            # Генерируем изображения
            image_generator = ImageGenerator()
            images = await image_generator.generate_images(prompt, count=5)
            
            if not images:
                raise Exception("Не удалось сгенерировать изображения")
            
            await status_msg.edit_text("🎨 Обрабатываю изображения в стикеры...")
            
            # Обрабатываем в стикеры
            sticker_processor = StickerProcessor()
            output_dir = settings.STICKERS_DIR / f"pack_{generation.id}"
            stickers = await sticker_processor.process_to_stickers(images, output_dir)
            
            if not stickers:
                raise Exception("Не удалось обработать изображения")
            
            # Отправляем стикеры пользователю
            await status_msg.edit_text(f"✅ Готово! Отправляю {len(stickers)} стикеров...")
            
            sent_stickers = []
            for sticker_path in stickers:
                try:
                    with open(sticker_path, 'rb') as sticker_file:
                        sent_sticker = await message.answer_sticker(sticker_file)
                        sent_stickers.append(sent_sticker.sticker.file_id)
                except Exception as e:
                    logger.error(f"Ошибка отправки стикера {sticker_path}: {e}")
            
            # Обновляем статус генерации
            await db_service.update_generation(
                generation.id,
                status="completed",
                images_count=len(sent_stickers)
            )
            
            await status_msg.edit_text(
                f"✅ Готово! Создано {len(sent_stickers)} стикеров.\n\n"
                f"💡 Совет: Используй /createpack чтобы создать стикер-пак из этих стикеров."
            )
            
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}", exc_info=True)
            await db_service.update_generation(
                generation.id,
                status="failed",
                error_message=str(e)
            )
            await status_msg.edit_text(
                f"❌ Произошла ошибка при генерации: {str(e)}\n\n"
                f"Попробуй еще раз или обратись в поддержку."
            )
        
        finally:
            await state.clear()
    finally:
        await session.close()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показать статистику пользователя"""
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        stats = await db_service.get_user_stats(user.id)
        
        stats_text = (
            f"📊 Твоя статистика:\n\n"
            f"🎁 Бесплатных генераций: {stats['free_generations_left']}\n"
            f"📦 Всего генераций: {stats['total_generations']}\n"
            f"✅ Успешных: {stats['completed_generations']}\n"
            f"👥 Рефералов: {stats['referrals_count']}\n"
            f"🎫 Реферальный код: `{stats['referral_code']}`\n"
            f"{'⭐ Premium статус: активен' if stats['is_premium'] else ''}"
        )
        
        await message.answer(stats_text, parse_mode="Markdown")
    finally:
        await session.close()


@router.message(Command("referral"))
async def cmd_referral(message: Message):
    """Показать реферальную информацию"""
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        stats = await db_service.get_user_stats(user.id)
        
        referral_text = (
            f"🎁 Реферальная система\n\n"
            f"Твой реферальный код: `{stats['referral_code']}`\n\n"
            f"Поделись ссылкой с друзьями:\n"
            f"`https://t.me/{message.bot.username}?start={stats['referral_code']}`\n\n"
            f"За каждого друга, который использует твой код, ты получишь:\n"
            f"• +1 бесплатная генерация\n\n"
            f"Всего рефералов: {stats['referrals_count']}"
        )
        
        await message.answer(referral_text, parse_mode="Markdown")
    finally:
        await session.close()


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    """Покупка генераций"""
    payment_service = PaymentService()
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        # В MVP просто показываем информацию
        # В продакшене здесь будет создание платежа
        buy_text = (
            f"💳 Покупка генераций\n\n"
            f"Цена пакета (5 генераций): {settings.STICKER_PACK_PRICE} ₽\n\n"
            f"В MVP режиме оплата пока не реализована.\n"
            f"Используй бесплатные генерации или реферальную систему!"
        )
        
        await message.answer(buy_text)
    finally:
        await session.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам"""
    help_text = (
        "📖 Справка по командам:\n\n"
        "/start - Начать работу с ботом\n"
        "/generate - Создать стикеры по текстовому описанию\n"
        "/stats - Показать статистику\n"
        "/referral - Реферальная система\n"
        "/buy - Купить генерации\n"
        "/help - Эта справка\n\n"
        "💡 Просто отправь текстовое описание после команды /generate, "
        "и я создам для тебя стикеры!"
    )
    
    await message.answer(help_text)


@router.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Не понимаю эту команду.\n\n"
        "Используй /help чтобы увидеть список доступных команд."
    )

