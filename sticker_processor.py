"""
Обработка изображений в стикеры для Telegram
"""
import logging
from pathlib import Path
from typing import List
from PIL import Image
import asyncio

logger = logging.getLogger(__name__)


class StickerProcessor:
    """Обработчик изображений в стикеры"""
    
    # Требования Telegram для стикеров
    MAX_SIZE = 512  # Максимальный размер стороны в пикселях
    MAX_FILE_SIZE = 512 * 1024  # 512 KB максимум
    
    async def process_to_stickers(
        self, 
        image_paths: List[Path],
        output_dir: Path
    ) -> List[Path]:
        """
        Обработка изображений в стикеры WebP
        
        Args:
            image_paths: Список путей к исходным изображениям
            output_dir: Директория для сохранения стикеров
            
        Returns:
            Список путей к обработанным стикерам
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        sticker_paths = []
        
        for i, image_path in enumerate(image_paths):
            try:
                sticker_path = output_dir / f"sticker_{i}.webp"
                await self._process_single_image(image_path, sticker_path)
                sticker_paths.append(sticker_path)
            except Exception as e:
                logger.error(f"Ошибка обработки изображения {image_path}: {e}")
                continue
        
        return sticker_paths
    
    async def _process_single_image(
        self, 
        input_path: Path, 
        output_path: Path
    ) -> None:
        """Обработка одного изображения в стикер"""
        # Выполняем в отдельном потоке, т.к. PIL синхронный
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._process_image_sync,
            input_path,
            output_path
        )
    
    def _process_image_sync(self, input_path: Path, output_path: Path) -> None:
        """Синхронная обработка изображения"""
        # Открываем изображение
        img = Image.open(input_path)
        
        # Конвертируем в RGBA если нужно
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        
        # Удаляем фон (простой метод - можно улучшить)
        img = self._remove_background(img)
        
        # Обрезаем до квадрата с центрированием
        img = self._crop_to_square(img)
        
        # Изменяем размер до максимум 512x512
        img = self._resize_to_max(img, self.MAX_SIZE)
        
        # Сохраняем как WebP с оптимизацией
        self._save_webp_optimized(img, output_path)
    
    def _remove_background(self, img: Image.Image) -> Image.Image:
        """
        Удаление фона (упрощенная версия)
        В продакшене лучше использовать rembg или другие библиотеки
        """
        # Простой метод: делаем прозрачным белый/светлый фон
        # Для MVP этого достаточно, в будущем можно использовать rembg
        data = img.getdata()
        new_data = []
        
        for item in data:
            # Если пиксель очень светлый (почти белый), делаем прозрачным
            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        
        img.putdata(new_data)
        return img
    
    def _crop_to_square(self, img: Image.Image) -> Image.Image:
        """Обрезка до квадрата с центрированием"""
        width, height = img.size
        
        if width == height:
            return img
        
        # Находим меньшую сторону
        size = min(width, height)
        
        # Центрируем обрезку
        left = (width - size) // 2
        top = (height - size) // 2
        right = left + size
        bottom = top + size
        
        return img.crop((left, top, right, bottom))
    
    def _resize_to_max(self, img: Image.Image, max_size: int) -> Image.Image:
        """Изменение размера с сохранением пропорций"""
        width, height = img.size
        
        if width <= max_size and height <= max_size:
            return img
        
        # Вычисляем новый размер с сохранением пропорций
        ratio = min(max_size / width, max_size / height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    def _save_webp_optimized(self, img: Image.Image, output_path: Path) -> None:
        """Сохранение в WebP с оптимизацией размера файла"""
        # Пробуем разные уровни качества пока файл не станет меньше 512KB
        for quality in range(95, 50, -5):
            img.save(
                output_path,
                "WEBP",
                quality=quality,
                method=6  # Максимальная компрессия
            )
            
            if output_path.stat().st_size <= self.MAX_FILE_SIZE:
                return
        
        # Если все еще слишком большой, уменьшаем размер
        if output_path.stat().st_size > self.MAX_FILE_SIZE:
            scale = (self.MAX_FILE_SIZE / output_path.stat().st_size) ** 0.5
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(output_path, "WEBP", quality=80, method=6)

