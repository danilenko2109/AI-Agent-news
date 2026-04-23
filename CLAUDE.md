# AI News Agent

## Установка `uv`
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Установка зависимостей
```bash
uv sync
```

## Запуск
1. Скопируйте `.env.example` в `.env` и заполните ключи.
2. Запустите сервис:
```bash
uv run python run.py
```

## Как протестировать
```bash
uv run python -m compileall app run.py
uv run python scripts/smoke_test.py
```

## Пример сценария
1. В Telegram admin-боте отправьте `/start`.
2. Нажмите **Добавить канал**, укажите bot token и `@target_channel`.
3. Нажмите **Добавить доноры**, добавьте `@source_channel`.
4. Отправьте новый пост в source-канал.
5. Система сделает рерайт, создаст картинку и опубликует в канал клиента.
