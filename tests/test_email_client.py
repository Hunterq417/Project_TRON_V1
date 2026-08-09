# tests/test_email_client.py
from unittest.mock import MagicMock

import email_client


def test_draft_email_formats_readable_text():
    draft = email_client.draft_email("alex@example.com", "Running late", "Be there in 20.")

    assert "alex@example.com" in draft
    assert "Running late" in draft
    assert "Be there in 20." in draft


def test_send_email_success(monkeypatch):
    fake_server = MagicMock()
    fake_smtp_cm = MagicMock()
    fake_smtp_cm.__enter__ = MagicMock(return_value=fake_server)
    fake_smtp_cm.__exit__ = MagicMock(return_value=False)
    fake_smtp_ssl = MagicMock(return_value=fake_smtp_cm)
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", fake_smtp_ssl)

    result = email_client.send_email(
        to="alex@example.com", subject="Running late", body="Be there in 20.",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="app-pw",
    )

    fake_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
    fake_server.login.assert_called_once_with("me@example.com", "app-pw")
    fake_server.send_message.assert_called_once()
    assert "sent" in result.lower()
    assert "alex@example.com" in result


def test_send_email_failure_returns_message_instead_of_raising(monkeypatch):
    fake_smtp_ssl = MagicMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr(email_client.smtplib, "SMTP_SSL", fake_smtp_ssl)

    result = email_client.send_email(
        to="alex@example.com", subject="s", body="b",
        smtp_host="smtp.example.com", smtp_port=465,
        smtp_user="me@example.com", smtp_app_password="app-pw",
    )

    assert "failed" in result.lower()
    assert "connection refused" in result
