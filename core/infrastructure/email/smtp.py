# core/infrastructure/email/smtp.py

import os
import ssl
import smtplib
import logging
import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.message import EmailMessage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    from_email: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    security: str = "starttls"
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "SMTPSettings":
        security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        default_port = 465 if security == "ssl" else 587
        username = os.getenv("SMTP_USERNAME", "").strip() or None
        return cls(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=int(os.getenv("SMTP_PORT", "").strip() or str(default_port)),
            from_email=os.getenv("SMTP_FROM_EMAIL", "").strip() or username or "",
            username=username,
            password=os.getenv("SMTP_PASSWORD") or None,
            security=security,
            timeout=float(os.getenv("SMTP_TIMEOUT_SECONDS", "").strip() or "10"),
        )


class SMTPEmailService:
    def __init__(self,
                 settings: SMTPSettings):
        if settings.security not in {"ssl", "starttls", "none"}:
            raise ValueError("SMTP_SECURITY должен быть ssl, starttls или none")
        if not 1 <= settings.port <= 65535:
            raise ValueError("SMTP_PORT должен быть в диапазоне от 1 до 65535")
        if not math.isfinite(settings.timeout) or settings.timeout <= 0:
            raise ValueError("SMTP_TIMEOUT_SECONDS должен быть конечным числом больше нуля")
        if bool(settings.username) != bool(settings.password):
            raise ValueError("SMTP_USERNAME и SMTP_PASSWORD должны быть заданы вместе")
        if settings.security == "none" and settings.username:
            raise ValueError("SMTP с логином и паролем требует ssl или starttls")
        self.settings = settings

    @classmethod
    def from_env(cls) -> "SMTPEmailService":
        return cls(SMTPSettings.from_env())

    @contextmanager
    def _connection(self):
        if not self.settings.host or not self.settings.from_email:
            raise RuntimeError("SMTP не настроен: задайте SMTP_HOST и SMTP_FROM_EMAIL")
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
            server.ehlo_or_helo_if_needed()
            if self.settings.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if self.settings.username and self.settings.password:
                server.login(self.settings.username, self.settings.password)
            yield server

    def check_connection(self) -> None:
        """Check connection, TLS and authentication without sending an email."""
        with self._connection() as server:
            code, response = server.noop()
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)

    def send_email(self,
                   to_email: str,
                   subject: str,
                   body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        with self._connection() as server:
            server.send_message(message)