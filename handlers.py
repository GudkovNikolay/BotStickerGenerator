"""
Обработчики команд и сообщений бота
"""
from aiogram.types import FSInputFile, InputSticker, InputFile
import logging
from aiogram import Router
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import get_session
from db_service import DatabaseService
from image_generator import ImageGenerator
from sticker_processor import StickerProcessor
from payment_service import PaymentService
from config import settings
import os
import asyncio
import numpy as np
from PIL import Image
import tempfile
from pathlib import Path
from io import BytesIO
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F 

logger = logging.getLogger(__name__)

router = Router()

# Состояния FSM
class GenerationStates(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_referral = State()
    waiting_for_pack_name = State()
    waiting_for_payment_method = State()


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
            # Убеждаемся, что тестовый режим выключен
            await state.update_data(test_mode=False)
        else:
            await message.answer(
                "❌ У тебя закончились бесплатные генерации.\n\n"
                "Используй /buy чтобы купить пак генераций."
            )
    finally:
        await session.close()


@router.message(Command("test_generate"))
async def cmd_test_generate(message: Message, state: FSMContext):
    """Тестовая команда для ускоренной генерации (белый шум)"""
    # Проверяем, что пользователь администратор (если нужно)
    # if message.from_user.id not in settings.ADMIN_IDS:
    #     await message.answer("❌ У вас нет прав для использования этой команды")
    #     return
    
    await message.answer(
        "🧪 Тестовый режим активирован.\n"
        "✍️ Отправь текстовое описание (будет сгенерирован белый шум)"
    )
    await state.set_state(GenerationStates.waiting_for_prompt)
    # Сохраняем флаг тестового режима
    await state.update_data(test_mode=True)


async def generate_test_images(count: int = 5) -> list:
    """
    Генерирует тестовые изображения (белый шум)
    Возвращает список путей к временным файлам
    """
    images = []
    
    # Создаем временную директорию для тестовых изображений
    temp_dir = settings.TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Генерация {count} тестовых изображений в {temp_dir}")
    
    for i in range(count):
        try:
            # Создаем изображение с белым шумом (RGB)
            img_array = np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8)
            img = Image.fromarray(img_array)
            
            # Сохраняем во временный файл
            temp_path = temp_dir / f"test_image_{i}_{int(asyncio.get_event_loop().time() * 1000)}.png"
            img.save(temp_path, format="PNG")
            
            # Проверяем, что файл создан и не пустой
            if temp_path.exists() and temp_path.stat().st_size > 0:
                images.append(str(temp_path))
                logger.info(f"Тестовое изображение сохранено: {temp_path}, размер: {temp_path.stat().st_size} байт")
            else:
                logger.error(f"Файл не создан или пустой: {temp_path}")
                
        except Exception as e:
            logger.error(f"Ошибка при создании тестового изображения {i}: {e}")
            continue
    
    logger.info(f"Сгенерировано {len(images)} тестовых изображений")
    return images


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
    
    # Получаем данные состояния
    state_data = await state.get_data()
    test_mode = state_data.get('test_mode', False)
    
    status_msg = None
    if test_mode:
        await message.answer("🧪 Тестовый режим: генерирую белый шум...")
    else:
        # Отправляем сообщение о начале генерации
        status_msg = await message.answer("⏳ Генерирую изображения... Это может занять некоторое время.")
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        # В тестовом режиме пропускаем проверку лимитов
        if not test_mode:
            # Используем бесплатную генерацию
            can_generate = await db_service.use_free_generation(user.id)
            
            if not can_generate and not (await db_service.get_user_stats(user.id))['is_premium']:
                await status_msg.edit_text("❌ У тебя закончились бесплатные генерации.")
                await state.clear()
                return
        
        # Создаем запись о генерации
        generation = await db_service.create_generation(user.id, prompt)
        
        try:
            if test_mode:
                # Тестовая генерация - белый шум
                logger.info("Запуск тестовой генерации")
                await asyncio.sleep(1)  # Имитация задержки
                images = await generate_test_images(count=5)
                logger.info(f"Тестовая генерация завершена, получено {len(images)} изображений")
                
                if not images:
                    raise Exception("Не удалось сгенерировать тестовые изображения")
                
                if status_msg:
                    await status_msg.edit_text("🧪 Тестовые изображения сгенерированы")
            else:
                # Реальная генерация
                image_generator = ImageGenerator()
                images = await image_generator.generate_images(prompt, count=5)
                
                if not images:
                    raise Exception("Не удалось сгенерировать изображения")
                
                await status_msg.edit_text("🎨 Обрабатываю изображения в стикеры...")
            
            # Проверяем, что images - это список путей
            logger.info(f"Получено {len(images)} изображений для обработки")
            for i, img_path in enumerate(images):
                logger.info(f"Изображение {i}: {img_path}")
                if not os.path.exists(img_path):
                    logger.error(f"Файл не существует: {img_path}")
                elif os.path.getsize(img_path) == 0:
                    logger.error(f"Файл пустой: {img_path}")
            
            # Обрабатываем в стикеры
            sticker_processor = StickerProcessor()
            output_dir = settings.STICKERS_DIR / f"pack_{generation.id}"
            stickers = await sticker_processor.process_to_stickers(images, output_dir)
            
            logger.info(f"Обработано стикеров: {len(stickers) if stickers else 0}")
            
            if not stickers:
                raise Exception("Не удалось обработать изображения в стикеры")
            
            # Проверяем созданные стикеры
            for i, sticker_path in enumerate(stickers):
                logger.info(f"Стикер {i}: {sticker_path}")
                if not os.path.exists(sticker_path):
                    logger.error(f"Стикер не существует: {sticker_path}")
                elif os.path.getsize(sticker_path) == 0:
                    logger.error(f"Стикер пустой: {sticker_path}")
            
            # Отправляем стикеры пользователю
            if not test_mode and status_msg:
                await status_msg.edit_text(f"✅ Готово! Создаю стикер-пак из {len(stickers)} стикеров...")
            else:
                await message.answer(f"🧪 Готово! Создаю стикер-пак из {len(stickers)} тестовых стикеров...")
            
    # Создаем стикер-пак с правильным именем
            import time
            import re
            import hashlib
            
            # Получаем username бота (без @)
            bot_info = await message.bot.me()
            bot_username = bot_info.username
            # bot_username = message.bot.username
            if bot_username.startswith('@'):
                bot_username = bot_username[1:]
            
            # Очищаем промпт для использования в имени
            # Берем первые 20 символов промпта, удаляем недопустимые символы
            clean_prompt = re.sub(r'[^a-zA-Z0-9]', '', prompt[:20].lower())
            if not clean_prompt:  # Если после очистки ничего не осталось
                clean_prompt = "sticker"
            
            # Создаем уникальный хеш на основе времени и ID генерации
            unique_hash = hashlib.md5(f"{user.telegram_id}_{generation.id}_{time.time()}".encode()).hexdigest()[:8]
            
            # Формируем базовое имя: начинается с буквы, содержит только допустимые символы
            base_name = f"{clean_prompt}_{unique_hash}"
            
            # Убеждаемся, что имя начинается с буквы
            if base_name[0].isdigit():
                base_name = "s" + base_name
            
            # Добавляем обязательный суффикс _by_<bot_username>
            pack_name = f"{base_name}_by_{bot_username}"
            
            # Обрезаем до максимальной длины (64 символа)
            if len(pack_name) > 64:
                # Если слишком длинное, укорачиваем base_name
                max_base_len = 64 - len(f"_by_{bot_username}")
                base_name = base_name[:max_base_len]
                pack_name = f"{base_name}_by_{bot_username}"
            
            # Проверяем на последовательные подчеркивания
            while '__' in pack_name:
                pack_name = pack_name.replace('__', '_')
            
            pack_title = f"Стикеры: {prompt[:30]}..."
            
            logger.info(f"Создание стикер-пака с именем: {pack_name}")
            
            # Подготавливаем стикеры для загрузки
            input_stickers = []
            for i, sticker_path in enumerate(stickers):
                try:
                    if not os.path.exists(sticker_path) or os.path.getsize(sticker_path) == 0:
                        logger.error(f"Файл не существует или пустой: {sticker_path}")
                        continue
                    
                    sticker_file = FSInputFile(sticker_path)
                    
                    # Для разных стикеров можно использовать разные эмодзи
                    # Здесь можно добавить логику выбора эмодзи на основе содержимого
                    emoji_list = ["🤖"]  # Эмодзи по умолчанию
                    
                    input_sticker = InputSticker(
                        sticker=sticker_file,
                        format="static",
                        emoji_list=emoji_list
                    )
                    input_stickers.append(input_sticker)
                    logger.info(f"Стикер {i} подготовлен для загрузки: {sticker_path}")
                    
                except Exception as e:
                    logger.error(f"Ошибка подготовки стикера {sticker_path}: {e}", exc_info=True)
                    continue
            
            logger.info(f"Подготовлено {len(input_stickers)} стикеров для загрузки")
            
            if input_stickers:
                try:
                    result = await message.bot.create_new_sticker_set(
                        user_id=message.from_user.id,
                        name=pack_name,
                        title=pack_title,
                        stickers=input_stickers,
                        sticker_format="static"
                    )
                    
                    if result:
                        pack_link = f"https://t.me/addstickers/{pack_name}"
                        
                        success_text = f"✅ Стикер-пак успешно создан!\n\n📦 Название: {pack_title}\n🔗 Ссылка: {pack_link}\n\nКоличество стикеров: {len(input_stickers)}"
                        
                        if test_mode:
                            await message.answer(f"🧪 Тестовый режим: {success_text}")
                        else:
                            await status_msg.edit_text(success_text)
                        
                        await db_service.update_generation(
                            generation.id,
                            status="completed",
                            images_count=len(input_stickers),
                            sticker_pack_name=pack_name
                        )
                        
                        logger.info(f"Стикер-пак {pack_name} успешно создан")
                    else:
                        raise Exception("Не удалось создать стикер-пак")
                        
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Ошибка создания стикер-пака: {error_msg}", exc_info=True)
                    
                    # Анализируем ошибку
                    if "PACK_SHORT_NAME_INVALID" in error_msg:
                        error_text = f"❌ Неверный формат имени пака. Имя должно заканчиваться на '_by_{bot_username}'"
                    elif "PACK_SHORT_NAME_OCCUPIED" in error_msg:
                        error_text = "❌ Пак с таким именем уже существует. Попробуйте еще раз (имя генерируется автоматически)"
                    else:
                        error_text = f"⚠️ Ошибка создания стикер-пака: {error_msg}\n\nОтправляю стикеры по отдельности:"
                    
                    if test_mode:
                        await message.answer(error_text)
                    else:
                        await status_msg.edit_text(error_text)
                    
                    # Отправляем стикеры по отдельности
                    for sticker_path in stickers:
                        try:
                            if os.path.exists(sticker_path) and os.path.getsize(sticker_path) > 0:
                                sticker_file = FSInputFile(sticker_path)
                                await message.answer_sticker(sticker_file)
                                await asyncio.sleep(0.3)
                        except Exception as send_error:
                            logger.error(f"Ошибка отправки стикера: {send_error}")
            else:
                raise Exception("Нет валидных стикеров для создания пака")
    
            
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}", exc_info=True)
            await db_service.update_generation(
                generation.id,
                status="failed",
                error_message=str(e)
            )
            error_msg = f"❌ Произошла ошибка при генерации"
            if test_mode:
                error_msg = f"🧪 {error_msg} (тестовый режим)"
            error_msg += f": {str(e)}\n\nПопробуй еще раз или обратись в поддержку."
            
            if not test_mode and status_msg:
                await status_msg.edit_text(error_msg)
            else:
                await message.answer(error_msg)
        
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
async def cmd_buy(message: Message, state: FSMContext):
    """Выбор способа оплаты"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Банковская карта ({settings.STICKER_PACK_PRICE} руб)", callback_data="pay_card")],
        [InlineKeyboardButton(text=f"⭐ Звезды Telegram ({settings.STICKER_PACK_STARS_PRICE})", callback_data="pay_stars")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="cancel")]
    ])
    
    await message.answer(
        f"💳 Выберите способ оплаты\n\n"
        f"Пакет: {settings.STICKER_PACK_COUNT} генераций\n"
        f"Цена: {settings.STICKER_PACK_PRICE} ₽ или {settings.STICKER_PACK_STARS_PRICE} ⭐",
        reply_markup=keyboard
    )
    await state.set_state(GenerationStates.waiting_for_payment_method)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам"""
    help_text = (
        "📖 Справка по командам:\n\n"
        "/start - Начать работу с ботом\n"
        "/generate - Создать стикер-пак по текстовому описанию\n"
        "/stats - Показать статистику\n"
        "/referral - Реферальная система\n"
        "/buy - Купить генерации\n"
        "/help - Эта справка\n"
        "/test_generate - (Тест) Быстрая генерация с белым шумом\n\n"
        "💡 После генерации стикеры автоматически собираются в стикер-пак!"
    )
    
    await message.answer(help_text)

@router.callback_query(lambda c: c.data == "pay_card")
async def process_card_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты картой"""
    # Создание счета через провайдера
    prices = [LabeledPrice(label="Пакет генераций", amount=settings.STICKER_PACK_PRICE * 100)]  # в копейках
    
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Пакет генераций стикеров",
        description=f"{settings.STICKER_PACK_COUNT} генераций стикеров",
        payload=f"generation_pack_{callback.from_user.id}",
        provider_token=settings.PAYMENTS_PROVIDER_TOKEN,
        currency=settings.CURRENCY,
        prices=prices,
        start_parameter="create_sticker_pack",
        need_email=False,
        need_phone_number=False,
        need_shipping_address=False,
        is_flexible=False,
        photo_url="https://example.com/sticker_preview.jpg",
        photo_width=500,
        photo_height=500
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "pay_stars")
async def process_stars_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты звездами Telegram"""
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Пакет генераций стикеров",
        description=f"{settings.STICKER_PACK_COUNT} генераций стикеров",
        payload=f"stars_pack_{callback.from_user.id}",
        provider_token=None,  # для звезд token не нужен
        currency="XTR",  # специальная валюта для звезд
        prices=[LabeledPrice(label="Пакет генераций", amount=settings.STICKER_PACK_STARS_PRICE)],
        start_parameter="create_sticker_pack"
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Подтверждение платежа"""
    await pre_checkout_query.bot.answer_pre_checkout_query(
        pre_checkout_query.id, 
        ok=True
    )

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """Обработка успешного платежа"""
    payment_info = message.successful_payment
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        # Определяем количество генераций в зависимости от суммы
        if payment_info.currency == "XTR":
            generations_to_add = payment_info.total_amount // settings.STICKER_PACK_STARS_PRICE * settings.STICKER_PACK_COUNT
        else:
            generations_to_add = (payment_info.total_amount // 100) // settings.STICKER_PACK_PRICE * settings.STICKER_PACK_COUNT
        
        # Добавляем генерации пользователю
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        # Обновляем количество генераций (добавьте метод в db_service)
        await db_service.add_generations(user.id, generations_to_add)
        
        # Сохраняем информацию о платеже
        await db_service.save_payment(
            user_id=user.id,
            payment_id=payment_info.provider_payment_charge_id or payment_info.telegram_payment_charge_id,
            amount=payment_info.total_amount,
            currency=payment_info.currency,
            generations_added=generations_to_add
        )
        
        await message.answer(
            f"✅ Оплата прошла успешно!\n\n"
            f"Вам добавлено {generations_to_add} генераций.\n"
            f"Используйте /generate для создания стикеров!"
        )
    finally:
        await session.close()

@router.message(Command("history"))
async def cmd_history(message: Message):
    """История платежей"""
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        user = await db_service.get_or_create_user(telegram_id=message.from_user.id)
        payments = await db_service.get_payment_history(user.id)
        
        if not payments:
            await message.answer("📭 История платежей пуста")
            return
        
        text = "📊 История платежей:\n\n"
        for p in payments:
            text += f"• {p.created_at.strftime('%d.%m.%Y')}: {p.generations_added} ген. - {p.amount/100} {p.currency}\n"
        
        await message.answer(text)
    finally:
        await session.close()

@router.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Не понимаю эту команду.\n\n"
        "Используй /help чтобы увидеть список доступных команд."
    )
    