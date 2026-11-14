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