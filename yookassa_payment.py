import uuid
from datetime import datetime
from yookassa import Configuration, Payment
from config import settings

# Настройка ЮKassa
Configuration.account_id = settings.YOOKASSA_SHOP_ID
Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

def create_yookassa_payment(amount_rub: int, description: str, telegram_id: int, user_id: int):
    """
    Создает платеж в ЮKassa
    
    Args:
        amount_rub: Сумма в рублях
        description: Описание платежа
        telegram_id: Telegram ID пользователя
        user_id: ID пользователя в БД
    
    Returns:
        tuple: (payment_object, confirmation_url, payment_id)
    """
    amount_value = f"{float(amount_rub):.2f}"
    idem_key = str(uuid.uuid4())
    
    payload = {
        "amount": {"value": amount_value, "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect", 
            "return_url": settings.YOOKASSA_RETURN_URL
        },
        "description": description[:128],
        "metadata": {
            "telegram_id": str(telegram_id),
            "user_id": str(user_id),
            "payment_type": "sticker_pack"
        },
    }
    
    # Добавляем чек если настроено
    if settings.YOOKASSA_WITH_RECEIPT:
        receipt = _build_receipt(amount_value, description, telegram_id)
        if receipt:
            payload["receipt"] = receipt
    
    payment = Payment.create(payload, idem_key)
    return payment, payment.confirmation.confirmation_url, payment.id

def _build_receipt(amount_value: str, description: str, telegram_id: int):
    """Создает чек для платежа"""
    customer = {}
    
    # Используем email пользователя если есть, иначе можно использовать telegram_id
    if settings.YOOKASSA_RECEIPT_EMAIL:
        customer["email"] = settings.YOOKASSA_RECEIPT_EMAIL
    elif settings.YOOKASSA_RECEIPT_PHONE:
        customer["phone"] = settings.YOOKASSA_RECEIPT_PHONE
    else:
        return None
    
    item = {
        "description": description[:128],
        "quantity": "1.00",
        "amount": {"value": amount_value, "currency": "RUB"},
        "vat_code": settings.YOOKASSA_VAT_CODE,
        "payment_subject": "service",
        "payment_mode": "full_payment",
    }
    
    return {
        "customer": customer, 
        "tax_system_code": settings.YOOKASSA_TAX_SYSTEM_CODE, 
        "items": [item]
    }

def get_yookassa_payment(payment_id: str):
    """Получает информацию о платеже"""
    return Payment.find_one(payment_id)

def check_payment_status(payment_id: str) -> dict:
    """
    Проверяет статус платежа
    
    Returns:
        dict: {
            'status': 'succeeded'/'pending'/'canceled',
            'paid': bool,
            'metadata': dict
        }
    """
    try:
        payment = get_yookassa_payment(payment_id)
        return {
            'status': payment.status,
            'paid': payment.paid,
            'metadata': payment.metadata,
            'amount': payment.amount.value if hasattr(payment, 'amount') else None
        }
    except Exception as e:
        return {'status': 'error', 'paid': False, 'error': str(e)}
        