from datetime import datetime, timedelta

from database import SessionLocal
from models import User as UserModel
import utils.email_service as email_service_module
from utils.email_service import generate_otp

# Captured at import time, before the autouse disable_smtp fixture replaces
# the module attribute for the duration of each test.
ORIGINAL_SEND_VERIFICATION = email_service_module.send_verification_email


def _register(client, email="otp@example.com", password="Password123!", name="Otp"):
    return client.post(
        "/auth/register", json={"email": email, "password": password, "name": name}
    )


def _get_user(email):
    db = SessionLocal()
    try:
        return db.query(UserModel).filter(UserModel.email == email).first()
    finally:
        db.close()


def _set_expiry(email, expires_at):
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == email).first()
        user.code_expires_at = expires_at
        db.commit()
    finally:
        db.close()


class TestGenerateOtp:

    def test_six_digit_string_with_leading_zeros(self):
        code = generate_otp()

        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_codes_vary(self):
        codes = {generate_otp() for _ in range(50)}
        assert len(codes) > 10  # not stuck on one value


class TestEmailService:

    def test_console_mode_without_credentials(self, monkeypatch):
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        sent = []

        # Console mode must not touch smtplib at all.
        class _Boom:
            def __init__(self, *args, **kwargs):
                sent.append("connected")

        monkeypatch.setattr(email_service_module.smtplib, "SMTP", _Boom)

        result = email_service_module.send_verification_email("a@b.com", "123456")

        assert result is False
        assert sent == []  # no SMTP connection attempted

    def test_html_contains_code(self):
        html = email_service_module._verification_html("013579")

        assert "013579" in html
        assert "DocuMind AI" in html
        assert "10 minutes" in html

    def test_smtp_delivery_happy_path(self, monkeypatch):
        # Restore the real sender (the autouse suite fixture stubs it out).
        monkeypatch.setattr(
            "utils.email_service.send_verification_email",
            ORIGINAL_SEND_VERIFICATION,
        )
        monkeypatch.setenv("SMTP_USERNAME", "bot@documind.ai")
        monkeypatch.setenv("SMTP_PASSWORD", "app-password")
        monkeypatch.setenv("SMTP_SERVER", "smtp.test.local")
        monkeypatch.setenv("SMTP_PORT", "2525")

        calls = {}

        class _FakeSMTP:
            def __init__(self, server, port, timeout=None):
                calls["server"] = server
                calls["port"] = port
                calls["started_tls"] = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                calls["started_tls"] = True

            def login(self, username, password):
                calls["login"] = username

            def sendmail(self, from_addr, to_addrs, payload):
                calls["from"] = from_addr
                calls["to"] = to_addrs
                calls["payload"] = payload

        monkeypatch.setattr(email_service_module.smtplib, "SMTP", _FakeSMTP)

        result = email_service_module.send_verification_email("u@example.com", "654321")

        assert result is True
        assert calls["server"] == "smtp.test.local"
        assert calls["port"] == 2525
        assert calls["started_tls"] is True
        assert calls["login"] == "bot@documind.ai"
        assert calls["to"] == ["u@example.com"]

        # MIMEText with utf-8 base64-encodes the body — decode the html part.
        import email as email_lib

        message = email_lib.message_from_string(calls["payload"])
        body = ""
        for part in message.walk():
            if part.get_content_type() == "text/html":
                body = part.get_payload(decode=True).decode("utf-8")
        assert "654321" in body

    def test_smtp_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("SMTP_USERNAME", "bot@documind.ai")
        monkeypatch.setenv("SMTP_PASSWORD", "app-password")

        class _Broken:
            def __init__(self, *args, **kwargs):
                raise OSError("smtp down")

        monkeypatch.setattr(email_service_module.smtplib, "SMTP", _Broken)

        assert email_service_module.send_verification_email("a@b.com", "123456") is False


class TestVerifyEmailEndpoint:

    def test_happy_path_activates_account_and_clears_code(self, client):
        _register(client, email="verify@example.com")
        user = _get_user("verify@example.com")
        code = user.verification_code

        response = client.post(
            "/auth/verify-email",
            json={"email": "verify@example.com", "code": code},
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Email verified successfully"

        user = _get_user("verify@example.com")
        assert user.is_verified is True
        assert user.verification_code is None
        assert user.code_expires_at is None

        # Login now works.
        login = client.post(
            "/auth/login",
            json={"email": "verify@example.com", "password": "Password123!"},
        )
        assert login.status_code == 200

    def test_wrong_code_rejected(self, client):
        _register(client, email="wrong@example.com")

        response = client.post(
            "/auth/verify-email",
            json={"email": "wrong@example.com", "code": "000000"},
        )

        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"]

        assert _get_user("wrong@example.com").is_verified is False

    def test_expired_code_rejected(self, client):
        _register(client, email="expired@example.com")
        # Naive UTC, matching the model's utcnow() convention (local now()
        # would be hours ahead of stored UTC on this machine).
        _set_expiry("expired@example.com", datetime.utcnow() - timedelta(minutes=1))

        user = _get_user("expired@example.com")

        response = client.post(
            "/auth/verify-email",
            json={"email": "expired@example.com", "code": user.verification_code},
        )

        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()

    def test_unknown_email_rejected(self, client):
        response = client.post(
            "/auth/verify-email",
            json={"email": "ghost@example.com", "code": "123456"},
        )

        assert response.status_code == 400

    def test_already_verified_rejected(self, client):
        from conftest import make_user

        user = make_user(client, email="already@example.com")

        response = client.post(
            "/auth/verify-email",
            json={"email": user["email"], "code": "123456"},
        )

        assert response.status_code == 400
        assert "already verified" in response.json()["detail"]


class TestResendCodeEndpoint:

    def test_resend_issues_new_code_and_invalidates_old(self, client):
        _register(client, email="resend@example.com")
        old_code = _get_user("resend@example.com").verification_code

        response = client.post(
            "/auth/resend-code", json={"email": "resend@example.com"}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Verification code sent to email"

        user = _get_user("resend@example.com")
        assert user.verification_code != old_code
        assert user.code_expires_at > datetime.utcnow()

        # Old code no longer verifies; new one does.
        old_try = client.post(
            "/auth/verify-email",
            json={"email": "resend@example.com", "code": old_code},
        )
        assert old_try.status_code == 400

        new_try = client.post(
            "/auth/verify-email",
            json={
                "email": "resend@example.com",
                "code": user.verification_code,
            },
        )
        assert new_try.status_code == 200

    def test_resend_unknown_user_404(self, client):
        response = client.post(
            "/auth/resend-code", json={"email": "ghost@example.com"}
        )

        assert response.status_code == 404

    def test_resend_for_verified_account_400(self, client):
        from conftest import make_user

        user = make_user(client, email="done@example.com")

        response = client.post(
            "/auth/resend-code", json={"email": user["email"]}
        )

        assert response.status_code == 400
