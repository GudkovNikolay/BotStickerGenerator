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
    
    # Требования Telegram для статических стикеров
    TARGET_SIZE = 512  # Строго 512x512 пикселей
    MAX_FILE_SIZE = 512 * 1024  # 512 KB максимум
    
    async def process_to_stickers(
        self, 
        image_paths: List[Path],
        output_dir: Path
    ) -> List[Path]:
        """
        Обработка изображений в стикеры PNG для Telegram
        
        Args:
            image_paths: Список путей к исходным изображениям
            output_dir: Директория для сохранения стикеров
            
        Returns:
            Список путей к обработанным стикерам (PNG)
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        sticker_paths = []
        
        for i, image_path in enumerate(image_paths):
            try:
                sticker_path = output_dir / f"sticker_{i:03d}.png"  # PNG для статических стикеров
                await self._process_single_image(image_path, sticker_path)
                sticker_paths.append(sticker_path)
            except Exception as e:
                logger.error(f"Ошибка обработки изображения {image_path}: {e}", exc_info=True)
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
        try:
            # Открываем изображение
            img = Image.open(input_path)
            
            # Конвертируем в RGBA для поддержки прозрачности
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            
            # Удаляем фон (опционально)
            # img = self._remove_background(img)
            
            # Приводим к строго квадратному формату 512x512
            img = self._make_telegram_sticker(img)
            
            # Сохраняем как PNG с оптимизацией
            self._save_png_optimized(img, output_path)
            
            # Проверяем размер
            file_size = output_path.stat().st_size
            if file_size > self.MAX_FILE_SIZE:
                logger.warning(f"Стикер {output_path} слишком большой: {file_size} bytes")
                
        except Exception as e:
            logger.error(f"Ошибка в _process_image_sync: {e}", exc_info=True)
            raise
    
    def _make_telegram_sticker(self, img: Image.Image) -> Image.Image:
        """
        Приводит изображение к формату стикера Telegram:
        - Квадратное 512x512
        - Белый фон для прозрачных областей (опционально)
        """
        # 1. Обрезаем до квадрата с центрированием
        img = self._crop_to_square(img)
        
        # 2. Ресайзим точно до 512x512
        if img.size != (self.TARGET_SIZE, self.TARGET_SIZE):
            img = img.resize((self.TARGET_SIZE, self.TARGET_SIZE), Image.Resampling.LANCZOS)
        
        # 3. Убеждаемся, что изображение в RGBA
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        
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
    
    def _save_png_optimized(self, img: Image.Image, output_path: Path) -> None:
        """Сохранение в PNG с оптимизацией размера файла"""
        # Сохраняем с оптимизацией
        img.save(
            output_path,
            "PNG",
            optimize=True,
            compress_level=9  # Максимальная компрессия
        )
        
        # Проверяем размер и если слишком большой - уменьшаем качество через ресайз
        if output_path.stat().st_size > self.MAX_FILE_SIZE:
            logger.info(f"Файл слишком большой, уменьшаем размер до 512x512 с оптимизацией")
            
            # Создаем копию с чуть меньшим размером (но не меньше 512x512)
            scale = (self.MAX_FILE_SIZE / output_path.stat().st_size) ** 0.5
            if scale < 1:
                new_size = (int(self.TARGET_SIZE * scale), int(self.TARGET_SIZE * scale))
                if new_size[0] >= 512:  # Сохраняем минимальный размер
                    img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    
                    # Создаем холст 512x512 и вставляем изображение по центру
                    final_img = Image.new('RGBA', (self.TARGET_SIZE, self.TARGET_SIZE), (255, 255, 255, 0))
                    x_offset = (self.TARGET_SIZE - new_size[0]) // 2
                    y_offset = (self.TARGET_SIZE - new_size[1]) // 2
                    final_img.paste(img_resized, (x_offset, y_offset), img_resized)
                    
                    final_img.save(output_path, "PNG", optimize=True, compress_level=9)


# Альтернативная версия, если нужны WebP стикеры (анимированные или с прозрачностью)
class StickerProcessorWebP:
    """Обработчик для WebP стикеров (если нужно)"""
    
    TARGET_SIZE = 512
    MAX_FILE_SIZE = 512 * 1024
    
    async def process_to_stickers(self, image_paths: List[Path], output_dir: Path) -> List[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        sticker_paths = []
        
        for i, image_path in enumerate(image_paths):
            try:
                sticker_path = output_dir / f"sticker_{i:03d}.webp"  # WebP
                await self._process_single_image(image_path, sticker_path)
                sticker_paths.append(sticker_path)
            except Exception as e:
                logger.error(f"Ошибка обработки {image_path}: {e}")
                continue
        
        return sticker_paths
    
    async def _process_single_image(self, input_path: Path, output_path: Path) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._process_image_sync, input_path, output_path)
    
    def _process_image_sync(self, input_path: Path, output_path: Path) -> None:
        img = Image.open(input_path)
        
        # Конвертируем в RGBA
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        
        # Приводим к формату стикера
        img = self._make_telegram_sticker(img)
        
        # Сохраняем как WebP
        self._save_webp_optimized(img, output_path)
    
    def _make_telegram_sticker(self, img: Image.Image) -> Image.Image:
        """Приводит к квадрату 512x512"""
        # Обрезаем до квадрата
        width, height = img.size
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        img = img.crop((left, top, left + size, top + size))
        
        # Ресайзим до 512x512
        if img.size != (self.TARGET_SIZE, self.TARGET_SIZE):
            img = img.resize((self.TARGET_SIZE, self.TARGET_SIZE), Image.Resampling.LANCZOS)
        
        return img
    
    def _save_webp_optimized(self, img: Image.Image, output_path: Path) -> None:
        """Сохранение в WebP с оптимизацией размера"""
        # Пробуем разные уровни качества
        for quality in range(90, 50, -5):
            img.save(output_path, "WEBP", quality=quality, method=6)
            if output_path.stat().st_size <= self.MAX_FILE_SIZE:
                logger.info(f"WebP сохранен с качеством {quality}, размер: {output_path.stat().st_size} bytes")
                return
        
        # Если все еще слишком большой, уменьшаем размер
        if output_path.stat().st_size > self.MAX_FILE_SIZE:
            scale = (self.MAX_FILE_SIZE / output_path.stat().st_size) ** 0.5
            new_size = (int(img.width * scale), int(img.height * scale))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            img_resized.save(output_path, "WEBP", quality=80, method=6)