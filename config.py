"""
Конфигурация приложения
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram
    BOT_TOKEN: str
    
    # Image generation (локальный Stable Diffusion через diffusers)
    # Backend пока только один: "local" (StableDiffusionPipeline)
    IMAGE_BACKEND: str = "local"

    # Hugging Face hub (для загрузки модели один раз, дальше работа локально)
    HF_TOKEN: str = ""  # опционально, если модель приватная
    HF_MODEL: str = "runwayml/stable-diffusion-v1-5"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot.db"
    
    # Payment Providers
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    STRIPE_API_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    
    # Bot Settings
    ADMIN_USER_IDS: str = ""
    FREE_GENERATIONS_PER_USER: int = 3
    STICKER_PACK_PRICE: int = 100  # в рублях/центах
    
    # Server
    WEBHOOK_URL: str = ""
    WEBHOOK_PATH: str = "/webhook"
    
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Создаем директории для файлов
try:
    settings = Settings()
except Exception as e:
    import sys
    print(f"Ошибка загрузки конфигурации: {e}")
    print("Убедитесь, что файл .env существует и содержит необходимые переменные.")
    print("Скопируйте .env.example в .env и заполните значения.")
    sys.exit(1)

settings.STICKERS_DIR.mkdir(exist_ok=True)
settings.TEMP_DIR.mkdir(exist_ok=True)

