# TELONYX Cinema Publishing Pipeline

Документ описывает новый большой слой приложения TELONYX Cinema: генерация украинского контента по фильму после обработки Shorts, предпросмотр на сайте и публикация в TikTok, YouTube Shorts и Telegram.

## Цель

После того как пользователь обработал видео и скачал готовый Shorts/TikTok-ролик, он может нажать кнопку **«Генерація»**.

Сервис должен:

1. взять данные уже готовой job: `job_id`, итоговый MP4, название фильма, год выхода, язык, настройки субтитров;
2. через Gemini найти и сгенерировать украинский материал про фильм;
3. подобрать 3–5 изображений, связанных с фильмом: актёры, кадры, постеры, моменты;
4. привести изображения к фирменному TELONYX Cinema стилю;
5. показать на сайте предпросмотр Telegram-поста, названия, описания и хештегов для TikTok/YouTube;
6. после нажатия **«Публікувати»** отправить:
   - готовый MP4 в TikTok через Content Posting API;
   - готовый MP4 в YouTube Shorts через YouTube Data API;
   - сгенерированный пост и изображения в Telegram-канал через Telegram Bot API.

## Пользовательский сценарий

```text
1. Пользователь загружает готовый момент из фильма.
2. Сервис делает финальный vertical MP4 1080x1920: титр + субтитры.
3. Пользователь скачивает ролик и смотрит результат.
4. Если результат устраивает, нажимает «Генерація».
5. Сервис создаёт контент-пакет:
   - украинский Telegram-пост;
   - факты и история создания;
   - хештеги;
   - title/description/hashtags для TikTok;
   - title/description/hashtags для YouTube Shorts;
   - 3–5 фирменных изображений.
6. Пользователь видит предпросмотр на сайте.
7. Если всё устраивает, нажимает «Публікувати».
8. Сервис публикует контент по API.
```

## Новые сущности

### PublishPackage

Черновик контента, который появляется после кнопки «Генерація».

Поля:

```text
id                  UUID
job_id              UUID
movie_title         string
movie_year          int
status              draft | generating | ready | publishing | published | failed
telegram_text_uk    text
tiktok_title        string
tiktok_description  text
tiktok_hashtags     string[]
youtube_title       string
youtube_description text
youtube_hashtags    string[]
source_links        json[]
images              PublishImage[]
created_at          datetime
updated_at          datetime
error_message       text | null
```

### PublishImage

```text
id                  UUID
publish_package_id  UUID
source_url          text
local_path          text
styled_path         text
alt_text_uk         text
kind                actor | scene | poster | mood | other
sort_order          int
```

### PublishTargetResult

```text
id                  UUID
publish_package_id  UUID
target              telegram | tiktok | youtube
status              pending | success | failed
external_url        text | null
external_id         text | null
error_message       text | null
created_at          datetime
updated_at          datetime
```

## API

### Создать контент-пакет

```http
POST /api/jobs/{job_id}/generate-package
```

Ответ:

```json
{
  "package_id": "uuid",
  "status": "generating"
}
```

### Получить контент-пакет

```http
GET /api/publish-packages/{package_id}
```

Ответ содержит Telegram preview, TikTok/YouTube metadata, ссылки на изображения и статус генерации.

### Перегенерировать текст

```http
POST /api/publish-packages/{package_id}/regenerate-text
```

Можно использовать, если текст слабый, слишком длинный или не попал в стиль канала.

### Перегенерировать изображения

```http
POST /api/publish-packages/{package_id}/regenerate-images
```

### Опубликовать

```http
POST /api/publish-packages/{package_id}/publish
```

Тело запроса:

```json
{
  "targets": ["telegram", "tiktok", "youtube"]
}
```

## Gemini

Используем Gemini API с Google Search grounding.

Задачи Gemini:

1. найти проверяемые материалы по фильму;
2. собрать краткую историю создания фильма;
3. выбрать 5–7 интересных фактов;
4. написать пост на украинском языке;
5. отдельно сгенерировать title/description/hashtags для TikTok и YouTube Shorts;
6. вернуть структурированный JSON.

### Промпт для Gemini

```text
Ти — редактор українського кіно-каналу TELONYX Cinema.

Фільм: {movie_title}
Рік: {movie_year}

Завдання:
1. Знайди в інтернеті історію створення фільму та цікаві факти.
2. Пиши тільки українською мовою.
3. Не вигадуй факти. Якщо факт не підтверджено джерелами — не використовуй.
4. Тон: кінематографічний, темний, атмосферний, але зрозумілий.
5. Формат Telegram-поста:
   - сильний хук на 1–2 рядки;
   - короткий блок «Історія створення»;
   - 5 цікавих фактів;
   - фінальна емоційна фраза;
   - хештеги українською.
6. Обовʼязкові хештеги Telegram:
   #Історія #Факти #ЦікавоЗнати
7. Для TikTok і YouTube Shorts створи окремо:
   - title;
   - description;
   - hashtags.

Поверни JSON без markdown.
```

## Telegram

Публикация в Telegram-канал делается через Bot API.

Рекомендуемый формат:

1. `sendMediaGroup` для 3–5 изображений;
2. первым элементом album передавать caption с Telegram-постом;
3. если текст слишком длинный — сначала альбом, потом отдельный `sendMessage` с полным постом.

Важно:

- бот должен быть администратором канала;
- токен хранить только в переменных окружения;
- тестовый токен, попавший в чат, нужно пересоздать через BotFather.

## TikTok

Публикация делается через TikTok Content Posting API.

Основной сценарий:

1. OAuth авторизация аккаунта автора;
2. получение access token и refresh token;
3. запрос creator info;
4. init direct post;
5. upload video;
6. проверка статуса публикации.

Нужно учитывать, что приложение TikTok Developer должно быть настроено и может требовать review/approval для production-доступа.

## YouTube Shorts

YouTube Shorts публикуется через YouTube Data API как обычный video upload.

Требования:

1. OAuth 2.0 для аккаунта канала;
2. scope для загрузки видео;
3. загрузка MP4 через `videos.insert`;
4. metadata:
   - title;
   - description;
   - tags;
   - categoryId;
   - privacyStatus;
5. для Shorts использовать вертикальный MP4 и добавить `#Shorts` в title или description.

## Изображения в фирменном стиле

Минимальная версия:

1. скачать найденные изображения;
2. привести к единому размеру, например 1080x1350 или 1080x1080;
3. добавить тёмный cinematic gradient;
4. добавить лёгкий grain/noise;
5. добавить neon/cyberpunk accent line;
6. добавить watermark `TELONYX CINEMA`;
7. сохранить styled image в storage.

Важно: нужно проверить лицензионные риски. Для MVP можно использовать изображения только как Telegram-контент, а позже добавить ручную модерацию источников.

## ENV

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_GROUNDING_ENABLED=true

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=@TXC_UA

TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=

YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_DEFAULT_PRIVACY=public

BRAND_WATERMARK=TELONYX CINEMA
BRAND_STYLE=dark_neon_cinematic
```

## Очереди и статусы

Даже если текущий проект работает как один сервис, генерацию и публикацию нужно делать как фоновые задачи, чтобы сайт не зависал.

### GeneratePackageTask

```text
queued -> searching -> writing -> styling_images -> ready | failed
```

### PublishPackageTask

```text
queued -> publishing_telegram -> publishing_tiktok -> publishing_youtube -> published | partially_published | failed
```

## MVP-порядок разработки

1. Добавить модель `PublishPackage` и хранение JSON-черновика.
2. Добавить кнопку «Генерація» на странице job result.
3. Добавить endpoint `/api/jobs/{job_id}/generate-package`.
4. Подключить Gemini и получить структурированный украинский JSON.
5. Сделать UI предпросмотра Telegram/TikTok/YouTube.
6. Добавить генерацию/обработку 3–5 изображений в фирменном стиле.
7. Добавить Telegram publish.
8. Добавить YouTube OAuth и upload.
9. Добавить TikTok OAuth и Direct Post.
10. Добавить логи, статусы, retry и отображение ошибок.

## Что нельзя делать

- Нельзя хранить токены в репозитории.
- Нельзя публиковать автоматически без финального подтверждения пользователя.
- Нельзя использовать непроверенные факты без источников.
- Нельзя смешивать украинский Telegram-пост с русским или английским текстом.
- Нельзя публиковать в TikTok/YouTube без сохранённых OAuth токенов владельца аккаунта.
