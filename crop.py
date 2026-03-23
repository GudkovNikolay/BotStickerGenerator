import cv2
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

def crop_by_horizontal_vertical_pixels(input_path, output_path, visualize=True, padding=20, tolerance=30, min_thickness=5):
    """
    Метод обрезки:
    1. Определяем цвет фона
    2. Для каждой горизонтали находим первый и последний пиксель, отличающийся от фона
    3. Запоминаем все пиксели между ними (сохраняем маску)
    4. Для каждой вертикали на исходном изображении, используя запомненную маску,
       находим первый и последний пиксель, который НЕ БЫЛ ОТБРОШЕН на шаге 2
    5. Оставляем только пиксели, которые прошли оба этапа
    """
    # Чтение изображения
    img = cv2.imread(input_path)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    height, width = img.shape[:2]
    
    print("=== ШАГ 1: Определяем цвет фона ===")
    
    # Определяем цвет фона из углов
    corners = [
        img_rgb[0, 0],
        img_rgb[0, width-1],
        img_rgb[height-1, 0],
        img_rgb[height-1, width-1]
    ]
    bg_color = np.mean(corners, axis=0)
    print(f"Цвет фона (RGB): {bg_color}")
    print(f"Допуск: {tolerance}")
    print(f"Минимальная толщина: {min_thickness} пикселей")
    
    # Функция проверки отличается ли пиксель от фона
    def is_different(pixel, bg, tol):
        return np.any(np.abs(pixel - bg) > tol)
    
    print("\n=== ШАГ 2: Обрабатываем каждую горизонталь ===")
    
    # Создаем маску (1 - оставить, 0 - удалить)
    # Изначально все пиксели помечены как удаленные
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # Для отладки: сохраняем информацию по каждой строке
    debug_rows = []
    
    # Перебираем каждую горизонталь (строку)
    for y in range(height):
        row = img_rgb[y, :]
        
        # Находим первый и последний пиксель, отличающийся от фона
        first_diff = None
        last_diff = None
        
        # Ищем первый отличающийся пиксель (слева направо)
        for x in range(width):
            if is_different(row[x], bg_color, tolerance):
                first_diff = x
                break
        
        # Ищем последний отличающийся пиксель (справа налево)
        for x in range(width - 1, -1, -1):
            if is_different(row[x], bg_color, tolerance):
                last_diff = x
                break
        
        # Если нашли оба пикселя
        if first_diff is not None and last_diff is not None:
            width_segment = last_diff - first_diff + 1
            
            # Проверяем, достаточно ли широкая линия
            if width_segment >= min_thickness:
                # Помечаем все пиксели между ними как "оставить"
                mask[y, first_diff:last_diff+1] = 1
                
                # Для отладки
                debug_rows.append({
                    'y': y,
                    'first': first_diff,
                    'last': last_diff,
                    'width': width_segment
                })
                
                if y < 10 or y % 50 == 0:
                    print(f"Строка {y}: первый={first_diff}, последний={last_diff}, ширина={width_segment} - СОХРАНЕНО")
            else:
                if y < 10:
                    print(f"Строка {y}: ширина={width_segment} меньше {min_thickness} - ИГНОРИРУЕМ")
        else:
            if y < 10:
                print(f"Строка {y}: нет отличающихся пикселей")
    
    print(f"\nСтрок с сохраненными пикселями: {len(debug_rows)}")
    print(f"Всего пикселей после горизонтальной обработки: {np.sum(mask)}")
    
    # Визуализация маски после горизонтальной обработки
    if visualize:
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        
        # Оригинал
        axes[0, 0].imshow(img_rgb)
        axes[0, 0].set_title('1. Оригинал')
        axes[0, 0].axis('off')
        
        # Маска после горизонтальной обработки
        axes[0, 1].imshow(mask, cmap='gray')
        axes[0, 1].set_title('2. Маска после горизонтальной обработки\n(белое - оставить)')
        axes[0, 1].axis('off')
        
        # Результат применения маски (наложить на оригинал)
        masked_horizontal = img_rgb.copy()
        masked_horizontal[mask == 0] = bg_color.astype(np.uint8)
        axes[0, 2].imshow(masked_horizontal)
        axes[0, 2].set_title('3. Результат горизонтальной обрезки\n(удалены пиксели вне диапазона)')
        axes[0, 2].axis('off')
        
        # Отображаем границы на оригинале
        debug_img = img_rgb.copy()
        for row_info in debug_rows:
            y = row_info['y']
            first = row_info['first']
            last = row_info['last']
            cv2.line(debug_img, (first, y), (last, y), (0, 255, 0), 1)
        axes[1, 0].imshow(debug_img)
        axes[1, 0].set_title('4. Найденные границы на горизонталях\n(зеленые линии - сохраненные)')
        axes[1, 0].axis('off')
        
        # Гистограмма распределения ширины строк
        widths = [r['width'] for r in debug_rows]
        axes[1, 1].hist(widths, bins=20)
        axes[1, 1].set_xlabel('Ширина строки (пиксели)')
        axes[1, 1].set_ylabel('Количество строк')
        axes[1, 1].set_title('Распределение ширины строк')
        axes[1, 1].axvline(min_thickness, color='r', linestyle='--', label=f'Порог: {min_thickness}')
        axes[1, 1].legend()
        
        # Статистика
        axes[1, 2].text(0.1, 0.9, f"Всего строк: {height}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.8, f"Строк с пикселями: {len(debug_rows)}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.7, f"Мин. ширина: {min(widths) if widths else 0}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.6, f"Макс. ширина: {max(widths) if widths else 0}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.5, f"Сред. ширина: {np.mean(widths) if widths else 0:.1f}", transform=axes[1, 2].transAxes)
        axes[1, 2].axis('off')
        axes[1, 2].set_title('Статистика горизонтальной обработки')
        
        plt.tight_layout()
        plt.show()
    
    print("\n=== ШАГ 3: Обрабатываем каждую вертикаль ===")
    
    # Создаем финальную маску (на основе горизонтальной, но с вертикальной фильтрацией)
    final_mask = np.zeros((height, width), dtype=np.uint8)
    debug_cols = []
    
    # Перебираем каждую вертикаль (столбец)
    for x in range(width):
        # Получаем колонку из исходного изображения
        col = img_rgb[:, x, :]
        
        # Находим первый и последний пиксель, который НЕ БЫЛ УДАЛЕН на горизонтальном этапе
        # То есть ищем пиксели, где mask[y, x] == 1
        first_valid = None
        last_valid = None
        
        # Ищем первый валидный пиксель (сверху вниз)
        for y in range(height):
            if mask[y, x] == 1:  # Пиксель прошел горизонтальную фильтрацию
                first_valid = y
                break
        
        # Ищем последний валидный пиксель (снизу вверх)
        for y in range(height - 1, -1, -1):
            if mask[y, x] == 1:
                last_valid = y
                break
        
        # Если нашли оба пикселя
        if first_valid is not None and last_valid is not None:
            height_segment = last_valid - first_valid + 1
            
            # Проверяем, достаточно ли высокая линия
            if height_segment >= min_thickness:
                # Помечаем все пиксели между ними как "оставить" в финальной маске
                final_mask[first_valid:last_valid+1, x] = 1
                
                debug_cols.append({
                    'x': x,
                    'first': first_valid,
                    'last': last_valid,
                    'height': height_segment
                })
                
                if x < 10 or x % 50 == 0:
                    print(f"Столбец {x}: первый={first_valid}, последний={last_valid}, высота={height_segment} - СОХРАНЕНО")
            else:
                if x < 10:
                    print(f"Столбец {x}: высота={height_segment} меньше {min_thickness} - ИГНОРИРУЕМ")
        else:
            if x < 10:
                print(f"Столбец {x}: нет валидных пикселей после горизонтальной обработки")
    
    print(f"\nСтолбцов с сохраненными пикселями: {len(debug_cols)}")
    print(f"Всего пикселей после вертикальной обработки: {np.sum(final_mask)}")
    
    # Визуализация после вертикальной обработки
    if visualize:
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        
        # Маска после горизонтальной обработки
        axes[0, 0].imshow(mask, cmap='gray')
        axes[0, 0].set_title('1. Маска после горизонтальной\nобработки')
        axes[0, 0].axis('off')
        
        # Финальная маска
        axes[0, 1].imshow(final_mask, cmap='gray')
        axes[0, 1].set_title('2. Финальная маска\n(после вертикальной обработки)')
        axes[0, 1].axis('off')
        
        # Результат применения финальной маски
        final_result = img_rgb.copy()
        final_result[final_mask == 0] = bg_color.astype(np.uint8)
        axes[0, 2].imshow(final_result)
        axes[0, 2].set_title('3. Финальный результат\n(удалены пиксели вне диапазонов)')
        axes[0, 2].axis('off')
        
        # Отображаем вертикальные границы на промежуточном результате
        debug_img_v = img_rgb.copy()
        debug_img_v[mask == 0] = [200, 200, 200]  # Серый фон для наглядности
        for col_info in debug_cols:
            x = col_info['x']
            first = col_info['first']
            last = col_info['last']
            cv2.line(debug_img_v, (x, first), (x, last), (0, 255, 0), 1)
        axes[1, 0].imshow(debug_img_v)
        axes[1, 0].set_title('4. Вертикальные границы\n(зеленые линии - сохраненные)')
        axes[1, 0].axis('off')
        
        # Гистограмма высоты столбцов
        heights = [c['height'] for c in debug_cols]
        axes[1, 1].hist(heights, bins=20)
        axes[1, 1].set_xlabel('Высота столбца (пиксели)')
        axes[1, 1].set_ylabel('Количество столбцов')
        axes[1, 1].set_title('Распределение высоты столбцов')
        axes[1, 1].axvline(min_thickness, color='r', linestyle='--', label=f'Порог: {min_thickness}')
        axes[1, 1].legend()
        
        # Статистика
        axes[1, 2].text(0.1, 0.9, f"Всего столбцов: {width}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.8, f"Столбцов с пикселями: {len(debug_cols)}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.7, f"Мин. высота: {min(heights) if heights else 0}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.6, f"Макс. высота: {max(heights) if heights else 0}", transform=axes[1, 2].transAxes)
        axes[1, 2].text(0.1, 0.5, f"Сред. высота: {np.mean(heights) if heights else 0:.1f}", transform=axes[1, 2].transAxes)
        axes[1, 2].axis('off')
        axes[1, 2].set_title('Статистика вертикальной обработки')
        
        plt.tight_layout()
        plt.show()
    
    # Находим bounding box для финальной обрезки
    coords = cv2.findNonZero(final_mask)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        
        # Добавляем отступы
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(width - x, w + 2 * padding)
        h = min(height - y, h + 2 * padding)
        
        # Применяем финальную маску и обрезаем
        result_with_mask = img_rgb.copy()
        result_with_mask[final_mask == 0] = bg_color.astype(np.uint8)
        cropped = result_with_mask[y:y+h, x:x+w]
        
        # Создаем альфа-канал для прозрачности
        alpha = (final_mask[y:y+h, x:x+w] * 255).astype(np.uint8)
        result_rgba = cv2.cvtColor(cropped, cv2.COLOR_RGB2RGBA)
        result_rgba[:, :, 3] = alpha
        
        # Сохраняем
        result_pil = Image.fromarray(result_rgba)
        result_pil.save(output_path)
        
        print(f"\n=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ===")
        print(f"Bounding box: x={x}, y={y}, w={w}, h={h}")
        print(f"Размер после отступов: {w} x {h}")
        print(f"Сохранено: {output_path}")
        
        return result_rgba
    
    return None

# Использование
if __name__ == "__main__":
    input_file = 'temp_images/sticker_1774267536163_0.png'
    
    result = crop_by_horizontal_vertical_pixels(
        input_file,
        'sticker_pixel_cropped.png',
        visualize=True,
        padding=30,
        tolerance=5,
        min_thickness=5  # Игнорируем линии тоньше 5 пикселей
    )