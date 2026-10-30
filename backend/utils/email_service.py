"""
Email verification (OTP) delivery.

generate_otp() returns a cryptographically random 6-digit code as a string
(leading zeros preserved). send_verification_email() sends a styled HTML
mail via SMTP using credentials from environment variables:

    SMTP_SERVER   (default smtp.gmail.com)
    SMTP_PORT     (default 587)
    SMTP_USERNAME (no default)
    SMTP_PASSWORD (no default)

Dev/console mode: when SMTP_USERNAME or SMTP_PASSWORD is unset, no network
call is made — the code is written to the server log instead and the
function returns False. Callers must treat False as "not delivered", not as
an error: the verification code is already persisted, and the user can use
resend-code once SMTP is configured.
"""

import logging
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

logger = logging.getLogger("documind.email")

OTP_LENGTH = 6


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


def send_verification_email(recipient_email: str, code: str) -> bool:
    """
    Deliver the verification code. Returns True when the email was handed
    to the SMTP server, False in console mode (credentials missing) or on
    any delivery failure — never raises to the caller.
    """

    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    if not username or not password:
        logger.info(
            "[Email] SMTP not configured — console mode. Verification code "
            "for %s: %s",
            recipient_email,
            code,
        )
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = "Your DocuMind AI verification code"
    message["From"] = f"DocuMind AI <{username}>"
    message["To"] = recipient_email
    message.attach(MIMEText(_verification_html(code), "html", "utf-8"))

    server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))

    try:
        with smtplib.SMTP(server, port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(username, [recipient_email], message.as_string())
    except Exception as exc:
        logger.error(
            "[Email] Failed to send verification code to %s: %s",
            recipient_email,
            exc,
        )
        return False

    return True
