"""
Генерация изображений через OpenAI DALL-E 3 API
"""
import aiohttp
import asyncio
import time
from pathlib import Path
from typing import List
from openai import AsyncOpenAI
from config import settings
import logging

logger = logging.getLogger(__name__)


class ImageGenerator:
    """Генератор изображений через DALL-E 3"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    async def generate_images(
        self, 
        prompt: str, 
        count: int = 5,
        size: str = "1024x1024"
    ) -> List[Path]:
        """
        Генерация изображений по промпту
        
        Args:
            prompt: Текстовый промпт
            count: Количество изображений (для DALL-E 3 максимум 1 за запрос)
            size: Размер изображения
            
        Returns:
            Список путей к сохраненным изображениям
        """
        images = []
        
        # DALL-E 3 генерирует по 1 изображению за запрос
        # Для генерации нескольких нужно делать несколько запросов
        for i in range(min(count, 5)):  # Ограничиваем максимум 5
            try:
                logger.info(f"Генерация изображения {i+1}/{count} для промпта: {prompt[:50]}...")
                
                response = await self.client.images.generate(
                    model="dall-e-3",
                    prompt=prompt,
                    size=size,
                    quality="standard",
                    n=1,
                )
                
                image_url = response.data[0].url
                
                # Скачиваем изображение
                image_path = await self._download_image(
                    image_url, 
                    settings.TEMP_DIR / f"generated_{i}_{int(time.time() * 1000)}.png"
                )
                
                images.append(image_path)
                
                # Небольшая задержка между запросами
                if i < count - 1:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Ошибка генерации изображения {i+1}: {e}")
                continue
        
        return images
    
    async def _download_image(self, url: str, save_path: Path) -> Path:
        """Скачивание изображения по URL"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(content)
                    return save_path
                else:
                    raise Exception(f"Ошибка скачивания изображения: {response.status}")

