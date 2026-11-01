"""
Email verification (OTP) delivery via the Resend HTTPS API.

Render free instances block outbound SMTP ports (587/465/25), so email is
dispatched over HTTPS with the Resend Python SDK instead of smtplib.

generate_otp() returns a cryptographically random 6-digit code as a string
(leading zeros preserved). send_verification_email() sends a styled HTML
mail through Resend using:

    RESEND_API_KEY   (no default)

Console mode: when RESEND_API_KEY is missing or empty, no network call is
made — the code is printed to the server console instead and the function
returns False, so test suites and local runs without keys do not crash.
Callers must treat False as "not delivered", not as an error: the
verification code is already persisted, and the user can use resend-code.
"""

import logging
import os
import secrets

import resend

logger = logging.getLogger("documind.email")

OTP_LENGTH = 6

# Default production sender on the verified subdomain mail.mehebub-hasan.me
# (DKIM/SPF/DMARC configured in Resend). Override with the EMAIL_FROM env
# var without a code change.
DEFAULT_SENDER = "DocuMind AI <verify@mail.mehebub-hasan.me>"


def generate_otp() -> str:
    """Random 6-digit code as a string, e.g. '013579' (leading zeros kept)."""

    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def _verification_html(code: str) -> str:
    return f"""\
<div style="margin:0;padding:32px;background-color:#f6f6f2;font-family:
Arial,Helvetica,sans-serif;">
  <div style="max-width:480px;margin:0 auto;background-color:#ffffff;
  border:1px solid #e2e1db;border-radius:12px;padding:32px;">
    <p style="margin:0;font-size:20px;font-weight:bold;color:#1b1f24;">
      DocuMind AI
    </p>
    <p style="margin:16px 0 0;color:#565e66;font-size:14px;line-height:22px;">
      Use the verification code below to finish creating your account.
      It expires in 10 minutes.
    </p>
    <p style="margin:24px 0;text-align:center;">
      <span style="display:inline-block;padding:14px 28px;border-radius:8px;
      background-color:#f2f2ee;border:1px solid #e2e1db;
      font-size:30px;letter-spacing:10px;font-weight:bold;color:#1b1f24;
      font-family:'Courier New',monospace;">{code}</span>
    </p>
    <p style="margin:0;color:#8b929c;font-size:12px;line-height:18px;">
      If you did not request this code, you can safely ignore this email.
    </p>
  </div>
</div>"""


def send_verification_email(recipient_email: str, otp_code: str) -> bool:
    """
    Deliver the verification code over HTTPS via Resend. Returns True when
    Resend accepted the email, False in console mode (no API key) or on any
    delivery failure — never raises to the caller.
    """

    api_key = os.getenv("RESEND_API_KEY")

    if not api_key:
        print(
            f"[Email fallback - console mode] Verification code for "
            f"{recipient_email}: {otp_code}"
        )
        return False

    resend.api_key = api_key

    try:
        resend.Emails.send(
            {
                "from": os.getenv("EMAIL_FROM", DEFAULT_SENDER),
                "to": [recipient_email],
                "subject": "Verify your DocuMind AI account",
                "html": _verification_html(otp_code),
            }
        )
    except Exception as exc:
        logger.error(
            "[Email] Failed to send verification code to %s via Resend: %s",
            recipient_email,
            exc,
        )
        return False

    return True
