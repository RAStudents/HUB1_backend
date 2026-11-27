# Развёртывание HUB на Ubuntu VPS

Конфигурация запускает frontend, API, PostgreSQL и Caddy. Caddy получает и
обновляет HTTPS-сертификат автоматически. База и загруженные файлы сохраняются
в Docker volumes. Публично доступны только порты 80 и 443.

## Требования

- Ubuntu Server с Docker Engine и Docker Compose plugin.
- DNS-записи `A` (и, если используется, `AAAA`) для `hub.acmenra.studio`,
  указывающие на адрес VPS.
- Открытые входящие порты TCP 80 и 443; UDP 443 можно открыть для HTTP/3.
- На сервере рядом друг с другом должны находиться оба репозитория:

  ```text
  /opt/hub/
    HUB1_backend/
    HUB1_frontend-main/
  ```

Frontend-репозиторий нужен во время сборки web-образа; он не копируется в
backend-репозиторий.

## Первый запуск

Клонируйте репозитории в соседние каталоги, выбрав нужные для публикации ветки:

```bash
sudo mkdir -p /opt/hub
sudo chown "$USER":"$USER" /opt/hub
cd /opt/hub
git clone https://github.com/RAStudents/HUB1_backend.git
git clone https://github.com/RAStudents/HUB1_frontend.git HUB1_frontend-main
```

Создайте файл секретов и сгенерируйте два разных случайных значения:

```bash
cd /opt/hub/HUB1_backend
cp deploy/.env.example deploy/.env
openssl rand -hex 32
openssl rand -hex 32
```

В `deploy/.env` задайте `POSTGRES_PASSWORD` и `JWT_SECRET` разными
сгенерированными значениями. Не отправляйте этот файл в Git и не используйте
примерные значения из `.env.example`.

Запустите приложение:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml logs -f api
```

После запуска откройте `https://hub.acmenra.studio`. Выдача сертификата
потребует, чтобы DNS уже указывал на VPS и входящий порт 80 был доступен.

## Yandex OAuth и email

Чтобы включить вход через Яндекс, заполните `YANDEX_CLIENT_ID` и
`YANDEX_CLIENT_SECRET` в `deploy/.env`, а в настройках OAuth приложения укажите
redirect URL:

```text
https://hub.acmenra.studio/api/auth/yandex/callback
```

Для email-приглашений заполните SMTP-переменные. После правок `.env` примените
их пересозданием API-контейнера:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --force-recreate api
```

## Обновление

Перед обновлением сделайте резервную копию (см. ниже), затем обновите каждый
репозиторий на нужной ветке и пересоберите сервисы:

```bash
git -C /opt/hub/HUB1_backend pull
git -C /opt/hub/HUB1_frontend-main pull
cd /opt/hub/HUB1_backend
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

Не выполняйте `docker compose down -v`: флаг `-v` удалит volumes с базой и
данными приложения.

## Резервное копирование

Сохраните дамп PostgreSQL и оба volume с файлами в отдельное хранилище вне VPS.
Пример дампа:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "hub-db-$(date +%F).sql"
```

Дамп базы сам по себе не сохраняет изображения и экспорты: volumes
`hub_objects` и `hub_legacy_storage` тоже должны попадать в резервную копию.
Периодически проверяйте восстановление резервной копии на отдельном окружении.

## Важные ограничения

- Эта конфигурация использует файловое хранилище в Docker volumes: она подходит
  для одного VPS и одного API-инстанса. Для нескольких серверов потребуется
  общее S3-хранилище и отдельная настройка `S3_BACKEND=s3`.
- Локальные `hub_mvp.db`, `storage` и `local_s3_storage` с компьютера
  разработчика автоматически на сервер не переносятся. Перед первой
  эксплуатацией отдельно спланируйте перенос нужных данных.
- Перед обновлением всегда проверяйте резервные копии; изменения схемы базы
  выполняются приложением при старте.
