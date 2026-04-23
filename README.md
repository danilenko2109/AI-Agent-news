# 🤖 AI News Agent — MVP SaaS

Автоматизована платформа для українських Telegram-новинних каналів.  
Парсить канали-донори → переписує через Gemini → генерує зображення → публікує.

---

## 🏗️ Архітектура

```
ai-news-agent/
├── main.py              ← Точка входу (asyncio, запускає все)
├── .env                 ← Ваші секрети (не комітити!)
├── requirements.txt
├── bot/
│   └── main_bot.py      ← aiogram 3.x адмін-бот
├── parser/
│   └── listener.py      ← Telethon real-time слухач
├── core/
│   ├── processor.py     ← Gemini 1.5 Flash + Pollinations AI
│   └── publisher.py     ← Публікація постів у Telegram
├── db/
│   ├── models.py        ← SQL-схема таблиць
│   └── database.py      ← aiosqlite CRUD методи
└── data/
    └── newsagent.db     ← SQLite база (auto-create)
```

---

## 🚀 Швидкий старт

### 1. Клонування та середовище

```bash
git clone https://github.com/your/ai-news-agent.git
cd ai-news-agent

python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
mkdir -p data session
```

### 2. Отримання API-ключів

#### Telegram API (для Telethon)
1. Відкрийте https://my.telegram.org/apps
2. Увійдіть через свій Telegram-номер
3. Створіть додаток → скопіюйте **App api_id** та **App api_hash**

#### Адмін-бот Token (для aiogram)
1. Напишіть [@BotFather](https://t.me/BotFather) → `/newbot`
2. Дотримуйтесь інструкцій → скопіюйте **HTTP API token**

#### Google Gemini API Key (безкоштовно)
1. Відкрийте https://aistudio.google.com/app/apikey
2. Натисніть **Create API Key** → скопіюйте ключ

### 3. Налаштування `.env`

```bash
cp .env.example .env
nano .env   # або будь-який редактор
```

Заповніть:
```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE=+380XXXXXXXXX

ADMIN_BOT_TOKEN=1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_TG_ID=123456789        # ваш особистий Telegram ID (для /stats)

GEMINI_API_KEY=AIzaSy...

DATABASE_PATH=./data/newsagent.db
TRIAL_DAYS=3
POST_DELAY=5
MIN_TEXT_LENGTH=20
```

> **Як дізнатись свій Telegram ID?** Напишіть [@userinfobot](https://t.me/userinfobot)

### 4. Перший запуск

```bash
python main.py
```

При першому запуску Telethon попросить:
- Ввести номер телефону (той що в `.env`)
- Ввести код підтвердження з Telegram
- (Можливо) пароль двофакторної автентифікації

Сесія зберігається у `session/parser_session.session` — наступні запуски без авторизації.

---

## 📱 Додавання першого каналу (тест)

### Крок 1: Створіть тестовий канал у Telegram
1. Telegram → «Новий канал» → назвіть, напр. `My AI News Test`
2. Зробіть канал публічним або запишіть числовий ID

### Крок 2: Додайте бота у канал як адміна
1. Відкрийте канал → Адміністратори → Додати адміна
2. Знайдіть вашого бота (за username) → надайте право **Публікувати пости**

### Крок 3: Через адмін-бот
Напишіть вашому адмін-боту:

```
/start          → реєстрація
/add_channel    → слідуйте інструкціям:
                   • Bot Token: токен бота-публікатора
                   • Target Channel: @your_test_channel
                   • Style: default
/add_source     → оберіть канал → введіть @unian_ua або https://t.me/unian_ua
                   (система нормалізує донорів до @username, без дублікатів)
```

### Крок 4: Перезапустіть
```bash
# Ctrl+C → знову:
python main.py
```

Тепер система слухає `@unian_ua`. При кожному новому пості:
1. Telethon отримує текст
2. Gemini переписує → повертає JSON
3. Pollinations генерує зображення
4. Пост публікується у ваш канал

---

## 🗄️ Міграція з SQLite на PostgreSQL

Вся логіка роботи з БД ізольована у `db/database.py`.

**Кроки:**

1. Встановіть залежності:
   ```bash
   pip install asyncpg sqlalchemy[asyncio]
   ```

2. Замініть `get_connection()` у `db/database.py`:
   ```python
   # Замість aiosqlite:
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
   
   engine = create_async_engine(os.getenv("DATABASE_URL"))
   
   @asynccontextmanager
   async def get_connection():
       async with AsyncSession(engine) as session:
           yield session
   ```

3. Адаптуйте SQL-запити (PostgreSQL використовує `$1` замість `?`)

4. Оновіть `.env`:
   ```env
   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/newsagent
   ```

Всі методи (CRUD) залишаються без змін.

---

## ⚙️ Конфігурація стилів постів

| Стиль | Опис |
|-------|------|
| `default` | Стандартний інформативний пост |
| `breaking` | З префіксом ТЕРМІНОВО / BREAKING NEWS |
| `analytical` | З коротким аналітичним коментарем |

Кастомний стиль: відредагуйте `PROMPT_STYLES` у `core/processor.py`.

---

## 🔒 Безпека

- Ніколи не комітьте `.env` у git
- Додайте `session/` та `data/` до `.gitignore`
- Для продакшну використовуйте змінні середовища (Railway, Render, VPS)

---

## 📦 Деплой (VPS / Railway)

```bash
# Systemd service (VPS)
sudo nano /etc/systemd/system/newsagent.service

[Unit]
Description=AI News Agent
After=network.target

[Service]
WorkingDirectory=/opt/ai-news-agent
ExecStart=/opt/ai-news-agent/venv/bin/python main.py
Restart=always
EnvironmentFile=/opt/ai-news-agent/.env

[Install]
WantedBy=multi-user.target

sudo systemctl enable newsagent
sudo systemctl start newsagent
```

---

## 🐛 Діагностика

### 1) Базова перевірка конфігу

Переконайтесь, що в `.env` заповнені:

- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`
- `ADMIN_BOT_TOKEN`
- `GEMINI_API_KEY`
- (опційно) `SOURCES_REFRESH_SECONDS`, `GEMINI_RETRIES`, `PUBLISH_RETRIES`, `POST_DELAY`

### 2) Перевірка каналів і доступів

У адмін-боті виконайте:

```text
/diagnose
```

Команда перевіряє:
- валідність `bot_token` для кожного каналу,
- доступ бота до `target_channel_id` та його статус у каналі,
- резолв джерел `source_tg_link` через Telethon.

### 3) Як читати логи пайплайна

У логах є ключові етапи:

- `incoming_message` / `received` — подію отримано від донора.
- `dedupe_skip` — публікація пропущена, причина дедупа (`same_source_post_id` або `same_content_hash`).
- `rewritten` / `rewrite_failed` — результат Gemini.
- `publish_success` / `publish_failed` — результат публікації в Telegram.
- `sources_refreshed` — listener перечитав джерела з БД.

### 4) Нові джерела не працюють одразу

Listener автоматично оновлює список джерел кожні `SOURCES_REFRESH_SECONDS` (за замовчуванням 60 сек).  
Перезапуск процесу більше не потрібен.

### 5) Типові проблеми

| Проблема | Рішення |
|----------|---------|
| `publish_failed` або помилки доступу | Переконайтесь, що бот є **адміном** каналу з правом публікації |
| Часті `TelegramRetryAfter` | Збільшіть `POST_DELAY`, за потреби `PUBLISH_RETRIES` |
| Gemini повертає помилки/таймаути | Перевірте `GEMINI_API_KEY`; збільшіть `GEMINI_RETRIES` |
| `dedupe_skip` для різних каналів | Перевірте, що канали мають різний `channel_id` у БД; дедуп працює в межах одного каналу |
| `Cannot resolve @channel` | Джерело приватне/некоректне; перевірте `source_tg_link` (`@name` або `https://t.me/name`) |
