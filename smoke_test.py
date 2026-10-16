import sys
from pathlib import Path

# Добавляем корни для правильного поиска модулей
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "apps" / "api"))

# Импортируем из base.py вместо db.py
from core.infrastructure.sql.base import SessionLocal  # или из вашего актуального пути
from core.infrastructure.sql.repos.users import UserRepository
from core.application.auth_service import AuthService

db = SessionLocal()
svc = AuthService(UserRepository(db))

# Проверяем работу входа через Яндекс и защиту от дубликатов
r1 = svc.login_with_yandex('ya_999', 'test_user@example.com', 'Яндекс Имя')
r2 = svc.login_with_yandex('ya_999', 'test_user@example.com', 'Яндекс Имя')

print('Первый вход ID:', r1['user_id'])
print('Повторный вход ID:', r2['user_id'])

assert r1['user_id'] == r2['user_id'], 'Ошибка: создался дубликат!'
print('УСПЕХ: Дубликатов нет, аккаунт привязан!')