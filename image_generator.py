"""
Генерация изображений локально через StableDiffusionPipeline (diffusers).
"""
import asyncio
import time
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import torch
from diffusers import StableDiffusionPipeline

from config import settings
import logging

logger = logging.getLogger(__name__)

_pipeline: Optional[StableDiffusionPipeline] = None


def _get_pipeline() -> StableDiffusionPipeline:
    """Ленивая инициализация StableDiffusionPipeline.

    Модель один раз скачивается с Hugging Face (по HF_MODEL), дальше работает локально.
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    model_id = settings.HF_MODEL or "runwayml/stable-diffusion-v1-5"
    auth_token = settings.HF_TOKEN or None

    logger.info(f"Загрузка модели Stable Diffusion: {model_id}")

    kwargs = {}
    if torch.cuda.is_available():
        kwargs["torch_dtype"] = torch.float16

    pipe = StableDiffusionPipeline.from_pretrained(
        model_id,
        use_auth_token=auth_token,
        **kwargs,
    )

    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
        logger.info("Stable Diffusion запущен на GPU")
    else:
        logger.info("Stable Diffusion запущен на CPU (будет медленно)")

    _pipeline = pipe
    return _pipeline


class ImageGenerator:
    """Генератор изображений через локальный Stable Diffusion (diffusers)."""

    def __init__(self):
        # Сейчас используем только локальный backend через diffusers
        self.backend = "local"

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
                    f"Генерация изображения {i+1}/{min(count, 5)} (local SD) "
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
        """Сгенерировать одно изображение и вернуть байты PNG."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate_single_sync, prompt, size)

    def _generate_single_sync(self, prompt: str, size: str) -> Optional[bytes]:
        """Синхронная генерация одного изображения через StableDiffusionPipeline."""
        pipe = _get_pipeline()

        # Парсинг размера "WxH"
        width = height = 512
        if "x" in size:
            try:
                w, h = size.lower().split("x")
                width = int(w)
                height = int(h)
            except Exception:
                pass

        # SD обычно требует кратность 8
        width = max(256, min(1024, width // 8 * 8))
        height = max(256, min(1024, height // 8 * 8))

        result = pipe(
            prompt,
            width=width,
            height=height,
            num_inference_steps=25,
            guidance_scale=7.5,
        )

        if not result.images:
            return None

        img = result.images[0]
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()


