"""
AI text processor using Google Gemini 1.5 Flash.
Generates rewritten Ukrainian news posts and image prompts.
"""

import json
import logging
import os
import re
import asyncio
import urllib.parse

import google.generativeai as genai

logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_MODEL = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=genai.types.GenerationConfig(
        temperature=0.7,
        max_output_tokens=1024,
        response_mime_type="application/json",
    ),
)

SYSTEM_PROMPT = """Ти — професійний український редактор новинного Telegram-каналу.

Твоє завдання:
1. Переписати новину своїми словами — чисто, без реклами та посилань.
2. Видалити всі згадки про інші Telegram-канали, посилання, хештеги, @юзернейми.
3. Зробити заголовок коротким (до 10 слів), цікавим і клікабельним.
4. Зберегти мову — ТІЛЬКИ українська.
5. Текст — 3-5 речень, інформативний.
6. Придумати короткий англійський prompt для генерації реалістичного зображення до новини (20-30 слів).

ЗАВЖДИ повертай ТІЛЬКИ валідний JSON без жодного Markdown, без коментарів:
{"title": "...", "text": "...", "image_prompt": "..."}
"""

PROMPT_STYLES: dict[str, str] = {
    "default": SYSTEM_PROMPT,
    "breaking": SYSTEM_PROMPT + "\nВикористовуй ТЕРМІНОВО / BREAKING NEWS на початку заголовку.",
    "analytical": SYSTEM_PROMPT + "\nДодай аналітичний коментар наприкінці тексту (1 речення).",
}
GEMINI_RETRIES = int(os.getenv("GEMINI_RETRIES", 3))


def _clean_raw_text(text: str) -> str:
    """Strip URLs and TG mentions from raw text before sending to AI."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    return text.strip()


async def rewrite_post(raw_text: str, prompt_style: str = "default") -> dict | None:
    """
    Send raw post text to Gemini and return structured dict:
    {"title": str, "text": str, "image_prompt": str}
    Returns None on failure.
    """
    if not raw_text or len(raw_text) < 30:
        logger.warning("Text too short to process, skipping.")
        return None

    cleaned = _clean_raw_text(raw_text)
    system = PROMPT_STYLES.get(prompt_style, SYSTEM_PROMPT)
    full_prompt = f"{system}\n\nОригінальна новина:\n{cleaned}"

    for attempt in range(1, GEMINI_RETRIES + 1):
        response = None
        try:
            response = await _MODEL.generate_content_async(full_prompt)
            raw_json = (response.text or "").strip()
            # Strip accidental markdown fences
            raw_json = re.sub(r"```json|```", "", raw_json).strip()
            data = json.loads(raw_json)
            if not all(k in data for k in ("title", "text", "image_prompt")):
                raise ValueError("Missing keys in response")
            return data
        except json.JSONDecodeError as e:
            snippet = ((response.text if response else "") or "")[:200]
            logger.error("JSON parse error from Gemini: %s | raw: %s", e, snippet)
            return None
        except Exception as e:
            err = str(e).lower()
            transient = any(
                token in err for token in ("timeout", "429", "resource_exhausted", "unavailable", "deadline")
            )
            if transient and attempt < GEMINI_RETRIES:
                backoff = 2 ** (attempt - 1)
                logger.warning("Gemini transient error (attempt %d/%d): %s", attempt, GEMINI_RETRIES, e)
                await asyncio.sleep(backoff)
                continue
            logger.error("Gemini error: %s", e)
            return None
    return None


def build_image_url(prompt: str, width: int = 1280, height: int = 720) -> str:
    """
    Build a Pollinations AI image URL (free, no API key required).
    Falls back gracefully — if the URL fails at download time, the post
    is still published without an image.
    """
    encoded = urllib.parse.quote(prompt)
    seed = abs(hash(prompt)) % 9999
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&seed={seed}&nologo=true&enhance=true"
    )


def format_telegram_message(title: str, text: str) -> str:
    """Format final Telegram HTML message."""
    return f"<b>{title}</b>\n\n{text}"
