"""
Конфигурация приложения
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

# Загружаем .env файл ПЕРЕД созданием настроек
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    print(f"✅ Загружен .env файл: {env_path}")
else:
    print(f"⚠️ .env файл не найден: {env_path}")

class Settings(BaseSettings):
    """Настройки приложения"""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
    )
    
    # Telegram - берем из os.environ
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # Image generation
    IMAGE_BACKEND: str = os.getenv("IMAGE_BACKEND", "kie_ai")
    KIE_API_KEY: str = os.getenv("KIE_API_KEY", "")
    KIE_MODEL: str = os.getenv("KIE_MODEL", "nano-banana-pro")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    
    # Payment
    YOOKASSA_SHOP_ID: str = os.getenv("YOOKASSA_SHOP_ID", "")
    YOOKASSA_SECRET_KEY: str = os.getenv("YOOKASSA_SECRET_KEY", "")
    STRIPE_API_KEY: str = os.getenv("STRIPE_API_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    
    # Bot Settings
    ADMIN_USER_IDS: str = os.getenv("ADMIN_USER_IDS", "")
    FREE_GENERATIONS_PER_USER: int = int(os.getenv("FREE_GENERATIONS_PER_USER", "3"))
    STICKER_PACK_COUNT: int = int(os.getenv("STICKER_PACK_COUNT", "5"))
    STICKER_PACK_PRICE: int = int(os.getenv("STICKER_PACK_PRICE", "2"))
    STICKER_PACK_STARS_PRICE: int = int(os.getenv("STICKER_PACK_STARS_PRICE", "50"))
    
    STICKER_GRID_ROWS: int = int(os.getenv("STICKER_GRID_ROWS", "3"))
    STICKER_GRID_COLS: int = int(os.getenv("STICKER_GRID_COLS", "3"))
    
    PAYMENTS_PROVIDER_TOKEN: str = os.getenv("PAYMENTS_PROVIDER_TOKEN", "")
    CURRENCY: str = os.getenv("CURRENCY", "RUB")
    
    # Server
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    
    # Paths
    BASE_DIR: Path = Path(__file__).parent
    STICKERS_DIR: Path = BASE_DIR / "generated_stickers"
    TEMP_DIR: Path = BASE_DIR / "temp_images"
    
    @property
    def admin_ids(self) -> list[int]:
        """Список ID администраторов"""
        if not self.ADMIN_USER_IDS:
            return []
        return [int(uid.strip()) for uid in self.ADMIN_USER_IDS.split(",")]


# Создаем экземпляр настроек
settings = Settings()

# Выводим информацию для отладки
print("\n📋 Конфигурация загружена:")
print(f"BOT_TOKEN: {'✅' if settings.BOT_TOKEN else '❌'}")
print(f"PAYMENTS_PROVIDER_TOKEN: {'✅' if settings.PAYMENTS_PROVIDER_TOKEN else '❌'}")
print(f"STICKER_PACK_PRICE: {settings.STICKER_PACK_PRICE}")
print(f"CURRENCY: {settings.CURRENCY}")
print('*' * 40)

# Создаем директории
settings.STICKERS_DIR.mkdir(exist_ok=True)
settings.TEMP_DIR.mkdir(exist_ok=True)