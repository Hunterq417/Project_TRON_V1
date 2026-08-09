# email_client.py
import smtplib
from email.mime.text import MIMEText


def draft_email(to: str, subject: str, body: str) -> str:
    return f"To: {to}\nSubject: {subject}\n\n{body}"


def send_email(
    to: str, subject: str, body: str,
    smtp_host: str, smtp_port: int, smtp_user: str, smtp_app_password: str,
) -> str:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_app_password)
            server.send_message(msg)
    except Exception as exc:
        return f"failed to send: {exc}"
    return f"sent to {to}"
