import json
import os
import smtplib
import time
from html import escape
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


def kauze_email_html(
    heading,
    greeting,
    paragraphs,
    action_url=None,
    action_label=None,
    detail_rows=None,
):
    """Construye la plantilla corporativa sin aceptar HTML externo."""
    logo_url = escape(
        os.environ.get(
            "KAUZE_EMAIL_LOGO_URL",
            "https://kauze.cl/app/kauze-logo-panel.png",
        ),
        quote=True,
    )
    safe_paragraphs = "".join(
        f'<p style="margin:0 0 16px;color:#52617a;font-size:15px;line-height:1.7;">{escape(str(item))}</p>'
        for item in (paragraphs or [])
    )
    safe_details = "".join(
        '<tr>'
        f'<td style="padding:8px 12px;color:#66748d;font-size:13px;">{escape(str(label))}</td>'
        f'<td style="padding:8px 12px;color:#0b1736;font-size:13px;font-weight:700;text-align:right;">{escape(str(value))}</td>'
        '</tr>'
        for label, value in (detail_rows or [])
    )
    details = (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin:18px 0;border:1px solid #dce5f4;border-radius:14px;background:#f7f9ff;">{safe_details}</table>'
        if safe_details
        else ""
    )
    action = ""
    if action_url and action_label:
        safe_url = escape(str(action_url), quote=True)
        action = (
            '<div style="margin:26px 0 22px;text-align:center;">'
            f'<a href="{safe_url}" style="display:inline-block;padding:14px 24px;border-radius:999px;'
            'background:linear-gradient(135deg,#2563eb,#6366f1);color:#ffffff;text-decoration:none;'
            f'font-size:15px;font-weight:800;">{escape(str(action_label))}</a></div>'
        )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#eef3ff;font-family:Arial,sans-serif;color:#0b1736;">'
        '<div style="display:none;max-height:0;overflow:hidden;">Acceso seguro a tu cuenta KAUZE.</div>'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:32px 12px;background:#eef3ff;">'
        '<tr><td align="center"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:600px;background:#ffffff;border:1px solid #dce5f4;border-radius:24px;overflow:hidden;box-shadow:0 18px 50px rgba(15,23,42,.10);">'
        '<tr><td style="padding:24px 30px;background:linear-gradient(135deg,#0b1736,#173b80);">'
        '<div style="display:inline-block;padding:9px 14px;border-radius:14px;background:#ffffff;">'
        f'<img src="{logo_url}" width="174" alt="KAUZE" '
        'style="display:block;width:174px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;">'
        '</div>'
        '<div style="margin-top:4px;color:#cbd8ff;font-size:12px;">El cauce que hace fluir tu negocio</div>'
        '</td></tr><tr><td style="padding:34px 30px;">'
        f'<p style="margin:0 0 8px;color:#2563eb;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;">{escape(str(greeting))}</p>'
        f'<h1 style="margin:0 0 22px;color:#0b1736;font-size:28px;line-height:1.2;">{escape(str(heading))}</h1>'
        f'{safe_paragraphs}{details}{action}'
        '<p style="margin:24px 0 0;color:#8a96aa;font-size:12px;line-height:1.6;">'
        'Si no solicitaste este mensaje, puedes ignorarlo o contactar al equipo KAUZE.</p>'
        '</td></tr><tr><td style="padding:18px 30px;background:#f7f9ff;color:#72809a;font-size:11px;text-align:center;">'
        'KAUZE · Gestión y reservas para negocios de servicios · kauze.cl</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def _send_with_resend(recipient, subject, content, idempotency_key=None, html=None):
    message = {
        "from": os.environ["KAUZE_EMAIL_FROM"],
        "to": [recipient],
        "subject": subject,
        "text": content,
    }
    if html:
        message["html"] = html
    payload = json.dumps(message).encode("utf-8")
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


def _send_with_smtp(recipient, subject, content, html=None):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = recipient
    message.set_content(content)
    if html:
        message.add_alternative(html, subtype="html")

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


def send_email(recipient, subject, content, idempotency_key=None, html=None):
    provider = email_provider()
    if provider == "resend":
        return _send_with_resend(recipient, subject, content, idempotency_key, html)
    if provider == "smtp":
        return _send_with_smtp(recipient, subject, content, html)
    raise RuntimeError("El servicio de correo de Kauze no esta configurado.")
