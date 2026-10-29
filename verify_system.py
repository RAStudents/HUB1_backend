# verify_system.py
import os
import sys
import time
import threading
from datetime import datetime, timedelta, timezone
from io import BytesIO
from PIL import Image

import httpx
import uvicorn

from apps.api.app.main import app
from apps.api.app.deps import get_db, get_s3_client
from core.infrastructure.sql.repos.samples import SampleRepository

HOST = "127.0.0.1"
PORT = 8009
BASE_URL = f"http://{HOST}:{PORT}"


class ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def wait_for_server(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def run_checks():
    print("=" * 65)
    print("  ПРОВЕРКА РАБОТОСПОСОБНОСТИ ПРОЕКТА (FASTAPI + SQLITE + S3)")
    print("=" * 65)

    print(f"\n[Запуск] Стартуем тестовый сервер uvicorn на {BASE_URL}...")
    server = ServerThread(app, HOST, PORT)
    server.start()

    if not wait_for_server(15):
        print("❌ Сервер не ответил за 15 секунд!")
        server.stop()
        sys.exit(1)

    print("✅ Сервер успешно запущен и отвечает на запросы.")

    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    try:
        # 1. Health check
        print("\n[1] Проверка GET /health ...")
        res = client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        assert res.json().get("status") == "ok"
        print("  -> OK:", res.json())

        # 2. Регистрация нового пользователя
        test_email = f"user_{int(datetime.now().timestamp())}@test.com"
        test_password = "Password123!"
        test_name = "Алексей Инженеров"

        print(f"\n[2] Проверка POST /api/auth/register ({test_email}) ...")
        res = client.post("/api/auth/register", json={
            "email": test_email,
            "password": test_password,
            "name": test_name
        })
        assert res.status_code == 201, f"Register failed: {res.text}"
        reg_data = res.json()
        assert "access_token" in reg_data
        token = reg_data["access_token"]
        user_id = reg_data["user_id"]
        print(f"  -> OK: Пользователь зарегистрирован, ID={user_id}")

        # 3. Вход в аккаунт
        print("\n[3] Проверка POST /api/auth/login ...")
        res = client.post("/api/auth/login", json={
            "email": test_email,
            "password": test_password
        })
        assert res.status_code == 200, f"Login failed: {res.text}"
        login_data = res.json()
        assert login_data["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}
        print("  -> OK: Вход выполнен, JWT токен подтверждён")

        # 4. Профиль пользователя
        print("\n[4] Проверка GET /api/auth/me ...")
        res = client.get("/api/auth/me", headers=auth_headers)
        assert res.status_code == 200, f"Get me failed: {res.text}"
        assert res.json()["email"] == test_email
        print(f"  -> OK: Профиль получен: {res.json()}")

        # 5. Обновление профиля
        print("\n[5] Проверка PATCH /api/auth/me ...")
        res = client.patch("/api/auth/me", headers=auth_headers, json={"name": "Алексей Обновлённый"})
        assert res.status_code == 200, f"Patch me failed: {res.text}"
        assert res.json()["name"] == "Алексей Обновлённый"
        print("  -> OK: Имя успешно изменено:", res.json()["name"])

        # 6. Создание датасета
        print("\n[6] Проверка POST /api/datasets/ ...")
        res = client.post("/api/datasets/", headers=auth_headers, json={
            "name": "Urban Traffic Detect",
            "task": "detect",
            "description": "Датасет детекции дорожных объектов",
            "classes": ["car", "bus", "truck"]
        })
        assert res.status_code == 201, f"Create dataset failed: {res.text}"
        dataset_id = res.json()["dataset_id"]
        print(f"  -> OK: Датасет успешно создан, dataset_id={dataset_id}")

        # 7. Галерея сэмплов (пустая)
        print(f"\n[7] Проверка GET /api/datasets/{dataset_id}/samples ...")
        res = client.get(f"/api/datasets/{dataset_id}/samples", headers=auth_headers)
        assert res.status_code == 200, f"Gallery failed: {res.text}"
        gallery = res.json()
        assert gallery["total"] == 0
        assert len(gallery["items"]) == 0
        print("  -> OK: Галерея пуста (total=0, items=[])")

        # 8. Запрос Upload URL
        print(f"\n[8] Проверка POST /api/datasets/{dataset_id}/samples/upload-url ...")
        res = client.post(
            f"/api/datasets/{dataset_id}/samples/upload-url",
            headers=auth_headers,
            json={"filename": "sample_001.jpg", "split": "train", "content_type": "image/jpeg"}
        )
        assert res.status_code == 200, f"Upload URL failed: {res.text}"
        upload_info = res.json()
        upload_key = upload_info["upload_key"]
        print(f"  -> OK: Presigned upload key: {upload_key}")

        # 9. Сохранение файла в S3 и завершение загрузки
        print(f"\n[9] Загрузка изображения и POST /complete-upload ...")
        s3 = get_s3_client()
        img = Image.new("RGB", (200, 200), color=(50, 120, 200))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        raw_img_bytes = buf.getvalue()
        s3.put_bytes(upload_key, raw_img_bytes, content_type="image/jpeg")

        res = client.post(
            f"/api/datasets/{dataset_id}/samples/complete-upload",
            headers=auth_headers,
            json={"upload_key": upload_key, "split": "train"}
        )
        assert res.status_code == 200, f"Complete upload failed: {res.text}"
        sample_card = res.json()
        sample_id = sample_card["id"]
        print(f"  -> OK: Кадр обработан, ID={sample_id}")
        print(f"     Image URL: {sample_card['image_url']}")
        print(f"     Thumb URL: {sample_card['thumb_url']}")

        # 10. Проверка галереи с добавленным сэмплом
        print(f"\n[10] Проверка GET /api/datasets/{dataset_id}/samples (с кадром) ...")
        res = client.get(f"/api/datasets/{dataset_id}/samples", headers=auth_headers)
        assert res.status_code == 200
        gallery = res.json()
        assert gallery["total"] == 1
        assert len(gallery["items"]) == 1
        assert gallery["items"][0]["id"] == sample_id
        print("  -> OK: Кадр отображается в галерее")

        # 11. Получение разметки кадра
        print(f"\n[11] Проверка GET /api/datasets/{dataset_id}/samples/{sample_id}/annotations ...")
        res = client.get(
            f"/api/datasets/{dataset_id}/samples/{sample_id}/annotations",
            headers=auth_headers
        )
        assert res.status_code == 200, f"Get annotations failed: {res.text}"
        ann_dto = res.json()
        assert ann_dto["sample_id"] == sample_id
        assert ann_dto["items"] == []
        print("  -> OK: Разметка кадра получена (пока пустая)")

        # 12. Блокировка кадра и сохранение аннотаций
        print(f"\n[12] Сохранение аннотации (PUT /annotations) ...")
        db_gen = get_db()
        db = next(db_gen)
        try:
            sample_repo = SampleRepository(db)
            sample_repo.lock_sample(
                sample_id=sample_id,
                user_id=user_id,
                lock_until=datetime.now(timezone.utc) + timedelta(minutes=30)
            )
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

        res = client.put(
            f"/api/datasets/{dataset_id}/samples/{sample_id}/annotations",
            headers=auth_headers,
            json={
                "sample_id": sample_id,
                "items": [
                    {
                        "class_id": 0,
                        "box": {"x": 0.5, "y": 0.5, "width": 0.3, "height": 0.3}
                    }
                ]
            }
        )
        assert res.status_code == 200, f"Save annotations failed: {res.text}"
        saved_ann = res.json()
        assert len(saved_ann["items"]) == 1
        print("  -> OK: Аннотация (Bounding Box) успешно сохранена, превью сгенерировано")

        # 13. Экспорт датасета
        print(f"\n[13] Проверка экспорта (POST /exports) ...")
        db_gen = get_db()
        db = next(db_gen)
        try:
            sample_repo = SampleRepository(db)
            sample_repo.set_status(sample_id=sample_id, status="accepted")
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

        res = client.post(
            f"/api/datasets/{dataset_id}/exports?layout=direct",
            headers=auth_headers
        )
        assert res.status_code == 201, f"Start export failed: {res.text}"
        export_data = res.json()
        assert export_data["status"] == "completed"
        assert export_data["exported_samples"] == 1
        assert export_data["download_url"]
        export_id = export_data["export_id"]
        print(f"  -> OK: ZIP-архив датасета сформирован (export_id={export_id}):")
        print(f"     Ссылка на скачивание: {export_data['download_url']}")

        # Проверка GET /exports/{export_id}
        res = client.get(f"/api/datasets/{dataset_id}/exports/{export_id}", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "completed"
        print("  -> OK: Статус экспорта успешно получен")

        # 14. Удаление сэмпла
        print(f"\n[14] Проверка DELETE /api/datasets/{dataset_id}/samples/{sample_id} ...")
        res = client.delete(
            f"/api/datasets/{dataset_id}/samples/{sample_id}",
            headers=auth_headers
        )
        assert res.status_code == 204, f"Delete failed: {res.text}"

        res = client.get(f"/api/datasets/{dataset_id}/samples", headers=auth_headers)
        assert res.json()["total"] == 0
        print("  -> OK: Сэмпл удалён, галерея очищена")

        print("\n" + "=" * 65)
        print("  ИТОГ: ВСЕ 14 ТЕСТОВЫХ СЦЕНАРИЕВ ВЫПОЛНЕНЫ УСПЕШНО!")
        print("  ПРОЕКТ ПОЛНОСТЬЮ РАБОТОСПОСОБЕН.")
        print("=" * 65)

    finally:
        client.close()
        server.stop()


if __name__ == "__main__":
    try:
        run_checks()
    except Exception as exc:
        print(f"\n❌ Ошибка во время тестирования: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
