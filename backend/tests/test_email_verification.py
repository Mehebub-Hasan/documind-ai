from datetime import datetime, timedelta, timezone

import pytest

from database import SessionLocal
from models import User as UserModel
import utils.email_service as email_service_module
from utils.email_service import generate_otp

# Captured at import time, before the autouse disable_email_delivery fixture
# replaces the module attribute for the duration of each test.
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
    # The suite-wide autouse fixture (conftest.disable_email_delivery) stubs
    # send_verification_email so no other test can send email. These tests
    # exercise the real implementation, so restore it for this class only.
    @pytest.fixture(autouse=True)
    def use_real_sender(self, monkeypatch):
        monkeypatch.setattr(
            "utils.email_service.send_verification_email",
            ORIGINAL_SEND_VERIFICATION,
        )

    def test_console_mode_without_credentials(self, monkeypatch):
        # When RESEND_API_KEY is not set, it should not call resend.Emails.send
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        from utils import email_service
        monkeypatch.setattr(email_service, "resend_api_key", None, raising=False)
        if hasattr(email_service, "resend"):
            monkeypatch.setattr(email_service.resend, "api_key", None)

        called = []
        if hasattr(email_service, "resend"):
            monkeypatch.setattr(email_service.resend.Emails, "send", lambda *args, **kwargs: called.append(True))

        email_service.send_verification_email("eval@documind.ai", "123456")
        assert len(called) == 0

    def test_resend_delivery_happy_path(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
        from utils import email_service
        monkeypatch.setattr(email_service, "resend_api_key", "re_test_key_123", raising=False)

        sent_payloads = []
        if hasattr(email_service, "resend"):
            monkeypatch.setattr(email_service.resend, "api_key", "re_test_key_123")
            monkeypatch.setattr(email_service.resend.Emails, "send", lambda payload: sent_payloads.append(payload))

        email_service.send_verification_email("eval@documind.ai", "123456")
        assert len(sent_payloads) == 1
        assert "123456" in sent_payloads[0].get("html", "")

    def test_resend_failure_handled(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
        from utils import email_service
        monkeypatch.setattr(email_service, "resend_api_key", "re_test_key_123", raising=False)

        def _raise_error(*args, **kwargs):
            raise Exception("Resend API down")

        if hasattr(email_service, "resend"):
            monkeypatch.setattr(email_service.resend.Emails, "send", _raise_error)

        # Ensure it does not crash the caller
        email_service.send_verification_email("eval@documind.ai", "123456")


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
        # Naive UTC (aware "now" stripped), matching the model's utcnow()
        # convention — local time or an aware datetime would break the
        # naive-datetime comparison.
        _set_expiry(
            "expired@example.com",
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
        )

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
        assert user.code_expires_at > datetime.now(timezone.utc).replace(
            tzinfo=None
        )

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
