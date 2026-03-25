from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import cv2

from PIL import Image

try:
    # rembg может отсутствовать в окружении; тогда используем fallback.
    from rembg import remove as rembg_remove
except Exception:  # pragma: no cover
    rembg_remove = None


def crop_to_nontransparent_bbox(img: Image.Image, alpha_threshold: int = 1) -> Image.Image:
    """Обрезает изображение по bbox ненулевой (почти) альфы."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    alpha = img.split()[-1]
    # Порог, чтобы отрезать почти-прозрачные артефакты
    alpha = alpha.point(lambda p: 255 if p >= alpha_threshold else 0)
    bbox = alpha.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def crop_by_corner_background(
    img: Image.Image, tolerance: int = 30, sample_margin: int = 0
) -> Image.Image:
    """
    Fallback-обрезка: ищем фон по углам и отрезаем всё, что похоже на фон.
    Подходит, если rembg недоступен.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    m = max(0, min(sample_margin, min(w, h) // 10))

    corners = [
        img.getpixel((m, m)),
        img.getpixel((w - 1 - m, m)),
        img.getpixel((m, h - 1 - m)),
        img.getpixel((w - 1 - m, h - 1 - m)),
    ]
    bg_color = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    def is_bg(px: Tuple[int, int, int]) -> bool:
        return all(abs(px[i] - bg_color[i]) <= tolerance for i in range(3))

    # Находим bbox по сканированию центральных полос.
    # Это быстрее, чем per-pixel поиск по всему изображению.
    left = 0
    for x in range(w):
        if not all(
            is_bg(img.getpixel((x, y))) for y in range(h // 2 - 5, h // 2 + 6) if 0 <= y < h
        ):
            left = max(0, x)
            break

    right = w
    for x in range(w - 1, -1, -1):
        if not all(
            is_bg(img.getpixel((x, y))) for y in range(h // 2 - 5, h // 2 + 6) if 0 <= y < h
        ):
            right = min(w, x + 1)
            break

    top = 0
    for y in range(h):
        if not all(
            is_bg(img.getpixel((x, y))) for x in range(w // 2 - 5, w // 2 + 6) if 0 <= x < w
        ):
            top = max(0, y)
            break

    bottom = h
    for y in range(h - 1, -1, -1):
        if not all(
            is_bg(img.getpixel((x, y))) for x in range(w // 2 - 5, w // 2 + 6) if 0 <= x < w
        ):
            bottom = min(h, y + 1)
            break

    if right <= left or bottom <= top:
        return img
    return img.crop((left, top, right, bottom))


def remove_background_and_crop(
    input_path: str | Path,
    output_path: str | Path,
    *,
    alpha_threshold: int = 1,
    bg_tolerance: int = 30,
) -> Image.Image:
    """
    Удаляет фон (если доступен rembg), затем обрезает до содержимого и сохраняет PNG.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    img = Image.open(input_path)

    if rembg_remove is not None:
        img = rembg_remove(img)
        img = crop_to_nontransparent_bbox(img, alpha_threshold=alpha_threshold)
    else:
        # fallback: просто crop по цвету фона
        img = crop_by_corner_background(img, tolerance=bg_tolerance)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return img


def crop_image_to_sticker_content(
    img: Image.Image,
    *,
    alpha_threshold: int = 1,
    bg_tolerance: int = 100,
    magenta_bg: bool = True,  # Новый параметр
) -> Image.Image:
    """
    Версия "in-memory": используется внутри пайплайна стикера.
    
    Args:
        img: Входное изображение
        alpha_threshold: Порог прозрачности для обрезки
        bg_tolerance: Допуск для удаления фона по цвету
        magenta_bg: Если True, удаляет маджентовый фон (#FF00FF)
    """
    # Если включен режим маджентового фона
    if magenta_bg:
        # Преобразуем в RGB если нужно
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Конвертируем в numpy
        img_array = np.array(img)
        
        # Определяем цвет мадженты
        magenta = np.array([255, 0, 255])
        
        # Вычисляем расстояние до мадженты
        diff = np.sqrt(np.sum((img_array - magenta) ** 2, axis=2))
        
        # Создаем маску: пиксели, которые НЕ маджента
        mask = (diff > bg_tolerance).astype(np.uint8) * 255
        
        # Морфологическая очистка для удаления шума
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        # Находим самый большой контур (объект)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            largest = max(contours, key=cv2.contourArea)
            
            # Создаем чистую маску только для объекта
            clean_mask = np.zeros_like(mask)
            cv2.drawContours(clean_mask, [largest], -1, 255, -1)
            
            # Добавляем альфа-канал
            rgba = cv2.cvtColor(img_array, cv2.COLOR_RGB2RGBA)
            rgba[:, :, 3] = clean_mask
            
            # Обрезаем по bounding box
            coords = cv2.findNonZero(clean_mask)
            if coords is not None:
                x, y, w, h = cv2.boundingRect(coords)
                # Добавляем небольшой отступ
                padding = 0#20
                x = max(0, x - padding)
                y = max(0, y - padding)
                w = min(img_array.shape[1] - x, w + 2 * padding)
                h = min(img_array.shape[0] - y, h + 2 * padding)
                rgba = rgba[y:y+h, x:x+w]
            
            return Image.fromarray(rgba)
        
        # Если не нашли объект, возвращаем оригинал
        return img
    
    # Старая логика для обычных случаев
    if rembg_remove is not None:
        img = rembg_remove(img)
        return crop_to_nontransparent_bbox(img, alpha_threshold=alpha_threshold)
    return crop_by_corner_background(img, tolerance=bg_tolerance)
