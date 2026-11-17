```
hub/
  docker-compose.yml                 # api, web, postgres, minio
  .env.example                       # DATABASE_URL, S3_*, YANDEX_CLIENT_ID/SECRET
  TASK.md
  docs/
    DATA_CONTRACT.md                 # cv 0.3.2 / ds 0.2.1.6, yaml, txt, две раскладки, пустой txt, градусы в API / радианы в txt
    ARCHITECTURE.md                  # postgres = состояние, s3 = байты
    KEYBOARD.md                      # сохранить, undo, маски, следующий кадр

  apps/api/
    Dockerfile                       # python + libheif
    pyproject.toml                   # fastapi, psycopg, boto3, pillow-heif, acmenra-cv, acmenra-ds
    app/
      main.py                        # приложение, cors, /health, подключение роутера
      deps.py                        # пользователь из токена, членство, роль на этот датасет
      errors.py                      # русские ошибки, 404 на чужой id
      api/
        router.py                    # сборка роутеров
        auth.py                      # регистрация, логин, callback Яндекса, я, выход
        datasets.py                  # создать, мои, доступные мне, удалить
        classes.py                   # имена классов, правка индекса только с подтверждением
        members.py                   # список участников, добавление зарегистрированных по email, смена роли, удаление
        notifications.py             # список уведомлений, отметка прочитанного
        samples.py                   # выдача upload-url, завершение загрузки, галерея, удаление
        annotations.py               # отдать разметку кадра и принять сохранение
        locks.py                     # взять, продлить, отпустить, снять владельцем
        review.py                    # на проверку, принято, на доработку
        export.py                    # запустить сборку zip, статус, ссылка на скачивание
      schemas/
        auth.py
        dataset.py
        sample.py
        annotation.py                # нормализованный box / obb / polygon, как отдал cv
        member.py
        notification.py
        export.py

  apps/web/
    Dockerfile
    package.json
    index.html
    vite.config.ts
    src/
      main.tsx
      router.tsx
      api/client.ts                  # запросы к API, картинка и zip — по ссылке из S3
      api/types.ts                   # DTO ответов, не строка YOLO
      auth/LoginPage.tsx
      auth/RegisterPage.tsx
      datasets/ListPage.tsx          # мои и доступные мне
      datasets/CreatePage.tsx        # имя, task, yaml или пустой список классов
      datasets/MembersPage.tsx
      gallery/GalleryPage.tsx        # All / Train / Val / Test, фильтр статуса, страницы
      gallery/SampleCard.tsx         # покой — кадр, hover — тумба с масками
      inspect/InspectPage.tsx        # зум, пан, история, статус; править нельзя
      inspect/Viewport.tsx
      editor/EditorPage.tsx          # сохранение, класс объекта, удаление
      editor/Viewport.tsx
      editor/useUndo.ts              # только память этого кадра
      editor/hotkeys.ts
      editor/tools/box.ts
      editor/tools/obb.ts
      editor/tools/polygon.ts

  core/domain/
    enums.py                         # Task, Split, Layout, Role, SampleStatus
    user.py                          # аккаунт, без роли датасета
    dataset.py                       # имя, task, приватность
    sample.py                        # stem, split, статус, lock_user, lock_until, parse_error
    annotation.py                    # class_id, автор, последний редактор; координат нет
    membership.py                    # пользователь × датасет × owner|labeler|observer
    event.py                         # кто, действие, когда
    status.py                        # допустимые переходы статусов

  core/application/
    auth_service.py                  # почта и Яндекс: один человек — один user
    dataset_service.py               # датасет и классы
    membership_service.py            # добавление участников и управление ролями
    upload_service.py                # догрузить байты, сконвертировать, завести сэмпл
    import_service.py                # zip: угадать раскладку, разложить объекты в S3 и строки в БД
    annotation_service.py            # save/get: роль, lock, cv, затем S3 и Postgres
    lock_service.py                  # TTL 15–30 мин, продление, force-unlock
    review_service.py                # на проверку / принято / на доработку + событие
    export_service.py                # только accepted, одна раскладка, zip в S3

  core/infrastructure/
    sql/
      base.py                        # текущий DataBase
      table.py                       # текущий Table
      enums.py                       # DBType, Status
      schema.py                      # users, datasets, classes, memberships, samples, annotations, events, notifications, exports
      repos/users.py
      repos/datasets.py
      repos/classes.py
      repos/memberships.py             # owner | labeler | observer; владелец неизменяем
      repos/notifications.py
      repos/samples.py
      repos/annotations.py
      repos/events.py
      repos/exports.py
    s3/
      client.py                      # put, get, delete, presigned url
      keys.py                        # префиксы бакета, не папки сервера
    media/
      convert.py                     # jpeg/png оставить, heic/webp/bmp/tiff → jpg, stem тот же
      scratch.py                     # временный файл для парсера и сборки zip, после вызова удалить
    cv/
      mapper.py                      # DTO ↔ Box/Obb/Polygon/Instance; плейсхолдер-бокс наружу не отдавать
      labels.py                      # только LabelParser и LabelWriter
      thumbs.py                      # Drawer рисует тумбу галереи
    auth/
      passwords.py                   # хэш, не открытый пароль
      tokens.py
      yandex.py                      # код Яндекса → тот же user по yandex_id

  # ключи в бакете (это prefixes S3):
  # datasets/{dataset_id}/images/{sample_id}.jpg
  # datasets/{dataset_id}/labels/{sample_id}.txt
  # datasets/{dataset_id}/thumbs/{sample_id}.jpg
  # exports/{export_id}.zip
```

## Local host

Set `LOCAL_HOST` in the backend `.env` to choose the host used by local URL defaults.
It controls the backend base URL, the default Yandex callback URL, and local CORS origins.
An explicit `YANDEX_REDIRECT_URI` still overrides the callback default.

```env
LOCAL_HOST=127.0.0.1
```

## S3 / MinIO object storage

Storage stays local by default. To switch the backend to AWS S3 or an S3-compatible service, install `boto3` in the backend's active Python environment and copy the S3 entries from the backend-root `.env.example` into the backend-root `.env` (the same folder as this README). Do not replace the rest of `.env`.

```powershell
.\.venv\Scripts\python.exe -m pip install boto3
```

Create the bucket in AWS or MinIO before starting the API; startup checks that it exists and fails if it cannot access it. The backend does not create buckets automatically. Set these values in `.env`:

```env
S3_BACKEND=s3
S3_BUCKET=hub
S3_REGION=us-east-1
S3_ENDPOINT_URL=
S3_PUBLIC_ENDPOINT_URL=
S3_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY
S3_ADDRESSING_STYLE=auto
```

For **AWS S3**, replace `hub` with the exact bucket name and `us-east-1` with the bucket's AWS region. Keep both endpoint values empty and `S3_ADDRESSING_STYLE=auto`. Create an IAM user/access key restricted to this bucket, or use the server's IAM role and leave both access key values empty. The identity needs `s3:ListBucket` on `arn:aws:s3:::YOUR_BUCKET` and `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on `arn:aws:s3:::YOUR_BUCKET/*`.

For **Timeweb Cloud S3**, the endpoint is `https://s3.twcstorage.ru` and the region is `ru-1`. Set `S3_BUCKET` to your bucket name, put the Timeweb `Access Key` and `Secret Key` in the credential variables above, and use:

```env
S3_REGION=ru-1
S3_ENDPOINT_URL=https://s3.twcstorage.ru
S3_PUBLIC_ENDPOINT_URL=https://s3.twcstorage.ru
S3_ADDRESSING_STYLE=path
```

Timeweb shows the access keys in the bucket dashboard. Do not make the bucket public; signed URLs are used by the app.

For **MinIO**, create a bucket (for example `hub`) and use the API endpoint reachable from the backend process:

```env
S3_BACKEND=s3
S3_BUCKET=hub
S3_REGION=us-east-1
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY_ID=YOUR_MINIO_ACCESS_KEY
S3_SECRET_ACCESS_KEY=YOUR_MINIO_SECRET_KEY
S3_ADDRESSING_STYLE=path
```

If the API runs in Docker Compose, set `S3_ENDPOINT_URL` to the MinIO service name and internal port (for example `http://minio:9000`). Set `S3_PUBLIC_ENDPOINT_URL` to the matching MinIO URL reachable by the user's browser (for example `http://localhost:9000` for local development, or the public MinIO hostname in production). The backend uses the first endpoint for its own S3 requests and the public endpoint only when generating signed browser links. If MinIO uses TLS, use `https://` endpoints. Give the MinIO account permissions to list the bucket and read, write, and delete objects in it.

After saving `.env`, restart the backend. The startup log should say `Storage (S3) готов.`. If it reports an error, check that the bucket already exists, the region and endpoint match the bucket service, and the credentials have the permissions above. Existing data under `local_s3_storage` is not copied automatically; upload/import it again or migrate those files into matching object keys in the bucket.

Images and exports use short-lived signed URLs, and uploads use a signed PUT URL. Keep the bucket private; public bucket access is not required. If a browser uploads directly to the bucket, configure bucket CORS to allow the exact frontend origin, `PUT`, `GET`, `HEAD`, and the `Content-Type` request header. Do not use `*` origins for a production site.

To return to local filesystem storage, set `S3_BACKEND=local` (or remove it) and restart the API.

## SMTP

Для отправки писем настройте переменные окружения backend:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=user@example.com
SMTP_PASSWORD=change-me
SMTP_FROM_EMAIL=user@example.com
SMTP_SECURITY=starttls
SMTP_TIMEOUT_SECONDS=10
```

`SMTP_SECURITY` принимает `starttls` (по умолчанию), `ssl` или `none`; для `ssl` порт по умолчанию `465`, для остальных режимов — `587`. Логин и пароль можно не задавать для SMTP-сервера без авторизации. Приглашение создаёт постоянное уведомление в приложении и отправляет email. Если SMTP не настроен или недоступен, приглашение и уведомление в приложении сохраняются; ответ API сообщает `"email_notification_sent": false`, а backend записывает ошибку отправки в лог.

Авторизованный пользователь получает свои уведомления через `GET /api/notifications` (параметры `page` и `page_size`; ответ содержит `unread_count`), отмечает одно уведомление прочитанным через `POST /api/notifications/{notification_id}/read` или отмечает все через `POST /api/notifications/read-all`. Чтение и отметка всегда ограничены текущим пользователем.

## Согласие на обработку электронных пользовательских данных

Backend хранит историю действий посетителя в `visitor_data_consent_events`, используя случайный
HttpOnly-cookie `consent_visitor_id`; согласие не привязано к аккаунту. Cookie выдаётся
публичным `GET /api/consent` и действует один год.
`GET /api/consent` возвращает текст согласия (`consent_text`), последнее действие и текущую версию;
также возвращает `policy_link_text` и `policy_url` для ссылки на страницу Политики.
`POST /api/consent` принимает `{"action":"accepted"}`, `{"action":"rejected"}` или
`{"action":"withdrawn"}`. Отозвать можно только принятое согласие. Повтор того же
действия идемпотентен. При изменении текста согласия нужно увеличить
`ELECTRONIC_USER_DATA_CONSENT_VERSION` в `apps/api/app/api/consent.py`.
Публичная frontend-страница `/consent` показывает текст и позволяет принять,
отклонить или отозвать согласие.
На всех frontend-маршрутах до принятия согласия показывается cookie-уведомление
со ссылкой на `/consent`; отказ или отзыв не скрывает уведомление.

Публичный `GET /api/privacy-policy` отдаёт `title`, `subtitle` и текст Политики;
frontend отображает его на странице `/privacy-policy`.
