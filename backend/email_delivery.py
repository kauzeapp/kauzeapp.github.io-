import json
import os
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def email_provider():
    if os.environ.get("RESEND_API_KEY") and os.environ.get("KAUZE_EMAIL_FROM"):
        return "resend"
    if all(os.environ.get(name) for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")):
        return "smtp"
    return "none"


def email_delivery_configured():
    return email_provider() != "none"


def _send_with_resend(recipient, subject, content):
    payload = json.dumps(
        {
            "from": os.environ["KAUZE_EMAIL_FROM"],
            "to": [recipient],
            "subject": subject,
            "text": content,
        }
    ).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": "Kauze/1.0",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status not in (200, 201):
                raise RuntimeError("Resend rechazó el correo.")
    except HTTPError as exc:
        raise RuntimeError(f"Resend rechazó el correo ({exc.code}).") from exc
    except URLError as exc:
        raise RuntimeError("No fue posible conectar con Resend.") from exc


def _send_with_smtp(recipient, subject, content):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = recipient
    message.set_content(content)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_SSL", "0") == "1"
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=15) as smtp:
        if not use_ssl and os.environ.get("SMTP_STARTTLS", "1") == "1":
            smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def send_email(recipient, subject, content):
    provider = email_provider()
    if provider == "resend":
        _send_with_resend(recipient, subject, content)
        return
    if provider == "smtp":
        _send_with_smtp(recipient, subject, content)
        return
    raise RuntimeError("El servicio de correo de Kauze no está configurado.")
