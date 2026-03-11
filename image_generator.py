"""
Генерация изображений через Kie.ai (nano-banana-pro).
"""
import asyncio
import json
import time
from pathlib import Path
from typing import List, Optional

import httpx

from config import settings
import logging

logger = logging.getLogger(__name__)


KIE_API_BASE_URL = "https://api.kie.ai"


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
                # горизонтальное изображение
                return "16:9"
            # вертикальное
            return "9:16"
    except Exception:
        pass
    return "1:1"


class ImageGenerator:
    """Генератор изображений через API Kie.ai (nano-banana-pro)."""

    def __init__(self):
        self.backend = "kie_ai"

    async def generate_images(
        self,
        prompt: str,
        count: int = 5,
        size: str = "512x512",
    ) -> List[Path]:
        """Генерация изображений по промпту локально.

        Args:
            prompt: Текстовый промпт
            count: Количество изображений (в MVP ограничиваем максимум 5)
            size: Размер изображения (например, "512x512")

        Returns:
            Список путей к сохраненным изображениям
        """
        images: List[Path] = []

        for i in range(min(count, 5)):
            try:
                logger.info(
                    f"Генерация изображения {i+1}/{min(count, 5)} (Kie.ai nano-banana-pro) "
                    f"для промпта: {prompt[:50]}..."
                )

                image_bytes = await self._generate_single(prompt=prompt, size=size)
                if not image_bytes:
                    raise Exception("Пустой результат генерации")

                image_path = settings.TEMP_DIR / f"generated_{i}_{int(time.time() * 1000)}.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(image_bytes)

                images.append(image_path)

                if i < count - 1:
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Ошибка генерации изображения {i+1}: {e}")
                continue

        return images

    async def _generate_single(self, prompt: str, size: str) -> Optional[bytes]:
        """Сгенерировать одно изображение через Kie.ai и вернуть байты PNG."""
        if not settings.KIE_API_KEY:
            logger.error("KIE_API_KEY не задан в настройках")
            return None

        aspect_ratio = _size_to_aspect_ratio(size)

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
                "image_input": [],
            },
        }

        async with httpx.AsyncClient(base_url=KIE_API_BASE_URL, timeout=60) as client:
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
            max_wait_seconds = 120
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
