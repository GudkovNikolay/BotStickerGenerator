"""
Вспомогательные функции
"""
import secrets
import string


def generate_referral_code(length: int = 8) -> str:
    """Генерация уникального реферального кода"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

