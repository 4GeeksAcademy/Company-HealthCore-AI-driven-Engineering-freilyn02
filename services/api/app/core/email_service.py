"""Transactional email sending via SendGrid.
Isolated so the reset-password business logic never talks to
SendGrid directly — makes it easy to swap providers or mock in tests.
"""
import os

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")

if not SENDGRID_API_KEY:
    raise RuntimeError("SENDGRID_API_KEY environment variable is not set")
if not SENDGRID_FROM_EMAIL:
    raise RuntimeError("SENDGRID_FROM_EMAIL environment variable is not set")


def send_reset_email(to_email: str, reset_link: str) -> None:
    """Send the password-reset email with the given link."""
    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject="Reset your password",
        html_content=(
            f"<p>We received a request to reset your password.</p>"
            f'<p><a href="{reset_link}">Click here to reset your password</a></p>'
            f"<p>This link expires in 30 minutes. If you didn't request this, "
            f"you can safely ignore this email.</p>"
        ),
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)