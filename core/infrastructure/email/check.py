"""SMTP connectivity check. No messages or invitations are sent."""
import os
from pathlib import Path
from core.infrastructure.email.smtp import SMTPEmailService


def main() -> int:
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().startswith("SMTP_"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    try:
        service = SMTPEmailService.from_env()
    except (ValueError, TypeError):
        print("Некорректная конфигурация SMTP. Проверьте SMTP_PORT, SMTP_SECURITY, SMTP_TIMEOUT_SECONDS и пару логин/пароль. Логин с паролем требует TLS.")
        return 2
    missing = [name for name, value in (("SMTP_HOST", service.settings.host), ("SMTP_FROM_EMAIL", service.settings.from_email)) if not value]
    if missing:
        print("SMTP не настроен. Заполните: " + ", ".join(missing))
        return 2
    try:
        service.check_connection()
    except Exception as exc:
        # SMTP responses may contain account details; do not print their contents.
        print(f"Проверка SMTP не пройдена ({type(exc).__name__}). Проверьте доступность сервера, режим TLS, учётные данные и ограничения провайдера.")
        return 1
    print("SMTP: соединение и настроенная авторизация работают. Письмо не отправлялось; доставка во входящие не проверялась.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
