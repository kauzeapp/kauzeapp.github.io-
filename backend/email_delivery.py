import json
import os
import smtplib
import time
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESEND_MAX_ATTEMPTS = 3
RESEND_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def email_provider():
    if os.environ.get("RESEND_API_KEY") and os.environ.get("KAUZE_EMAIL_FROM"):
        return "resend"
    if all(
        os.environ.get(name)
        for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
    ):
        return "smtp"
    return "none"


def email_delivery_configured():
    return email_provider() != "none"


def _retry_delay(attempt, retry_after=None):
    if retry_after:
        try:
            return min(max(float(retry_after), 0.25), 5.0)
        except (TypeError, ValueError):
            pass
    return min(0.5 * (2**attempt), 2.0)


def _send_with_resend(recipient, subject, content, idempotency_key=None):
    payload = json.dumps(
        {
            "from": os.environ["KAUZE_EMAIL_FROM"],
            "to": [recipient],
            "subject": subject,
            "text": content,
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "Kauze/1.0",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = str(idempotency_key)[:256]

    last_error = None
    for attempt in range(RESEND_MAX_ATTEMPTS):
        request = Request(
            "https://api.resend.com/emails",
            data=payload,
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=15) as response:
                if response.status not in (200, 201):
                    raise RuntimeError(
                        f"Resend rechazo el correo ({response.status})."
                    )
                raw = response.read().decode("utf-8")
                result = json.loads(raw or "{}")
                if not result.get("id"):
                    raise RuntimeError(
                        "Resend no confirmo la recepcion del correo."
                    )
                return {"provider": "resend", "id": result["id"]}
        except HTTPError as exc:
            last_error = exc
            if (
                exc.code not in RESEND_RETRYABLE_STATUS
                or attempt == RESEND_MAX_ATTEMPTS - 1
            ):
                raise RuntimeError(
                    f"Resend rechazo el correo ({exc.code})."
                ) from exc
            time.sleep(_retry_delay(attempt, exc.headers.get("Retry-After")))
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == RESEND_MAX_ATTEMPTS - 1:
                raise RuntimeError("No fue posible conectar con Resend.") from exc
            time.sleep(_retry_delay(attempt))

    raise RuntimeError("No fue posible enviar el correo con Resend.") from last_error


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
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("El servidor SMTP rechazo al destinatario.")
    return {"provider": "smtp", "id": None}


def send_email(recipient, subject, content, idempotency_key=None):
    provider = email_provider()
    if provider == "resend":
        return _send_with_resend(recipient, subject, content, idempotency_key)
    if provider == "smtp":
        return _send_with_smtp(recipient, subject, content)
    raise RuntimeError("El servicio de correo de Kauze no esta configurado.")
