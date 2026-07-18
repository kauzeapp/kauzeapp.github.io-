import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from html import escape

from backend.db import connection


PUBLIC_BOOKING_WINDOW_SECONDS = 300
PUBLIC_BOOKING_MAX_REQUESTS = 8
DEFAULT_SLOTS = (
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "12:00",
    "12:30",
    "14:00",
    "14:30",
    "15:00",
    "15:30",
    "16:00",
    "16:30",
    "17:00",
    "17:30",
    "18:00",
)

_rate_lock = threading.Lock()
_rate_events = {}


class PublicBookingError(ValueError):
    def __init__(self, message, code="invalid_booking", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _clean_text(value, field, minimum=1, maximum=120, required=True):
    text = " ".join(str(value or "").strip().split())
    if required and len(text) < minimum:
        raise PublicBookingError(f"Falta {field}.", f"missing_{field}")
    if len(text) > maximum or "<" in text or ">" in text:
        raise PublicBookingError(f"{field.capitalize()} no es válido.", f"invalid_{field}")
    return text


def _duration_minutes(value):
    match = re.search(r"\d+", str(value or ""))
    return max(5, min(int(match.group()) if match else 30, 1440))


def _public_text(value, maximum=240):
    return escape(" ".join(str(value or "").strip().split())[:maximum])


def _typed_rows(state, key, business_type):
    collection = state.get(key) or {}
    rows = collection.get(business_type) if isinstance(collection, dict) else []
    return rows if isinstance(rows, list) else []


def _is_public(state):
    return bool(state.get("publicBookingEnabled") or state.get("demoMode"))


def _service_payload(row, index):
    if isinstance(row, list):
        return {
            "id": f"service-{index}",
            "name": _public_text(row[0] if len(row) > 0 else "Servicio", 100),
            "duration": _public_text(row[1] if len(row) > 1 else "30 min", 30),
            "price": int(row[2] if len(row) > 2 else 0),
        }
    return {
        "id": str(row.get("id") or f"service-{index}"),
        "name": _public_text(row.get("name") or "Servicio", 100),
        "duration": _public_text(row.get("duration") or "30 min", 30),
        "price": max(0, int(row.get("price") or 0)),
    }


def _professional_payload(row, index):
    if isinstance(row, list):
        return {
            "id": f"professional-{index}",
            "name": _public_text(row[0] if len(row) > 0 else "Profesional", 100),
            "role": _public_text(row[1] if len(row) > 1 else "Profesional", 100),
            "note": _public_text(row[2] if len(row) > 2 else "", 180),
        }
    return {
        "id": str(row.get("id") or f"professional-{index}"),
        "name": _public_text(row.get("name") or "Profesional", 100),
        "role": _public_text(row.get("role") or "Profesional", 100),
        "note": _public_text(row.get("note") or "", 180),
    }


def _appointments(state, business_type):
    return _typed_rows(state, "appointments", business_type)


def _available_slots(state, business_type, target_date, professional_name=None):
    occupied = {
        str(item.get("time") or "")
        for item in _appointments(state, business_type)
        if str(item.get("date") or "") == target_date
        and str(item.get("status") or "").lower() not in ("cancelada", "cancelled")
        and (not professional_name or item.get("professional") == professional_name)
    }
    return [slot for slot in DEFAULT_SLOTS if slot not in occupied]


def _public_business(row):
    state = row.get("panel_state") or {}
    business_type = str(state.get("type") or row.get("category_slug") or "barberia")
    services = [
        _service_payload(item, index)
        for index, item in enumerate(_typed_rows(state, "services", business_type), 1)
    ]
    professionals = [
        _professional_payload(item, index)
        for index, item in enumerate(
            _typed_rows(state, "professionals", business_type), 1
        )
    ]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return {
        "id": str(row["slug"]),
        "slug": str(row["slug"]),
        "type": business_type,
        "name": _public_text(row["name"], 120),
        "description": _public_text(row.get("description") or "Negocio asociado a Kauze."),
        "address": _public_text(row.get("address") or "Dirección por confirmar", 160),
        "location": _public_text(row.get("commune") or row.get("city") or "Santiago", 100),
        "city": _public_text(row.get("city") or "Santiago", 100),
        "route": f'{row["slug"]}.kauze.cl',
        "rating": str(state.get("publicRating") or "5.0"),
        "reviews": int(state.get("publicReviews") or 1),
        "statusLabel": "Disponible" if state.get("businessStatus") == "DISPONIBLE" else "Agenda pausada",
        "statusTone": "good" if state.get("businessStatus") == "DISPONIBLE" else "warn",
        "hero": _public_text(state.get("pageTitle") or "Reserva tu próxima hora con Kauze.", 180),
        "subtitle": _public_text(state.get("pageSubtitle") or "Elige servicio, profesional y horario.", 240),
        "cta": _public_text(state.get("pageCta") or "Reservar ahora", 80),
        "bannerStyle": str(state.get("bannerStyle") or "soft"),
        "bannerImage": str(state.get("bannerImage") or ""),
        "activeTheme": str(state.get("activeTheme") or "Kauze Base"),
        "demoMode": bool(state.get("demoMode")),
        "deposit": {
            "enabled": bool(state.get("depositEnabled")),
            "mode": str(state.get("depositMode") or "none"),
            "percent": int(state.get("depositPercent") or 0),
            "fixedAmount": int(state.get("depositFixedAmount") or 0),
            "minimum": int(state.get("depositMinimum") or 0),
        },
        "services": services,
        "professionals": professionals,
        "nextSlots": _available_slots(state, business_type, tomorrow)[:4],
    }


def list_public_businesses():
    from psycopg.rows import dict_row

    with connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """
            SELECT
              l.nombre AS name,
              l.slug,
              l.descripcion AS description,
              l.direccion AS address,
              l.comuna AS commune,
              l.ciudad AS city,
              c.slug AS category_slug,
              e.estado AS panel_state
            FROM locales l
            INNER JOIN categorias c ON c.id = l.categoria_id AND c.activo = TRUE
            INNER JOIN estados_panel_local e ON e.local_id = l.id
            WHERE l.estado = 'activo'
              AND (
                COALESCE(e.estado->>'publicBookingEnabled', 'false') = 'true'
                OR COALESCE(e.estado->>'demoMode', 'false') = 'true'
              )
            ORDER BY l.nombre
            """
        ).fetchall()
    return [_public_business(row) for row in rows]


def public_availability(slug, target_date, professional_id=None):
    from psycopg.rows import dict_row

    try:
        parsed_date = date.fromisoformat(str(target_date or ""))
    except ValueError as exc:
        raise PublicBookingError("La fecha no es válida.", "invalid_date") from exc
    if parsed_date < date.today() or parsed_date > date.today() + timedelta(days=365):
        raise PublicBookingError("La fecha está fuera del período disponible.", "invalid_date")

    with connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            SELECT l.slug, c.slug AS category_slug, e.estado AS panel_state
            FROM locales l
            INNER JOIN categorias c ON c.id = l.categoria_id
            INNER JOIN estados_panel_local e ON e.local_id = l.id
            WHERE l.slug = %s AND l.estado = 'activo'
            LIMIT 1
            """,
            (slug,),
        ).fetchone()
    if not row or not _is_public(row["panel_state"] or {}):
        raise PublicBookingError("El negocio no está disponible.", "business_not_found", 404)

    state = row["panel_state"] or {}
    business_type = str(state.get("type") or row["category_slug"])
    professionals = [
        _professional_payload(item, index)
        for index, item in enumerate(
            _typed_rows(state, "professionals", business_type), 1
        )
    ]
    professional = next(
        (item for item in professionals if item["id"] == professional_id), None
    )
    return {
        "date": parsed_date.isoformat(),
        "slots": _available_slots(
            state,
            business_type,
            parsed_date.isoformat(),
            professional["name"] if professional else None,
        ),
    }


def _rate_limit(client_key):
    now = time.monotonic()
    key = str(client_key or "unknown")[:120]
    with _rate_lock:
        recent = [
            event
            for event in _rate_events.get(key, [])
            if now - event < PUBLIC_BOOKING_WINDOW_SECONDS
        ]
        if len(recent) >= PUBLIC_BOOKING_MAX_REQUESTS:
            raise PublicBookingError(
                "Demasiados intentos. Espera unos minutos.", "rate_limited", 429
            )
        recent.append(now)
        _rate_events[key] = recent


def create_public_appointment(payload, client_key="unknown"):
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    if not isinstance(payload, dict):
        raise PublicBookingError("La reserva no es válida.")
    if payload.get("website"):
        raise PublicBookingError("La reserva no es válida.")
    _rate_limit(client_key)

    business_slug = _clean_text(payload.get("businessSlug"), "negocio", maximum=100)
    service_id = _clean_text(payload.get("serviceId"), "servicio", maximum=100)
    professional_id = _clean_text(
        payload.get("professionalId"), "profesional", maximum=100
    )
    client_name = _clean_text(payload.get("clientName"), "nombre", minimum=2, maximum=100)
    phone = _clean_text(payload.get("phone"), "teléfono", minimum=7, maximum=24)
    email = _clean_text(payload.get("email"), "correo", maximum=160, required=False)
    request_id = _clean_text(
        payload.get("requestId") or secrets.token_urlsafe(12),
        "solicitud",
        maximum=100,
    )

    try:
        target_date = date.fromisoformat(str(payload.get("date") or ""))
        target_time = datetime.strptime(str(payload.get("time") or ""), "%H:%M").time()
    except ValueError as exc:
        raise PublicBookingError("La fecha u hora no es válida.", "invalid_schedule") from exc
    if target_date < date.today() or target_date > date.today() + timedelta(days=365):
        raise PublicBookingError("La fecha está fuera del período disponible.", "invalid_schedule")
    if target_time.minute not in (0, 30) or target_time.hour < 9 or target_time.hour > 21:
        raise PublicBookingError("La hora no está disponible.", "invalid_schedule")

    with connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            SELECT
              l.id AS local_id,
              l.nombre AS business_name,
              l.slug,
              c.slug AS category_slug,
              e.estado AS panel_state
            FROM locales l
            INNER JOIN categorias c ON c.id = l.categoria_id AND c.activo = TRUE
            INNER JOIN estados_panel_local e ON e.local_id = l.id
            WHERE l.slug = %s AND l.estado = 'activo'
            FOR UPDATE OF e
            """,
            (business_slug,),
        ).fetchone()
        if not row or not _is_public(row["panel_state"] or {}):
            raise PublicBookingError("El negocio no está disponible.", "business_not_found", 404)

        state = dict(row["panel_state"] or {})
        if state.get("businessStatus") != "DISPONIBLE":
            raise PublicBookingError("La agenda del negocio está pausada.", "business_paused", 409)
        business_type = str(state.get("type") or row["category_slug"])
        services = [
            _service_payload(item, index)
            for index, item in enumerate(_typed_rows(state, "services", business_type), 1)
        ]
        professionals = [
            _professional_payload(item, index)
            for index, item in enumerate(
                _typed_rows(state, "professionals", business_type), 1
            )
        ]
        service = next((item for item in services if item["id"] == service_id), None)
        professional = next(
            (item for item in professionals if item["id"] == professional_id), None
        )
        if not service or not professional:
            raise PublicBookingError("El servicio o profesional ya no está disponible.", "selection_unavailable", 409)

        appointments_group = dict(state.get("appointments") or {})
        appointments = list(appointments_group.get(business_type) or [])
        existing = next(
            (item for item in appointments if item.get("requestId") == request_id), None
        )
        if existing:
            return {"appointment": existing, "business": row["business_name"], "created": False}

        conflict = next(
            (
                item
                for item in appointments
                if item.get("date") == target_date.isoformat()
                and item.get("time") == target_time.strftime("%H:%M")
                and item.get("professional") == professional["name"]
                and str(item.get("status") or "").lower() not in ("cancelada", "cancelled")
            ),
            None,
        )
        if conflict:
            raise PublicBookingError("Esa hora acaba de ser reservada. Elige otra.", "slot_unavailable", 409)

        appointment_id = f"public-{secrets.token_urlsafe(10)}"
        code = f"{secrets.randbelow(1_000_000):06d}"
        created_at = datetime.now(timezone.utc).isoformat()
        appointment = {
            "id": appointment_id,
            "requestId": request_id,
            "date": target_date.isoformat(),
            "time": target_time.strftime("%H:%M"),
            "client": client_name,
            "name": client_name,
            "phone": phone,
            "email": email,
            "service": service["name"],
            "serviceId": service["id"],
            "duration": service["duration"],
            "price": service["price"],
            "professional": professional["name"],
            "professionalId": professional["id"],
            "status": "Esperando confirmación",
            "confirmationStatus": "Pendiente",
            "paymentStatus": "Sin abono",
            "paymentMethod": "No aplica",
            "depositAmount": 0,
            "remainingAmount": service["price"],
            "whatsappReminderStatus": "Programado",
            "calendarStatus": "Pendiente de integración",
            "notifications": [
                {
                    "channel": "app",
                    "status": "ok",
                    "text": "Nueva reserva recibida en el panel Kauze",
                    "target": "Panel del negocio",
                    "at": created_at,
                }
            ],
            "source": "cliente",
            "createdAt": created_at,
            "code": code,
        }
        appointments.append(appointment)
        appointments_group[business_type] = appointments
        state["appointments"] = appointments_group

        clients_group = dict(state.get("clients") or {})
        clients = list(clients_group.get(business_type) or [])
        normalized_phone = re.sub(r"\D", "", phone)
        client_index = next(
            (
                index
                for index, item in enumerate(clients)
                if re.sub(r"\D", "", str(item.get("phone") or "")) == normalized_phone
                or (email and str(item.get("email") or "").lower() == email.lower())
            ),
            None,
        )
        client_payload = {
            "id": f"client-{secrets.token_urlsafe(8)}",
            "name": client_name,
            "phone": phone,
            "email": email,
            "lastService": service["name"],
            "nextAction": "Confirmar asistencia",
            "totalBilling": 0,
            "internalRating": None,
        }
        if client_index is None:
            clients.append(client_payload)
        else:
            clients[client_index] = {**clients[client_index], **client_payload, "id": clients[client_index].get("id") or client_payload["id"]}
        clients_group[business_type] = clients
        state["clients"] = clients_group

        conn.execute(
            """
            UPDATE estados_panel_local
            SET estado = %s, actualizado_en = NOW(), version = version + 1
            WHERE local_id = %s
            """,
            (Jsonb(state), row["local_id"]),
        )
        return {"appointment": appointment, "business": row["business_name"], "created": True}
