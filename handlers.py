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
import time
from PIL import Image
import tempfile
from pathlib import Path
from io import BytesIO
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F 
from typing import Dict, Any, List
import re
import httpx
from emoji_manager import EmojiManager
logger = logging.getLogger(__name__)

router = Router()

# Состояния FSM
class GenerationStates(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_referral = State()
    waiting_for_pack_name = State()
    waiting_for_payment_method = State()
    waiting_for_form_data = State()  # Ожидание заполненной формы
    confirming_form = State()        # Подтверждение формы



@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    await state.clear()
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        
        if len(message.text.split()) > 1:
            referral_code = message.text.split()[1]
            await db_service.process_referral(referral_code, user.id)
        
        stats = await db_service.get_user_stats(user.id)
        
        # Получаем username бота
        bot_info = await message.bot.get_me()
        bot_username = bot_info.username
        
        # Формируем текст для поделиться
        referral_link = f"https://t.me/{bot_username}?start={stats['referral_code']}"
        share_text = f"Сгенерируй стикерпак с помощью этого бота"
        f"Перейди по этой ссылке и получи скидку 50% на первый пак: {referral_link}"
        
        welcome_text = (
            f"Привет!\n\n"
            f"Это бот для генерации стикер-паков по текстовому описанию.\n\n"
            f"Расскажи о боте друзьям, чтобы получить скидку!\n\n"
            f"Если друг перейдет по твоей ссылке (кнопка внизу), и ты и он получите скидку 50% на стикер-пак.\n\n"
            f"Приведи несколько друзей, за каждого нового друга ты получаешь ещё один стикер-пак со скидкой 50%! :) \n\n"
            f"Сгенерируй свой первый пак с помощью команды /generate"
        )
        
        # Кнопка для поделиться с предзаполненным текстом
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔗 Поделиться ссылкой",
                switch_inline_query=share_text  # Будет открыто окно выбора чата с этим текстом
            )],
        ])
        
        await message.answer(
            welcome_text, 
            parse_mode="Markdown",
            reply_markup=keyboard
        )
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
        # Получаем username бота
        bot_info = await message.bot.get_me()
        bot_username = bot_info.username

        referral_link = f"https://t.me/{bot_username}?start={stats['referral_code']}"

        stats_text = (
            f"📊 Твоя статистика:\n\n"
            # f"🎁 Бесплатных генераций: {stats['free_generations_left']}\n"
            f"📦 Всего генераций: {stats['total_generations']}\n"
            f"✅ Успешных: {stats['completed_generations']}\n"
            f"👥 Рефералов: {stats['referrals_count']}\n"
            f"🎫 Реферальная ссылка: `{referral_link}`\n"
            # f"{'⭐ Premium статус: активен' if stats['is_premium'] else ''}"
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
        
        # Получаем username бота правильно
        bot_info = await message.bot.get_me()
        bot_username = bot_info.username
        
        referral_text = (
            f"🎁 Реферальная система\n\n"

            f"Поделись ссылкой с друзьями:\n"
            f"`https://t.me/{bot_username}?start={stats['referral_code']}`\n\n"
            f"За каждого друга, который использует твой код, и ты и он получите скидку 50% на стикерпак\n\n"
            # f"• +1 бесплатная генерация\n\n"
            # f"Всего рефералов: {stats['referrals_count']}"
        )
        
        await message.answer(referral_text, parse_mode="Markdown")
    finally:
        await session.close()


@router.message(Command("buy"))
async def cmd_buy(message: Message, state: FSMContext):
    """Выбор способа оплаты"""
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        
        user = await db_service.get_or_create_user(
            telegram_id=message.from_user.id
        )
        
        # Получаем информацию о скидке
        discount = await db_service.get_user_discount(user.id)
        
        original_price = settings.STICKER_PACK_PRICE
        final_price = original_price
        
        if discount['has_discount']:
            final_price = original_price * (100 - discount['discount_percent']) / 100
            discount_text = (
                f"\n\n🎉 *У вас скидка {discount['discount_percent']}%!*\n"
                f"Причина: {discount['reason']}\n"
                f"Цена со скидкой: {final_price:.0f} ₽"
            )
        else:
            discount_text = "\n\n🎁 *Приведи друга и получи скидку 50%!*\nИспользуй /referral"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Оплатить {final_price:.0f} ₽", 
                callback_data=f"pay_card_{final_price}"
            )],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="cancel")]
        ])
        
        await message.answer(
            f"💳 *Оплата*\n\n"
            f"Пакет: {settings.STICKER_PACK_COUNT} генераций\n"
            f"Цена: {original_price} ₽{discount_text}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await state.set_state(GenerationStates.waiting_for_payment_method)
        
    finally:
        await session.close()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам"""
    help_text = (
        "📖 Справка по командам:\n\n"
        "/start - Начать работу с ботом\n"
        "/generate - Создать стикер-пак\n"
        "/stats - Показать статистику\n"
        "/referral - Реферальная система\n"
        "/buy - Купить генерации\n"
        "/help - Эта справка\n"
    )
    
    await message.answer(help_text)

@router.callback_query(lambda c: c.data.startswith('pay_card_'))
async def process_card_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты картой с учетом скидки"""
    # Извлекаем цену из callback_data
    final_price = float(callback.data.split('_')[2])
    
    # Создание счета
    prices = [LabeledPrice(label="Пакет генераций", amount=int(final_price * 100))]
    
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
            f"Теперь можно перейти к генерации.\n"
            f"Используйте /generate для создания вашего пака!"
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

# ============= НОВЫЙ КОД ДЛЯ СЕТКИ СТИКЕРОВ =============
# Состояния FSM для сетки
class StickerGridStates(StatesGroup):
    waiting_for_theme = State()
    waiting_for_sticker_edit = State()
    waiting_for_description = State()
    waiting_for_caption = State()
    waiting_for_emoji = State()
    confirming = State()
    waiting_for_reference_photo = State()
    waiting_for_emoji_input = State()

class StickerGrid:
    """Класс для управления сеткой стикеров"""
    
    def __init__(self, total_stickers: int = 5):
        self.theme = None#"Не выбрана"
        self.stickers = []
        self.total_stickers = total_stickers
        self.current_editing = 0
        
        # Инициализируем стикеры пустыми значениями
        for i in range(total_stickers):
            self.stickers.append({
                'description': '',  # Пустое описание по умолчанию
                'caption': '',
                'emoji': EmojiManager.get_random_emoji()  # Случайный эмодзи
            })
    
    def to_dict(self):
        return {
            'theme': self.theme,
            'stickers': self.stickers,
            'total_stickers': self.total_stickers,
            'current_editing': self.current_editing
        }
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls(5)
        grid = cls(data.get('total_stickers', 5))
        grid.theme = data.get('theme', 'Не выбрана')
        grid.stickers = data.get('stickers', [])
        grid.current_editing = data.get('current_editing', 0)
        return grid
    
    def has_description(self, index: int) -> bool:
        """Проверяет, есть ли описание у стикера"""
        return bool(self.stickers[index]['description'].strip())
    
    def get_sticker_summary(self, index: int) -> str:
        """Возвращает краткое описание стикера"""
        sticker = self.stickers[index]
        if sticker['description']:
            desc = sticker['description'][:15] + ('...' if len(sticker['description']) > 15 else '')
        else:
            desc = "🔹 не задано"
        caption = f" 💬 {sticker['caption'][:10]}..." if sticker['caption'] else ""
        return f"{sticker['emoji']} {desc}{caption}"
    
    def get_grid_display(self) -> str:
        """Возвращает отображение всей сетки"""
        display = f"📋 **Текущее состояние стикеров**\n"
        display += f"📌 **Тема:** {self.theme}\n\n"
        display += "💡 *Описания можно не заполнять - тогда стикеры будут на общую тему*\n\n"
        
        # Создаем сетку 3x3 (или меньше)
        for i in range(0, self.total_stickers, 3):
            row = []
            for j in range(3):
                if i + j < self.total_stickers:
                    idx = i + j
                    sticker = self.stickers[idx]
                    # Показываем эмодзи и индикатор заполненности
                    # indicator = "✅" if sticker['description'] else "⬜"
                    row.append(f"[{idx+1}] {sticker['emoji']}")
                else:
                    row.append("[ ]")
            display += " | ".join(row) + "\n"
        
        display += "\n" + "─" * 30 + "\n"
        
        # Детали каждого стикера
        for i, sticker in enumerate(self.stickers):
            if sticker['description']:
                display += f"\n**{i+1}.** {sticker['emoji']} *{sticker['description']}*"
            else:
                display += f"\n**{i+1}.** {sticker['emoji']} *будет на общую тему*"
            if sticker['caption']:
                display += f"\n    💬 Надпись на стикере: {sticker['caption']}"
        
        return display


# Найдите и замените существующий обработчик команды /grid
@router.message(Command("generate"))
async def cmd_start_grid(message: Message, state: FSMContext):
    """Запуск создания стикерпака через сетку из 9 стикеров"""
    
    # Создаем новую сетку с 9 стикерами
    grid = StickerGrid(total_stickers=9)
    await state.update_data(grid=grid.to_dict())
    
    # Показываем главное меню
    await show_grid_main(message, state, grid, edit=False)


@router.callback_query(lambda c: c.data.startswith('grid_size_'))
async def process_grid_size(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора размера сетки"""
    
    if callback.data == "grid_cancel":
        await callback.message.edit_text("❌ Создание отменено")
        await state.clear()
        await callback.answer()
        return
    
    # Определяем количество стикеров
    size = int(callback.data.split('_')[2])
    
    # Создаем новую сетку
    grid = StickerGrid(total_stickers=size)
    await state.update_data(grid=grid.to_dict())
    
    # Показываем главное меню
    await show_grid_main(callback.message, state, grid, edit=True)
    await callback.answer()


async def show_grid_main(message: Message, state: FSMContext, grid: StickerGrid, edit: bool = False):
    """Показывает главное меню с сеткой"""

    data = await state.get_data()
    has_reference_photo = bool(data.get("reference_photo_path"))
    display = grid.get_grid_display()
    display += f"\n\n📷 Референс фото {'загружено' if has_reference_photo else 'не загружено'}"
    
    # Создаем клавиатуру с кнопками для каждого стикера
    keyboard_buttons = []
    
    # Добавляем кнопки для стикеров (по рядам)
    for i in range(0, grid.total_stickers, 3):
        row = []
        for j in range(3):
            if i + j < grid.total_stickers:
                idx = i + j
                sticker = grid.stickers[idx]
                # Показываем эмодзи и статус в кнопке
                # status = "✅" if sticker['description'] else "⬜"
                row.append(InlineKeyboardButton(
                    text=f"{idx+1}. {sticker['emoji']}",
                    callback_data=f"grid_edit_{idx}"
                ))
        if row:
            keyboard_buttons.append(row)
    
    # Добавляем кнопки управления
    keyboard_buttons.append([
        InlineKeyboardButton(text="📌 Выбрать тему", callback_data="grid_theme"),
        InlineKeyboardButton(text="👀 Предпросмотр", callback_data="grid_preview")
    ])

    keyboard_buttons.append([
        InlineKeyboardButton(
            text=f"📷 {'Обновить' if has_reference_photo else 'Загрузить'} референс фото",
            callback_data="grid_reference_photo",
        )
    ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="✅ Генерировать!", callback_data="grid_generate"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="grid_cancel")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    action = "Редактирование" if edit else "Текущее состояние"
    
    # Проверяем, можем ли мы редактировать сообщение
    try:
        await message.edit_text(
            f"📋 **{action} стикерпака**\n\n{display}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except:
        # Если не можем редактировать (например, это новое сообщение), отправляем новое
        await message.answer(
            f"📋 **{action} стикерпака**\n\n{display}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


@router.callback_query(lambda c: c.data == "grid_reference_photo")
async def grid_reference_photo(callback: CallbackQuery, state: FSMContext):
    """Попросить пользователя загрузить референсное фото."""
    await state.set_state(StickerGridStates.waiting_for_reference_photo)
    grid = StickerGrid.from_dict((await state.get_data()).get("grid"))

    try:
        await callback.message.edit_text(
            "📷 Отправь референсное фото (желательно с лицом/персонажем).\n\n"
            "После загрузки я буду просить Kie.ai сделать все стикеры с этим персонажем.\n\n"
            "Можно отменить: нажми «◀️ Назад ко всем стикерам».",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад ко всем стикерам", callback_data="grid_reference_back")]]
            ),
        )
    except Exception:
        await callback.message.answer(
            "📷 Отправь референсное фото (желательно с лицом/персонажем).\n\n"
            "После загрузки я буду просить Kie.ai сделать все стикеры с этим персонажем.\n\n"
            "Можно отменить: нажми «◀️ Назад ко всем стикерам».",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад ко всем стикерам", callback_data="grid_reference_back")]]
            ),
        )

    await callback.answer()


@router.callback_query(lambda c: c.data == "grid_reference_back")
async def grid_reference_back(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню сетки без изменения референса."""
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get("grid"))
    await show_grid_main(callback.message, state, grid, edit=True)
    await callback.answer()


@router.message(StickerGridStates.waiting_for_reference_photo)
async def process_reference_photo(message: Message, state: FSMContext):
    """Обработка загруженного референсного фото."""
    if not message.photo:
        await message.answer("Пожалуйста, отправь фото. (Это лучше, чем документ или текст.)")
        return

    # Берём самое большое фото из массива
    photo = message.photo[-1]
    file_id = photo.file_id
    user_id = message.from_user.id

    # Скачиваем файл через Telegram HTTP API
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            get_file_resp = await client.get(
                "https://api.telegram.org/bot{token}/getFile".format(token=settings.BOT_TOKEN),
                params={"file_id": file_id},
            )
            get_file_data = get_file_resp.json()
            if not get_file_data.get("ok"):
                raise RuntimeError(f"Telegram getFile failed: {get_file_data}")

            file_path = get_file_data["result"]["file_path"]

            file_url = "https://api.telegram.org/file/bot{token}/{file_path}".format(
                token=settings.BOT_TOKEN, file_path=file_path
            )
            file_resp = await client.get(file_url)
            if file_resp.status_code != 200:
                raise RuntimeError(f"Telegram file download failed: {file_resp.status_code}")

            content_type = file_resp.headers.get("content-type", "").lower()
            ext = "png" if "png" in content_type else "jpg"

            ref_path = settings.TEMP_DIR / f"grid_reference_{user_id}_{int(time.time() * 1000)}.{ext}"
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_bytes(file_resp.content)

    except Exception as e:
        await message.answer(f"❌ Не удалось скачать референсное фото: {e}")
        return

    await state.update_data(reference_photo_path=str(ref_path))

    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get("grid"))
    await show_grid_main(message, state, grid, edit=True)


@router.callback_query(lambda c: c.data == "grid_theme")
async def grid_edit_theme(callback: CallbackQuery, state: FSMContext):
    """Редактирование общей темы"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    
    await callback.message.edit_text(
        f"📌 **Текущая тема:** {grid.theme}\n\n"
        f"Введите новую общую тему для стикерпака:\n"
        f"Например: *Космические котики* или *Смешные собаки*\n\n"
        f"💡 *Эта тема будет использоваться для всех стикеров, у которых не задано конкретное описание*"
    )
    await state.set_state(StickerGridStates.waiting_for_theme)
    await callback.answer()


@router.message(StickerGridStates.waiting_for_theme)
async def process_grid_theme(message: Message, state: FSMContext):
    """Обработка новой темы"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    
    grid.theme = message.text
    await state.update_data(grid=grid.to_dict())
    
    # Возвращаемся к сетке
    await show_grid_main(message, state, grid, edit=True)


@router.callback_query(lambda c: c.data.startswith('grid_edit_'))
async def grid_edit_sticker(callback: CallbackQuery, state: FSMContext):
    """Редактирование конкретного стикера"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    
    sticker_idx = int(callback.data.split('_')[2])
    sticker = grid.stickers[sticker_idx]
    
    grid.current_editing = sticker_idx
    await state.update_data(grid=grid.to_dict())
    
    # Меню редактирования стикера
    text = (
        f"✏️ **Редактирование стикера #{sticker_idx + 1} из {grid.total_stickers}**\n\n"
        f"Текущие настройки:\n"
        f"• Эмодзи: {sticker['emoji']}\n"
    )
    
    if sticker['description']:
        text += f"• Описание: *{sticker['description']}*\n"
    else:
        text += f"• Описание: *не задано (будет использована общая тема)*\n"
    
    text += f"• Подпись: {sticker['caption'] or 'нет'}\n\n"
    text += f"Что хотите изменить?"
    
    # Определяем следующий стикер (с зацикливанием)
    next_idx = (sticker_idx + 1) % grid.total_stickers
    prev_idx = (sticker_idx - 1) % grid.total_stickers
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Описание", callback_data="sticker_edit_desc"),
            InlineKeyboardButton(text="💬 Подпись", callback_data="sticker_edit_caption")
        ],
        [
            InlineKeyboardButton(text="😊 Эмодзи", callback_data="sticker_edit_emoji"),
            InlineKeyboardButton(text="🔄 Сбросить", callback_data="sticker_reset")
        ],
        [
            InlineKeyboardButton(text=f"◀️ Предыдущий (#{prev_idx+1})", callback_data=f"grid_edit_{prev_idx}"),
            InlineKeyboardButton(text=f"Следующий (#{next_idx+1}) ▶️", callback_data=f"grid_edit_{next_idx}")
        ],
        [InlineKeyboardButton(text="◀️ Назад ко всем стикерам", callback_data="sticker_back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(lambda c: c.data == "sticker_edit_desc")
async def sticker_edit_description(callback: CallbackQuery, state: FSMContext):
    """Редактирование описания стикера"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    # Сохраняем ID сообщения для последующего удаления
    await state.update_data(last_grid_message_id=callback.message.message_id)
    
    current_desc = grid.stickers[idx]['description'] or "не задано"
    
    await callback.message.edit_text(
        f"📝 **Редактирование описания стикера #{idx + 1}**\n\n"
        f"Текущее описание: *{current_desc}*\n\n"
        f"Введите новое описание (или /skip чтобы оставить пустым и использовать общую тему):\n\n"
        f"💡 *Если оставить пустым, стикер будет сгенерирован на общую тему*"
    )
    await state.set_state(StickerGridStates.waiting_for_description)
    await callback.answer()


@router.message(StickerGridStates.waiting_for_description)
async def process_sticker_description(message: Message, state: FSMContext):
    """Обработка нового описания"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    if message.text == "/skip":
        grid.stickers[idx]['description'] = ""
    else:
        grid.stickers[idx]['description'] = message.text
    
    await state.update_data(grid=grid.to_dict())
    
    # Удаляем сообщение с описанием, чтобы не засорять чат
    await message.delete()
    
    # Возвращаемся к меню стикера
    await show_sticker_edit_menu(message, state, grid, idx)


@router.callback_query(lambda c: c.data == "sticker_edit_caption")
async def sticker_edit_caption(callback: CallbackQuery, state: FSMContext):
    """Редактирование подписи стикера"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    current = grid.stickers[idx]['caption'] or "нет"
    
    # Сохраняем ID сообщения для последующего удаления
    await state.update_data(last_grid_message_id=callback.message.message_id)
    
    await callback.message.edit_text(
        f"💬 **Редактирование подписи стикера #{idx + 1}**\n\n"
        f"Текущая подпись: {current}\n\n"
        f"Введите новую подпись (или /skip чтобы оставить пустой):\n\n"
        f"💡 *Подпись будет добавлена на стикер в виде текста*"
    )
    await state.set_state(StickerGridStates.waiting_for_caption)
    await callback.answer()


@router.message(StickerGridStates.waiting_for_caption)
async def process_sticker_caption(message: Message, state: FSMContext):
    """Обработка новой подписи"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    if message.text == "/skip":
        grid.stickers[idx]['caption'] = ""
    else:
        grid.stickers[idx]['caption'] = message.text
    
    await state.update_data(grid=grid.to_dict())
    
    # Удаляем сообщение с подписью
    await message.delete()
    
    # Возвращаемся к меню стикера
    await show_sticker_edit_menu(message, state, grid, idx)


@router.callback_query(lambda c: c.data == "sticker_reset")
async def sticker_reset(callback: CallbackQuery, state: FSMContext):
    """Сброс стикера к значениям по умолчанию"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    grid.stickers[idx] = {
        'description': '',
        'caption': '',
        'emoji': '🖼️'
    }
    await state.update_data(grid=grid.to_dict())
    
    await show_sticker_edit_menu(callback.message, state, grid, idx)
    await callback.answer()


@router.callback_query(lambda c: c.data == "sticker_back")
async def sticker_back_to_grid(callback: CallbackQuery, state: FSMContext):
    """Возврат к главной сетке"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    
    await show_grid_main(callback.message, state, grid, edit=True)
    await callback.answer()


async def show_sticker_edit_menu(message: Message, state: FSMContext, grid: StickerGrid, idx: int):
    """Показывает меню редактирования стикера"""
    
    sticker = grid.stickers[idx]
    
    text = (
        f"✏️ **Редактирование стикера #{idx + 1} из {grid.total_stickers}**\n\n"
        f"Текущие настройки:\n"
        f"• Эмодзи: {sticker['emoji']}\n"
    )
    
    if sticker['description']:
        text += f"• Описание: *{sticker['description']}*\n"
    else:
        text += f"• Описание: *не задано (будет использована общая тема)*\n"
    
    text += f"• Подпись: {sticker['caption'] or 'нет'}\n\n"
    text += f"Что хотите изменить?"
    
    # Определяем следующий стикер (с зацикливанием)
    next_idx = (idx + 1) % grid.total_stickers
    prev_idx = (idx - 1) % grid.total_stickers
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Описание", callback_data="sticker_edit_desc"),
            InlineKeyboardButton(text="💬 Подпись", callback_data="sticker_edit_caption")
        ],
        [
            InlineKeyboardButton(text="😊 Эмодзи", callback_data="sticker_edit_emoji"),
            InlineKeyboardButton(text="🔄 Сбросить", callback_data="sticker_reset")
        ],
        [
            InlineKeyboardButton(text=f"◀️ Предыдущий (#{prev_idx+1})", callback_data=f"grid_edit_{prev_idx}"),
            InlineKeyboardButton(text=f"Следующий (#{next_idx+1}) ▶️", callback_data=f"grid_edit_{next_idx}")
        ],
        [InlineKeyboardButton(text="◀️ Назад ко всем стикерам", callback_data="sticker_back")]
    ])
    
    try:
        # Пробуем отредактировать существующее сообщение
        if hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=keyboard)
        else:
            # Если это новое сообщение, отправляем и сохраняем ID
            sent = await message.answer(text, reply_markup=keyboard)
            await state.update_data(last_grid_message_id=sent.message_id)
    except:
        # Если не получилось отредактировать, отправляем новое
        sent = await message.answer(text, reply_markup=keyboard)
        await state.update_data(last_grid_message_id=sent.message_id)

@router.callback_query(lambda c: c.data == "grid_preview")
async def grid_show_preview(callback: CallbackQuery, state: FSMContext):
    """Показывает предпросмотр стикерпака"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    
    preview = f"📋 **Предпросмотр стикерпака**\n\n"
    preview += f"📌 **Тема:** {grid.theme}\n"
    preview += f"📊 **Стикеров:** {len(grid.stickers)}\n\n"
    
    for i, sticker in enumerate(grid.stickers, 1):
        preview += f"**{i}.** {sticker['emoji']} "
        if sticker['description']:
            preview += f"*{sticker['description']}*"
        else:
            preview += f"*[на тему {grid.theme}]*"
        
        if sticker['caption']:
            preview += f"\n   💬 Будет добавлена подпись: {sticker['caption']}"
        preview += "\n\n"
    
    preview += "✅ Всё верно? Можно генерировать!"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Генерировать!", callback_data="grid_generate")],
        [InlineKeyboardButton(text="◀️ Назад к редактированию", callback_data="sticker_back")]
    ])
    
    await callback.message.edit_text(preview, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()
    
@router.callback_query(lambda c: c.data == "grid_generate")
async def grid_generate(callback: CallbackQuery, state: FSMContext):
    """Генерация стикерпака из сетки"""
    logger.info(f"=== НАЧАЛО ГЕНЕРАЦИИ для пользователя {callback.from_user.id} === 1")
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    logger.info(f"=== НАЧАЛО ГЕНЕРАЦИИ для пользователя {callback.from_user.id} ===  2")
    # Сначала показываем сообщение о начале проверки
    status_message = await callback.message.edit_text(
        "🔄 **Проверка доступа к генерации...**\n\n"
        f"Тема: {grid.theme}\n"
        f"Стикеров: {len(grid.stickers)}\n"
        f"С индивидуальными описаниями: {sum(1 for s in grid.stickers if s['description'])}\n"
        f"С подписями: {sum(1 for s in grid.stickers if s['caption'])}\n"
    )
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        user = await db_service.get_or_create_user(telegram_id=callback.from_user.id)
        stats = await db_service.get_user_stats(user.id)
        
        # Проверяем, есть ли доступные генерации
        can_generate = await db_service.use_free_generation(user.id)
        
        if not can_generate:
            # Если бесплатных нет, проверяем, есть ли платные
            paid_generations = stats.get('paid_generations_left', 0)
            
            if paid_generations <= 0:
                # Нет доступных генераций - показываем экран оплаты
                # Передаем все необходимые данные
                await show_payment_screen(
                    callback.message, 
                    state, 
                    grid, 
                    status_message,
                    data.get('reference_photo_path')  # Передаем путь к референсному фото
                )
                return
            
            # Есть платные генерации - используем одну
            await db_service.use_paid_generation(user.id)
        
        # Продолжаем генерацию
        await status_message.edit_text(
            f"🎨 **Начинаю генерацию...**\n\n"
            f"Тема: {grid.theme}\n"
            f"Стикеров: {len(grid.stickers)}\n"
            f"С индивидуальными описаниями: {sum(1 for s in grid.stickers if s['description'])}\n"
            f"С подписями: {sum(1 for s in grid.stickers if s['caption'])}\n\n"
            f"Это займёт около минуты."
        )
        
        # Создаем промпт для генерации
        reference_photo_path = data.get("reference_photo_path")
        has_reference_photo = bool(reference_photo_path)
        prompt = create_grid_prompt(grid, has_reference_photo=has_reference_photo)
        
        # Создаем запись о генерации
        generation = await db_service.create_generation(user.id, prompt)
        
        # Генерируем изображения
        image_generator = ImageGenerator()
        images = await image_generator.generate_images(
            prompt,
            count=0,
            grid_rows=3,
            grid_cols=3,
            reference_image_path=reference_photo_path,
        )
        
        if not images:
            raise Exception("Не удалось сгенерировать изображения")
        
        # Обрабатываем в стикеры
        sticker_processor = StickerProcessor()
        output_dir = settings.STICKERS_DIR / f"pack_{generation.id}"
        stickers = await sticker_processor.process_to_stickers(images, output_dir)
        
        if not stickers:
            raise Exception("Не удалось обработать стикеры")
        
        # Создаем стикер-пак с данными из сетки
        await create_sticker_pack_from_grid(
            bot=callback.message.bot,
            user_id=callback.from_user.id,
            stickers_paths=stickers,
            grid=grid,
            generation_id=generation.id,
            db_service=db_service
        )
        
        await status_message.edit_text(
            f"✅ **Стикерпак успешно создан!**\n\n"
            f"Все стикеры сгенерированы с вашими описаниями."
        )
        
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        await status_message.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        await session.close()
        await state.clear()
    
    await callback.answer()


async def show_payment_screen(message: Message, state: FSMContext, grid: StickerGrid, status_message: Message, reference_photo_path: str = None):
    """Показывает экран оплаты"""
    
    # Сохраняем данные сетки в состояние для последующей генерации
    await state.update_data(
        pending_generation=True,
        pending_grid=grid.to_dict(),
        pending_reference_photo=reference_photo_path
    )
    
    session = await get_session()
    try:
        db_service = DatabaseService(session)
        user = await db_service.get_or_create_user(telegram_id=message.chat.id)
        
        # Получаем информацию о скидке
        discount = await db_service.get_user_discount(user.id)
        
        original_price = settings.STICKER_PACK_PRICE
        final_price = original_price
        
        if discount['has_discount']:
            final_price = original_price * (100 - discount['discount_percent']) / 100
            discount_text = (
                f"\n\n🎉 *У вас скидка {discount['discount_percent']}%!*\n"
                f"Причина: {discount['reason']}\n"
                f"Цена со скидкой: {final_price:.0f} ₽"
            )
        else:
            discount_text = "\n\n🎁 *Приведи друга и получи скидку 50%!*\nИспользуй /referral"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Оплатить {final_price:.0f} ₽", 
                callback_data=f"pay_and_generate_{final_price}"
            )],
            [InlineKeyboardButton(text="❌ Отменить генерацию", callback_data="cancel_generation")]
        ])
        
        await status_message.edit_text(
            f"⚠️ **Недостаточно генераций!**\n\n"
            f"Для создания стикерпака необходимо:\n"
            f"• {settings.STICKER_PACK_COUNT} генераций\n\n"
            f"💳 *Оплата*\n\n"
            f"Пакет: {settings.STICKER_PACK_COUNT} генераций\n"
            f"Цена: {original_price} ₽{discount_text}\n\n"
            f"После оплаты генерация начнется автоматически.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    finally:
        await session.close()


@router.callback_query(lambda c: c.data.startswith('pay_and_generate_'))
async def pay_and_generate(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты с последующей генерацией"""
    
    # Извлекаем цену из callback_data
    final_price = float(callback.data.split('_')[2])
    
    # Сохраняем флаг, что после оплаты нужно начать генерацию
    await state.update_data(generate_after_payment=True)
    
    # Создание счета
    prices = [LabeledPrice(label="Пакет генераций", amount=int(final_price * 100))]
    
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


@router.callback_query(lambda c: c.data == "cancel_generation")
async def cancel_generation(callback: CallbackQuery, state: FSMContext):
    """Отмена генерации"""
    await state.clear()
    await callback.message.edit_text("❌ Генерация отменена")
    await callback.answer()

def create_grid_prompt(grid: StickerGrid, *, has_reference_photo: bool = False) -> str:
    """Создает промпт из данных сетки"""
    
    # Базовая часть промпта
    prompt = f"Create a sticker sheet with {len(grid.stickers)} different stickers.\n\n"
    prompt += f"Overall theme: {grid.theme}\n\n"

    if has_reference_photo:
        prompt += (
            "A reference photo is provided. The character/person from the reference photo must "
            "appear in ALL stickers. Keep the identity and appearance consistent across all grid cells.\n\n"
        )
    
    # Проверяем, есть ли индивидуальные описания
    has_descriptions = any(s['description'] for s in grid.stickers)
    
    if True:#has_descriptions:
        prompt += "Each sticker should be unique. Here are the specific requirements:\n"
        for i, sticker in enumerate(grid.stickers, 1):
            if sticker['description']:
                prompt += f"Sticker {i}: {sticker['description']}"
            else:
                prompt += f"Sticker {i}: Based on overall theme: {grid.theme}"
            
            # Добавляем подпись в промпт, если она есть
            if sticker['caption']:
                prompt += f" - Include text caption '{sticker['caption']}' on the sticker"
            else:
                prompt += f" - Do not include any text on the sticker"
            prompt += "\n"
    else:
        # Если нет индивидуальных описаний, все стикеры на общую тему
        prompt += f"Create {len(grid.stickers)} variations on the theme: {grid.theme}\n"
        prompt += "Each sticker should be different but all related to the same theme.\n"
        
        # Добавляем подписи, если они есть
        captions = [s['caption'] for s in grid.stickers if s['caption']]
        if captions:
            prompt += "\nInclude these text captions on the respective stickers:\n"
            for i, caption in enumerate(captions, 1):
                prompt += f"Sticker {i}: include caption '{caption}'\n"
    
    prompt += """
    Technical requirements:
    - The ENTIRE background is SOLID MAGENTA (#FF00FF) - EVERY pixel not part of a sticker must be this color
    - NO dividing lines, NO borders, NO outlines between stickers
    - Stickers are "floating" on a solid magenta background
    - CRITICAL SPACING: Each sticker must have at least 50 pixels of magenta space around it on all sides
    - Stickers must NOT touch each other - minimum gap of 50 pixels between stickers horizontally and vertically
    - Stickers must NOT touch the canvas edges - at least 50 pixels margin from all edges
    - The magenta background forms a continuous, unbroken sea around all stickers
    - NO shadows, NO gradients on the background
    - Consistent art style across all stickers
    - High quality, suitable for Telegram stickers
    - If captions are specified, they should be clearly visible and integrated into the sticker design
    """
    
    return prompt


async def create_sticker_pack_from_grid(bot, user_id: int, stickers_paths: List[Path],
                                        grid: StickerGrid, generation_id: int, db_service):
    """Создает стикер-пак с данными из сетки"""
    
    import hashlib
    import time
    import re
    
    bot_info = await bot.me()
    bot_username = bot_info.username
    
    # Создаем имя пака
    clean_theme = re.sub(r'[^a-zA-Z0-9]', '', grid.theme[:20].lower())
    if not clean_theme or clean_theme == "невыбрана":
        clean_theme = "stickers"
    
    unique_hash = hashlib.md5(f"{user_id}_{generation_id}_{time.time()}".encode()).hexdigest()[:8]
    base_name = f"{clean_theme}_{unique_hash}"
    
    if base_name[0].isdigit():
        base_name = "s" + base_name
    
    pack_name = f"{base_name}_by_{bot_username}"
    pack_title = f"Стикеры: {grid.theme[:30]}"
    
    # Подготавливаем стикеры с эмодзи из сетки
    input_stickers = []
    for i, (sticker_path, sticker_data) in enumerate(zip(stickers_paths, grid.stickers)):
        try:
            if not sticker_path.exists():
                continue
            
            sticker_file = FSInputFile(sticker_path)
            input_sticker = InputSticker(
                sticker=sticker_file,
                format="static",
                emoji_list=[sticker_data['emoji']]
            )
            input_stickers.append(input_sticker)
            
        except Exception as e:
            logger.error(f"Ошибка подготовки стикера {i}: {e}")
    
    if input_stickers:
        result = await bot.create_new_sticker_set(
            user_id=user_id,
            name=pack_name,
            title=pack_title,
            stickers=input_stickers,
            sticker_format="static"
        )
        
        if result:
            pack_link = f"https://t.me/addstickers/{pack_name}"
            
            # Отправляем подписи
            captions_text = "📝 **Подписи к стикерам:**\n"
            for i, sticker in enumerate(grid.stickers, 1):
                if sticker.get('caption'):
                    captions_text += f"{i}. {sticker['caption']}\n"
            
            if captions_text != "📝 **Подписи к стикерам:**\n":
                await bot.send_message(
                    user_id,
                    f"✅ **Стикер-пак создан!**\n\n"
                    f"🔗 {pack_link}\n\n"
                    f"{captions_text}"
                )
            else:
                await bot.send_message(
                    user_id,
                    f"✅ **Стикер-пак создан!**\n\n"
                    f"🔗 {pack_link}"
                )
            
            await db_service.update_generation(
                generation_id,
                status="completed",
                images_count=len(input_stickers),
                sticker_pack_name=pack_name
            )
# ============= КОНЕЦ КОДА ДЛЯ СЕТКИ =============# ============= КОНЕЦ КОДА ДЛЯ СЕТКИ =============

# Замените функцию sticker_edit_emoji на упрощенную версию
@router.callback_query(lambda c: c.data == "sticker_edit_emoji")
async def sticker_edit_emoji(callback: CallbackQuery, state: FSMContext):
    """Выбор эмодзи для стикера"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    # Сохраняем ID сообщения для последующего удаления
    await state.update_data(last_grid_message_id=callback.message.message_id)
    
    # Простое меню с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Случайный эмодзи", callback_data="emoji_random")],
        [InlineKeyboardButton(text="✏️ Ввести свой эмодзи", callback_data="emoji_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sticker_back")]
    ])
    
    await callback.message.edit_text(
        f"😊 **Выбор эмодзи для стикера #{idx + 1}**\n\n"
        f"Текущий эмодзи: {grid.stickers[idx]['emoji']}\n\n"
        f"Вы можете:\n"
        f"• Нажать «Случайный эмодзи» для случайного выбора\n"
        f"• Нажать «Ввести свой эмодзи» и ввести любой эмодзи с клавиатуры\n\n"
        f"💡 *Подсказка: на телефоне можно переключиться на клавиатуру с эмодзи*",
        reply_markup=keyboard
    )
    await state.set_state(StickerGridStates.waiting_for_emoji)
    await callback.answer()

# Обработчик для ввода своего эмодзи
@router.callback_query(lambda c: c.data == "emoji_custom")
async def process_emoji_custom(callback: CallbackQuery, state: FSMContext):
    """Запрос на ввод своего эмодзи"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    await callback.message.edit_text(
        f"✏️ **Введите свой эмодзи для стикера #{idx + 1}**\n\n"
        f"Текущий эмодзи: {grid.stickers[idx]['emoji']}\n\n"
        f"Отправьте сообщение с любым эмодзи (можно использовать клавиатуру эмодзи на телефоне).\n"
        f"Или отправьте /skip чтобы оставить текущий.\n\n"
        f"💡 *Примеры: 😊, 🐶, ❤️, 🚀*"
    )
    await state.set_state(StickerGridStates.waiting_for_emoji_input)
    await callback.answer()

# Добавьте обработчик для случайного выбора
@router.callback_query(lambda c: c.data == "emoji_random")
async def process_emoji_random(callback: CallbackQuery, state: FSMContext):
    """Выбор случайного эмодзи из всех категорий"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    # Получаем случайный эмодзи
    random_emoji = EmojiManager.get_random_emoji()
    
    grid.stickers[idx]['emoji'] = random_emoji
    await state.update_data(grid=grid.to_dict())
    
    # Показываем сообщение с результатом
    await callback.answer(f"Выбран эмодзи: {random_emoji}", show_alert=True)
    
    # Возвращаемся к меню стикера
    await show_sticker_edit_menu(callback.message, state, grid, idx)
    await callback.answer()

# Добавьте этот обработчик после всех callback_query обработчиков, но перед handle_unknown

@router.message(StickerGridStates.waiting_for_emoji_input)
async def process_custom_emoji(message: Message, state: FSMContext):
    """Обработка введенного пользователем эмодзи"""
    
    data = await state.get_data()
    grid = StickerGrid.from_dict(data.get('grid'))
    idx = grid.current_editing
    
    # Проверяем команду /skip
    if message.text == "/skip":
        # Оставляем текущий эмодзи
        await message.delete()
        # Возвращаемся к меню стикера
        await show_sticker_edit_menu(message, state, grid, idx)
        return
    
    # Проверяем, является ли введенный текст эмодзи
    emoji_text = message.text.strip()
    
    # Проверка на эмодзи
    import unicodedata
    
    def is_emoji_character(char):
        """Проверяет, является ли символ эмодзи"""
        try:
            # Эмодзи часто имеют категорию 'So' (Symbol, other)
            # или 'Sm' (Symbol, math) для некоторых
            category = unicodedata.category(char)
            if category in ('So', 'Sm'):
                return True
            # Некоторые эмодзи состоят из нескольких символов и имеют специальные имена
            name = unicodedata.name(char, '')
            if 'EMOJI' in name or 'FACE' in name or 'HEART' in name:
                return True
        except:
            pass
        return False
    
    # Проверяем каждый символ в строке
    is_emoji = False
    for char in emoji_text:
        if is_emoji_character(char):
            is_emoji = True
            break
    
    # Также проверяем, что строка не слишком длинная (эмодзи обычно 1-5 символов)
    if not is_emoji or len(emoji_text) > 10:
        await message.reply(
            "❌ Пожалуйста, отправьте именно эмодзи.\n\n"
            "Примеры: 😊, 🐶, ❤️, 🚀\n\n"
            "Или отправьте /skip чтобы оставить текущий эмодзи."
        )
        return
    
    # Устанавливаем новый эмодзи
    grid.stickers[idx]['emoji'] = emoji_text
    await state.update_data(grid=grid.to_dict())
    
    # Удаляем сообщение пользователя, чтобы не засорять чат
    try:
        await message.delete()
    except:
        pass
    
    # Показываем подтверждение
    await message.answer(f"✅ Эмодзи изменен на: {emoji_text}")
    
    # Возвращаемся к меню стикера
    await show_sticker_edit_menu(message, state, grid, idx)


# Также добавьте обработчик для состояния waiting_for_emoji
# (это состояние, когда пользователь еще не выбрал действие)
@router.message(StickerGridStates.waiting_for_emoji)
async def handle_emoji_state_message(message: Message, state: FSMContext):
    """Обработка сообщений в состоянии ожидания выбора эмодзи"""
    # Если пользователь отправил что-то текстом в этом состоянии,
    # направляем его обратно к выбору эмодзи
    await message.answer(
        "❓ Пожалуйста, используйте кнопки для выбора эмодзи:\n\n"
        "• 🎲 Случайный эмодзи\n"
        "• ✏️ Ввести свой эмодзи\n\n"
        "Или нажмите «◀️ Назад» для возврата в меню стикера."
    )
#EMOJI ^

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, state: FSMContext):
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
        
        # Обновляем количество платных генераций
        await db_service.add_paid_generations(user.id, generations_to_add)
        
        # Сохраняем информацию о платеже
        await db_service.save_payment(
            user_id=user.id,
            payment_id=payment_info.provider_payment_charge_id or payment_info.telegram_payment_charge_id,
            amount=payment_info.total_amount,
            currency=payment_info.currency,
            generations_added=generations_to_add
        )
        
        # Проверяем, нужно ли начать генерацию после оплаты
        data = await state.get_data()
        if data.get('generate_after_payment'):
            # Убираем флаг
            await state.update_data(generate_after_payment=False)
            
            # Получаем сохраненные данные для генерации
            pending_generation = data.get('pending_generation')
            if pending_generation:
                grid = StickerGrid.from_dict(data.get('pending_grid'))
                reference_photo_path = data.get('pending_reference_photo')
                
                # Сохраняем данные в состояние для генерации
                await state.update_data(
                    grid=grid.to_dict(),
                    reference_photo_path=reference_photo_path
                )
                
                # Запускаем генерацию
                await message.answer(
                    f"✅ Оплата прошла успешно!\n\n"
                    f"Начинаю генерацию вашего стикерпака..."
                )
                
                # Вызываем генерацию
                from aiogram.types import CallbackQuery
                fake_callback = CallbackQuery(
                    id="temp",
                    from_user=message.from_user,
                    message=message,
                    data="grid_generate",
                    chat_instance="temp",
                    bot=message.bot
                )
                await grid_generate(fake_callback, state)
            else:
                await message.answer(
                    f"✅ Оплата прошла успешно!\n\n"
                    f"Теперь можно перейти к генерации.\n"
                    f"Используйте /generate для создания вашего пака!"
                )
        else:
            await message.answer(
                f"✅ Оплата прошла успешно!\n\n"
                f"Теперь можно перейти к генерации.\n"
                f"Используйте /generate для создания вашего пака!"
            )
    finally:
        await session.close()

@router.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Не понимаю эту команду.\n\n"
        "Используй /help чтобы увидеть список доступных команд."
    )
    
