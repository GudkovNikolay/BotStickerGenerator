from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

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
    bg_tolerance: int = 30,
) -> Image.Image:
    """
    Версия "in-memory": используется внутри пайплайна стикера.
    """
    if rembg_remove is not None:
        img = rembg_remove(img)
        return crop_to_nontransparent_bbox(img, alpha_threshold=alpha_threshold)
    return crop_by_corner_background(img, tolerance=bg_tolerance)
