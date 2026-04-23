from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import quote
from urllib.request import urlopen

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:  # pragma: no cover
    def retry(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

from app.logger import logger

try:
    from PIL import Image, ImageDraw
except ModuleNotFoundError:  # pragma: no cover
    Image = None
    ImageDraw = None


class ImageService:
    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    async def generate(self, prompt: str) -> Path:
        safe_name = prompt[:24].replace(" ", "_").replace("/", "_") or "news"
        output = Path(gettempdir()) / f"news_{safe_name}.jpg"
        pollinations_url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1024&height=1024&nologo=true"

        def _download() -> None:
            with urlopen(pollinations_url, timeout=20) as response:  # noqa: S310
                output.write_bytes(response.read())

        try:
            await asyncio.to_thread(_download)
            logger.debug("Image generated: {}", output)
            return output
        except Exception as exc:
            logger.error("Pollinations failed, creating fallback image: {}", exc)
            await self._fallback_image(output, prompt)
            return output

    async def _fallback_image(self, output: Path, prompt: str) -> None:
        if Image is None or ImageDraw is None:
            await asyncio.to_thread(output.write_bytes, f"AI NEWS\n{prompt}".encode("utf-8"))
            return

        def _draw() -> None:
            image = Image.new("RGB", (1024, 1024), color=(25, 35, 52))
            draw = ImageDraw.Draw(image)
            draw.text((40, 40), "AI NEWS", fill=(255, 255, 255))
            draw.text((40, 100), prompt[:120], fill=(200, 220, 255))
            image.save(output, "JPEG", quality=90)

        await asyncio.to_thread(_draw)
