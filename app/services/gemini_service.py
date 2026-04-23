from __future__ import annotations

import asyncio

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

from app.config import settings
from app.logger import logger

try:
    import google.generativeai as genai
except ModuleNotFoundError:  # pragma: no cover
    genai = None

SYSTEM_PROMPT = (
    "Ти редактор українського новинного медіа. "
    "Перепиши новину унікально, без згадок інших каналів. "
    "Додай короткий заголовок зверху. "
    "Текст має бути читабельним і сучасним."
)


class GeminiService:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.gemini_key
        self.model_name = "gemini-1.5-flash"
        if self.api_key and genai:
            genai.configure(api_key=self.api_key)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    async def rewrite(self, text: str) -> str:
        if not self.api_key or not genai:
            return f"📰 Оновлена новина\n\n{text.strip()}"

        def _call() -> str:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(f"{SYSTEM_PROMPT}\n\nНовина:\n{text}")
            return response.text.strip()

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            logger.error("Gemini rewrite failed: {}", exc)
            raise

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    async def generate_image_prompt(self, text: str) -> str:
        if not self.api_key or not genai:
            return f"Editorial breaking news illustration, {text[:120]}"

        def _call() -> str:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                "Generate one short image prompt in English for a modern editorial news illustration."
                f"\nNews:\n{text}"
            )
            return response.text.strip().replace("\n", " ")

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            logger.error("Gemini prompt failed: {}", exc)
            raise
