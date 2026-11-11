# core/infrastructure/email/smtp.py

import os
import ssl
import smtplib
import logging
from dataclasses import dataclass
from email.message import EmailMessage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    from_email: str
    username: str | None = None
    password: str | None = None
    security: str = "starttls"
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "SMTPSettings":
        security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        default_port = 465 if security == "ssl" else 587
        username = os.getenv("SMTP_USERNAME") or None
        return cls(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=int(os.getenv("SMTP_PORT", str(default_port))),
            from_email=os.getenv("SMTP_FROM_EMAIL", username or "").strip(),
            username=username,
            password=os.getenv("SMTP_PASSWORD") or None,
            security=security,
            timeout=float(os.getenv("SMTP_TIMEOUT_SECONDS", "10")),
        )


class SMTPEmailService:
    def __init__(self,
                 settings: SMTPSettings):
        if settings.security not in {"ssl", "starttls", "none"}:
            raise ValueError("SMTP_SECURITY должен быть ssl, starttls или none")
        if not 1 <= settings.port <= 65535:
            raise ValueError("SMTP_PORT должен быть в диапазоне от 1 до 65535")
        if settings.timeout <= 0:
            raise ValueError("SMTP_TIMEOUT_SECONDS должен быть больше нуля")
        if bool(settings.username) != bool(settings.password):
            raise ValueError("SMTP_USERNAME и SMTP_PASSWORD должны быть заданы вместе")
        self.settings = settings

    @classmethod
    def from_env(cls) -> "SMTPEmailService":
        return cls(SMTPSettings.from_env())

    def send_email(self,
                   to_email: str,
                   subject: str,
                   body: str) -> None:
        if not self.settings.host or not self.settings.from_email:
            raise RuntimeError(
                "SMTP не настроен: задайте SMTP_HOST и SMTP_FROM_EMAIL"
            )

        message = EmailMessage()
        message["From"] = self.settings.from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        smtp_class = (
            smtplib.SMTP_SSL if self.settings.security == "ssl" else smtplib.SMTP
        )
        connection_options = {
            "timeout": self.settings.timeout,
        }
        if self.settings.security == "ssl":
            connection_options["context"] = ssl.create_default_context()

        with smtp_class(
            self.settings.host, self.settings.port, **connection_options
        ) as server:
            if self.settings.security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if self.settings.username and self.settings.password:
                server.login(self.settings.username, self.settings.password)
            server.send_message(message)