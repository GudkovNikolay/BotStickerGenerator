"""
Генерация изображений через Kie.ai (nano-banana-pro) с возможностью тестирования на локальном файле.
"""
import asyncio
import json
import mimetypes
import time
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from PIL import Image

from config import settings
import logging

logger = logging.getLogger(__name__)


KIE_API_BASE_URL = "https://api.kie.ai"
KIE_UPLOAD_BASE_URL = "https://kieai.redpandaai.co"
KIE_UPLOAD_PATH = "images/user-uploads"


def _size_to_aspect_ratio(size: str) -> str:
    """Грубое сопоставление размера вида 'WxH' к aspect_ratio Kie.ai."""
    try:
        if "x" in size:
            w_str, h_str = size.lower().split("x")
            w = int(w_str)
            h = int(h_str)
            if w <= 0 or h <= 0:
                raise ValueError
            ratio = w / h
            if 0.9 <= ratio <= 1.1:
                return "1:1"
            if ratio > 1.1:
                return "16:9"
            return "9:16"
    except Exception:
        pass
    return "1:1"


def _grid_to_aspect_ratio(rows: int, cols: int) -> str:
    """Подбираем aspect_ratio под форму сетки."""
    if rows <= 0 or cols <= 0:
        return "1:1"
    ratio = cols / rows
    if 0.9 <= ratio <= 1.1:
        return "1:1"
    if ratio >= 1.55:
        return "16:9"
    if ratio <= 0.65:
        return "9:16"
    if ratio > 1.1:
        return "4:3"
    return "3:4"


def _build_grid_prompt(prompt: str, rows: int, cols: int) -> str:
    """Уточняем промпт, чтобы модель вернула лист-сетку со стикерами."""
    return (
        f"{prompt}\n\n"
        f"Create ONE sticker sheet image containing a {rows}x{cols} grid of distinct stickers. "
        "Each grid cell must contain exactly one sticker centered with padding. "
        "Use a clean white background and clear separation between cells. "
        "No text, no logos, no watermarks, no borders around the sheet."
    )


def _find_content_borders(img: Image.Image, tolerance: int = 30) -> Tuple[int, int, int, int]:
    """
    Находит границы полезного содержимого, отсекая рамку.
    
    Args:
        img: PIL Image
        tolerance: Допуск отклонения от фонового цвета
    
    Returns:
        (left, top, right, bottom) - координаты обрезки
    """
    # Конвертируем в RGB для простоты
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    width, height = img.size
    
    # Берем цвет из углов для определения фона
    corners = [
        img.getpixel((0, 0)),  # верхний левый
        img.getpixel((width-1, 0)),  # верхний правый
        img.getpixel((0, height-1)),  # нижний левый
        img.getpixel((width-1, height-1))  # нижний правый
    ]
    
    # Усредняем цвет фона
    bg_color = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    
    def is_background(x, y):
        """Проверяет, является ли пиксель фоновым"""
        try:
            pixel = img.getpixel((x, y))
            # Проверяем, похож ли пиксель на фоновый цвет
            return all(abs(pixel[i] - bg_color[i]) <= tolerance for i in range(3))
        except:
            return False
    
    # Ищем левую границу
    left = 0
    for x in range(width):
        if not all(is_background(x, height//2 + d) for d in range(-5, 6)):
            left = max(0, x)  # небольшой отступ
            break
    
    # Ищем правую границу
    right = width
    for x in range(width-1, -1, -1):
        if not all(is_background(x, height//2 + d) for d in range(-5, 6)):
            right = min(width, x)
            break
    
    # Ищем верхнюю границу
    top = 0
    for y in range(height):
        if not all(is_background(width//2 + d, y) for d in range(-5, 6)):
            top = max(0, y)
            break
    
    # Ищем нижнюю границу
    bottom = height
    for y in range(height-1, -1, -1):
        if not all(is_background(width//2 + d, y) for d in range(-5, 6)):
            bottom = min(height, y)
            break
    
    print(f"Найдены границы содержимого: left={left}, top={top}, right={right}, bottom={bottom}")
    print(width, height)
    return left, top, right, bottom


def _split_grid_png(png_bytes: bytes, rows: int, cols: int, remove_border: bool = True) -> List[bytes]:
    """
    Режем PNG-сетку на rows*cols отдельных PNG-тайлов с удалением рамки.
    Без фильтров шума, только обрезка.
    """
    if rows <= 0 or cols <= 0:
        return []

    # Открываем изображение
    img = Image.open(BytesIO(png_bytes))
    
    # Сохраняем оригинальный режим
    original_mode = img.mode
    
    # Конвертируем в RGBA если нужно для сохранения прозрачности
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    w, h = img.size

    # Если нужно, удаляем рамку вокруг всей сетки
    if remove_border:
        left, top, right, bottom = _find_content_borders(img)
        if left != w - right or top != h - bottom:
            left, top, right, bottom = 0, 0, w, h
        else:
            img = img.crop((left, top, right, bottom))
    
    w, h = img.size
    
    # Вычисляем размер ячейки
    cell_w = w // cols
    cell_h = h // rows
    
    tiles: List[bytes] = []
    for r in range(rows):
        for c in range(cols):
            # Координаты ячейки
            left = c * cell_w
            upper = r * cell_h
            right_bound = (c + 1) * cell_w if c < cols - 1 else w
            lower_bound = (r + 1) * cell_h if r < rows - 1 else h
            print(f"left={left}, top={upper}, right={right_bound}, bottom={lower_bound}")
            
            # Вырезаем ячейку
            tile = img.crop((left, upper, right_bound, lower_bound))
            
            # # Убираем внутреннюю рамку внутри каждой ячейки
            # tile_left, tile_top, tile_right, tile_bottom = _find_content_borders(tile, tolerance=20)
            # tile = tile.crop((tile_left, tile_top, tile_right, tile_bottom))
            
            # Конвертируем обратно в оригинальный режим если нужно
            if original_mode != 'RGBA' and original_mode != 'RGB':
                tile = tile.convert(original_mode)
            
            # Сохраняем в байты
            buf = BytesIO()
            tile.save(buf, format="PNG")
            tiles.append(buf.getvalue())
    
    return tiles


class ImageGenerator:
    """Генератор изображений через API Kie.ai (nano-banana-pro)."""

    def __init__(self, use_local_file: bool = True, local_file_path: str = "kie_raw_1774723597590.png"):
        """
        Args:
            use_local_file: Если True, использовать локальный файл вместо API
            local_file_path: Путь к локальному файлу с сеткой стикеров
        """
        self.backend = "kie_ai"
        self.use_local_file = use_local_file
        self.local_file_path = local_file_path

    def _draw_grid_debug(
        self, 
        grid_bytes: bytes, 
        grid_rows: int, 
        grid_cols: int,
        output_path: Path,
        remove_border: bool = True
    ) -> None:
        """
        Создает визуализацию процесса нарезки сетки.
        Рисует красным:
        - Найденные границы содержимого
        - Линии разреза между стикерами
        - Номера ячеек
        """
        from PIL import ImageDraw, ImageFont
        
        # Открываем изображение
        img = Image.open(BytesIO(grid_bytes))
        
        # Конвертируем в RGB для рисования цветных линий
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Создаем копию для рисования
        debug_img = img.copy()
        draw = ImageDraw.Draw(debug_img, 'RGBA')
        
        width, height = debug_img.size
        w, h = width, height
        # 1. Если нужно, находим и рисуем границы содержимого
        if remove_border:
            left, top, right, bottom = _find_content_borders(img)

            if left != w - right or top != h - bottom:
                left, top, right, bottom = 0, 0, w, h
            # Рисуем внешнюю рамку (синюю) - найденные границы
            draw.rectangle(
                [(left, top), (right, bottom)],
                outline=(0, 0, 255, 255),  # Синий
                width=3
            )
            
            # Подписываем координаты
            draw.text((left + 5, top + 5), f"({left}, {top})", fill=(0, 0, 255, 255))
            draw.text((right - 5, bottom - 5), f"({right}, {bottom})", fill=(0, 0, 255, 255))
            
            # Обрезаем для дальнейшей разметки
            debug_img_cropped = debug_img.crop((left, top, right, bottom))
            draw = ImageDraw.Draw(debug_img_cropped, 'RGBA')
            w, h = debug_img_cropped.size
        else:
            debug_img_cropped = debug_img
            w, h = width, height
        
        # 2. Вычисляем размер ячейки
        cell_w = w // grid_cols
        cell_h = h // grid_rows
        
        # 3. Рисуем линии сетки
        # Вертикальные линии
        for c in range(1, grid_cols):
            x = c * cell_w
            draw.line([(x, 0), (x, h)], fill=(255, 0, 0, 255), width=2)
            # Подписываем координату
            draw.text((x - 20, 5), f"x={x}", fill=(255, 0, 0, 255))
        
        # Горизонтальные линии
        for r in range(1, grid_rows):
            y = r * cell_h
            draw.line([(0, y), (w, y)], fill=(255, 0, 0, 200), width=2)
            draw.text((5, y - 15), f"y={y}", fill=(255, 0, 0, 255))
        
        # 4. Рисуем границы каждой ячейки
        for r in range(grid_rows):
            for c in range(grid_cols):
                left = c * cell_w
                upper = r * cell_h
                right_bound = (c + 1) * cell_w if c < grid_cols - 1 else w
                lower_bound = (r + 1) * cell_h if r < grid_rows - 1 else h
                
                # Рисуем полупрозрачную заливку для каждой ячейки
                fill_color = (255, 255, 0, 30) if (r + c) % 2 == 0 else (0, 255, 255, 30)
                draw.rectangle(
                    [(left, upper), (right_bound, lower_bound)],
                    fill=fill_color,
                    outline=None
                )
                
                # Рисуем номер ячейки
                cell_num = r * grid_cols + c + 1
                text_x = left + cell_w // 2 - 10
                text_y = upper + cell_h // 2 - 10
                draw.text(
                    (text_x, text_y), 
                    str(cell_num), 
                    fill=(255, 255, 255, 255),
                    stroke_width=2,
                    stroke_fill=(0, 0, 0, 255)
                )
        
        # 5. Если была обрезка, вставляем обратно в исходное изображение
        if remove_border:
            debug_img.paste(debug_img_cropped, (left, top))
            debug_img = debug_img_cropped
        
        # # 6. Добавляем легенду
        # legend_y = height - 60
        # draw = ImageDraw.Draw(debug_img, 'RGBA')
        
        # # Полупрозрачный фон для легенды
        # draw.rectangle(
        #     [(10, height - 70), (300, height - 10)],
        #     fill=(0, 0, 0, 180)
        # )
        
        # draw.text((20, height - 60), "🔵 Синяя рамка: границы содержимого", fill=(0, 0, 255, 255))
        # draw.text((20, height - 45), "🔴 Красные линии: разрезы", fill=(255, 0, 0, 255))
        # draw.text((20, height - 30), f"🟡 Сетка: {grid_rows}x{grid_cols}", fill=(255, 255, 0, 255))
        
        # Сохраняем
        debug_img.save(output_path)
        logger.info(f"✅ Отладочное изображение сохранено: {output_path}")

    # Добавьте этот метод в класс ImageGenerator:
    async def generate_debug_visualization(
        self,
        prompt: str = "",
        grid_rows: int = 3,
        grid_cols: int = 3,
        output_filename: str = "debug_grid.png"
    ) -> Optional[Path]:
        """
        Генерирует отладочную визуализацию с разметкой.
        """
        try:
            if not self.use_local_file:
                logger.error("Отладка доступна только в тестовом режиме с локальным файлом")
                return None
            
            # Находим локальный файл
            local_path = self._find_file(self.local_file_path)
            if not local_path:
                raise FileNotFoundError(f"Файл {self.local_file_path} не найден")
            
            # Читаем файл
            with open(local_path, "rb") as f:
                grid_bytes = f.read()
            
            # Создаем путь для отладочного изображения
            debug_path = settings.TEMP_DIR / output_filename
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Рисуем разметку
            self._draw_grid_debug(
                grid_bytes=grid_bytes,
                grid_rows=grid_rows,
                grid_cols=grid_cols,
                output_path=debug_path,
                remove_border=True
            )
            
            return debug_path
            
        except Exception as e:
            logger.error(f"Ошибка создания отладочной визуализации: {e}")
            return None
            
    async def generate_images(
        self,
        prompt: str,
        count: int = 0,
        size: str = "512x512",
        grid_rows: int = 3,
        grid_cols: int = 3,
        reference_image_path: Optional[str] = None,
    ) -> List[Path]:
        """Генерация стикеров с удалением рамки, но без фильтров шума."""
        try:
            if self.use_local_file:
                logger.info(f"🔧 ТЕСТОВЫЙ РЕЖИМ: Использую локальный файл {self.local_file_path}")
                return await self._generate_from_local_file(
                    count=count,
                    grid_rows=grid_rows,
                    grid_cols=grid_cols
                )
            
            # Обычный режим с API
            logger.info(
                f"Генерация листа-сетки {grid_rows}x{grid_cols} (Kie.ai nano-banana-pro) "
                f"для промпта: {prompt[:50]}..."
            )

            grid_prompt = _build_grid_prompt(prompt, grid_rows, grid_cols)

            # Загружаем референс-фото в Kie.ai File Upload API (получаем URL),
            # чтобы передать его в input.image_input.
            image_input: List[str] = []
            if reference_image_path:
                try:
                    ref_path = Path(reference_image_path)
                    if ref_path.exists():
                        ref_url = await self._upload_reference_image(ref_path)
                        if ref_url:
                            image_input = [ref_url]
                except Exception as e:
                    logger.warning(f"Не удалось подготовить reference_image_path для Kie.ai: {e}")

            grid_bytes = await self._generate_single(
                prompt=grid_prompt,
                size=size,
                aspect_ratio=_grid_to_aspect_ratio(grid_rows, grid_cols),
                image_input=image_input,
            )
            if not grid_bytes:
                raise Exception("Пустой результат генерации сетки")

            # Сохраняем сырую картинку от Kie без изменений
            settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
            kie_raw_path = settings.TEMP_DIR / f"kie_raw_{int(time.time() * 1000)}.png"
            kie_raw_path.write_bytes(grid_bytes)
            logger.info(f"Сохранена сырая картинка от Kie: {kie_raw_path}")

            return self._process_grid_bytes(grid_bytes, count, grid_rows, grid_cols)

        except Exception as e:
            logger.error(f"Ошибка генерации сетки стикеров: {e}")
            return []

    async def _upload_reference_image(self, file_path: Path) -> Optional[str]:
        """Загружает файл в Kie.ai и возвращает URL для input.image_input."""
        if not settings.KIE_API_KEY:
            return None

        headers = {"Authorization": f"Bearer {settings.KIE_API_KEY}"}
        upload_url = f"{KIE_UPLOAD_BASE_URL}/api/file-stream-upload"

        with file_path.open("rb") as f:
            mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            files = {"file": (file_path.name, f, mime_type)}
            data = {"uploadPath": KIE_UPLOAD_PATH, "fileName": file_path.name}
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(upload_url, headers=headers, files=files, data=data)

        if resp.status_code != 200:
            logger.warning(f"Kie.ai upload failed: status={resp.status_code}, body={resp.text}")
            return None

        try:
            payload = resp.json()
            # Пример ответа в доках: data.downloadUrl
            if not payload.get("success"):
                return None
            data_obj = payload.get("data") or {}
            return data_obj.get("downloadUrl") or data_obj.get("fileUrl")
        except Exception:
            return None
    
    async def _generate_from_local_file(
        self,
        count: int = 0,
        grid_rows: int = 3,
        grid_cols: int = 3,
    ) -> List[Path]:
        """Генерирует стикеры из локального файла с сеткой."""
        try:
            # Поиск файла
            local_path = self._find_file(self.local_file_path)
            if not local_path:
                raise FileNotFoundError(f"Файл {self.local_file_path} не найден")
            
            logger.info(f"✅ Найден локальный файл: {local_path}")
            
            # Читаем файл
            with open(local_path, "rb") as f:
                grid_bytes = f.read()
            
            # Если это JPG, просто конвертируем в PNG без дополнительной обработки
            if local_path.suffix.lower() in ['.jpg', '.jpeg']:
                logger.info("Конвертация JPG в PNG...")
                img = Image.open(BytesIO(grid_bytes))
                buf = BytesIO()
                img.save(buf, format="PNG")
                grid_bytes = buf.getvalue()
            
            return self._process_grid_bytes(grid_bytes, count, grid_rows, grid_cols)
            
        except Exception as e:
            logger.error(f"Ошибка при работе с локальным файлом: {e}")
            return []
    
    def _find_file(self, filename: str) -> Optional[Path]:
        """Ищет файл в нескольких стандартных местах."""
        paths_to_try = [
            Path(filename),
            settings.TEMP_DIR / filename,
            Path.cwd() / filename,
            Path.cwd() / "temp" / filename,
        ]
        
        for path in paths_to_try:
            if path.exists():
                return path
        return None
    
    def _process_grid_bytes(
        self, 
        grid_bytes: bytes, 
        count: int, 
        grid_rows: int, 
        grid_cols: int
    ) -> List[Path]:
        """Обрабатывает байты сетки и возвращает пути к нарезанным стикерам."""
        # Используем нарезку с удалением рамки, но без фильтров шума
        tiles = _split_grid_png(grid_bytes, grid_rows, grid_cols, remove_border=True)
        
        if not tiles:
            raise Exception("Не удалось разрезать сетку на тайлы")

        if count and count > 0:
            tiles = tiles[:count]

        images: List[Path] = []
        ts = int(time.time() * 1000)
        for i, tile_bytes in enumerate(tiles):
            image_path = settings.TEMP_DIR / f"sticker_{ts}_{i}.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(tile_bytes)
            images.append(image_path)
            
            # Логируем размер файла для отладки
            size_kb = len(tile_bytes) / 1024
            logger.info(f"✅ Сохранен стикер {i+1}/{len(tiles)}: {image_path} ({size_kb:.1f} KB)")

        return images

    async def _generate_single(
        self,
        prompt: str,
        size: str,
        aspect_ratio: Optional[str] = None,
        image_input: Optional[List[str]] = None,
    ) -> Optional[bytes]:
        """Сгенерировать одно изображение через Kie.ai и вернуть байты PNG."""
        if not settings.KIE_API_KEY:
            logger.error("KIE_API_KEY не задан в настройках")
            return None

        aspect_ratio = aspect_ratio or _size_to_aspect_ratio(size)

        headers = {
            "Authorization": f"Bearer {settings.KIE_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.KIE_MODEL,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": "1K",
                "output_format": "png",
                "image_input": image_input or [],
            },
        }

        async with httpx.AsyncClient(base_url=KIE_API_BASE_URL, timeout=180) as client:
            # 1. Создаем задачу генерации
            try:
                resp = await client.post(
                    "/api/v1/jobs/createTask",
                    json=payload,
                    headers=headers,
                )
            except Exception as e:
                logger.error(f"Ошибка запроса к Kie.ai (createTask): {e}")
                return None

            if resp.status_code != 200:
                logger.error(f"Kie.ai createTask вернул статус {resp.status_code}: {resp.text}")
                return None

            data = resp.json()
            if data.get("code") != 200:
                logger.error(f"Kie.ai createTask ошибка: code={data.get('code')}, msg={data.get('msg')}")
                return None

            task_id = data.get("data", {}).get("taskId")
            if not task_id:
                logger.error(f"Kie.ai createTask не вернул taskId: {data}")
                return None

            logger.info(f"Kie.ai задача создана, taskId={task_id}")

            # 2. Пуллим статус задачи
            max_wait_seconds = 300
            poll_interval = 3
            start_time = time.time()

            result_url: Optional[str] = None

            while time.time() - start_time < max_wait_seconds:
                try:
                    status_resp = await client.get(
                        "/api/v1/jobs/recordInfo",
                        params={"taskId": task_id},
                        headers=headers,
                    )
                except Exception as e:
                    logger.error(f"Ошибка запроса к Kie.ai (recordInfo): {e}")
                    return None

                if status_resp.status_code != 200:
                    logger.error(
                        f"Kie.ai recordInfo вернул статус {status_resp.status_code}: {status_resp.text}"
                    )
                    return None

                status_data = status_resp.json()
                if status_data.get("code") != 200:
                    logger.error(
                        f"Kie.ai recordInfo ошибка: code={status_data.get('code')}, msg={status_data.get('msg')}"
                    )
                    return None

                task_data = status_data.get("data") or {}
                state = task_data.get("state")

                logger.info(f"Kie.ai задача {task_id} состояние: {state}")

                if state == "fail":
                    logger.error(
                        f"Генерация Kie.ai не удалась: failCode={task_data.get('failCode')}, "
                        f"failMsg={task_data.get('failMsg')}"
                    )
                    return None

                if state == "success":
                    result_json_str = task_data.get("resultJson") or ""
                    try:
                        result_json = json.loads(result_json_str)
                        urls = result_json.get("resultUrls") or []
                        if not urls:
                            logger.error(f"Kie.ai success, но resultUrls пустой: {result_json}")
                            return None
                        result_url = urls[0]
                        break
                    except Exception as e:
                        logger.error(f"Ошибка парсинга resultJson от Kie.ai: {e}, raw={result_json_str}")
                        return None

                await asyncio.sleep(poll_interval)

            if not result_url:
                logger.error("Kie.ai не вернул результат в отведенное время")
                return None

            # 3. Скачиваем изображение по URL
            try:
                img_resp = await client.get(result_url)
            except Exception as e:
                logger.error(f"Ошибка скачивания изображения с Kie.ai: {e}")
                return None

            if img_resp.status_code != 200:
                logger.error(
                    f"Ошибка скачивания изображения с Kie.ai, статус {img_resp.status_code}: {img_resp.text}"
                )
                return None

            return img_resp.content