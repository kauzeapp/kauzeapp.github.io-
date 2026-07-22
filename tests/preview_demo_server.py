"""Servidor local desechable para probar el flujo cliente -> panel sin Railway."""

import json
import os
import secrets
import sys
from copy import deepcopy
from datetime import date, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from backend.public_booking import _available_slots, _professional_payload, _service_payload
from backend.email_delivery import kauze_email_html
from backend.seed_demo import DEMO_NAME, DEMO_SLUG, build_panel_state


PORT = int(os.environ.get("PORT", "8891"))
STATE = build_panel_state()
if os.environ.get("PREVIEW_NEW_ACCOUNT") == "1":
    STATE.update(
        {
            "name": "Mi negocio en Kauze",
            "professionals": {"barberia": []},
            "services": {"barberia": []},
            "appointments": {"barberia": []},
            "clients": {"barberia": []},
            "publicBookingEnabled": False,
            "address": "",
            "commune": "",
            "city": "",
            "latitude": None,
            "longitude": None,
            "businessStatus": "CERRADO",
            "operatingDay": {"date": "", "openedAt": ""},
            "onboarding": {"welcomeDismissed": False, "tourCompleted": False},
        }
    )
MASTERPLAN_STATE = deepcopy(STATE)
MASTERPLAN_STATE.update(
    {
        "name": "Masterplan Barbería — DEMO",
        "pageTitle": "Reserva tu hora en Masterplan Barbería",
        "pageSubtitle": "Elige servicio, profesional y horario. Para ver trabajos y ejemplos, visita su Instagram.",
        "instagramUrl": "https://www.instagram.com/masterplan.soluciones?igsh=MXVsNnF3NXI5M2hkMA==",
        "instagramHandle": "@masterplan.soluciones",
        "publicPhone": "+56 9 8765 4321",
        "logoUrl": "/cliente/assets/masterplan-logo.jpg",
        "publicSubdomain": "masterplan",
        "professionals": {
            "barberia": [
                {
                    "id": "masterplan-pro-1",
                    "name": "Benjamín Soto",
                    "role": "Barbero senior",
                    "note": "Perfil ficticio para pruebas internas.",
                },
                {
                    "id": "masterplan-pro-2",
                    "name": "Martina Rojas",
                    "role": "Especialista en fade",
                    "note": "Perfil ficticio para pruebas internas.",
                },
            ]
        },
        "services": {
            "barberia": [
                {"id": "masterplan-ser-1", "name": "Corte clásico", "duration": "45 min", "price": 12000},
                {"id": "masterplan-ser-2", "name": "Fade", "duration": "60 min", "price": 16000},
                {"id": "masterplan-ser-3", "name": "Perfilado de barba", "duration": "30 min", "price": 10000},
            ]
        },
        "appointments": {"barberia": []},
        "clients": {"barberia": []},
    }
)
BUSINESS_STATES = {DEMO_SLUG: STATE, "masterplan": MASTERPLAN_STATE}
PREVIEW_BUSINESS_SLUG = os.environ.get("PREVIEW_BUSINESS", DEMO_SLUG)
if PREVIEW_BUSINESS_SLUG not in BUSINESS_STATES:
    PREVIEW_BUSINESS_SLUG = DEMO_SLUG
PREVIEW_STATE = BUSINESS_STATES[PREVIEW_BUSINESS_SLUG]
ACCOUNT = {
    "user": {
        "id": "preview-owner",
        "name": "Sergio Molina",
        "email": "preview@kauze.cl",
        "profileImage": "",
    },
    "business": {
        "id": f"preview-{PREVIEW_BUSINESS_SLUG}",
        "name": PREVIEW_STATE["name"],
        "slug": PREVIEW_BUSINESS_SLUG,
        "type": "barberia",
        "status": "activo",
        "subdomainStatus": "activo",
        "subdomain": f"{PREVIEW_BUSINESS_SLUG}.kauze.cl",
        "subdomainUrl": f"https://{PREVIEW_BUSINESS_SLUG}.kauze.cl",
    },
    "role": {"id": "preview-role", "name": "Dueño", "slug": "dueno"},
    "isSuperAdmin": True,
}

PREVIEW_ADMIN_CLIENTS = [
    {
        "id": "preview-owner", "name": "Sergio Molina", "email": "preview@kauze.cl",
        "phone": "+56911112222", "businessName": "KAUZE Demo", "categoriaSlug": "barberia",
        "planTipo": "trial", "estadoSuscripcion": "trial",
        "fechaVencimiento": (date.today() + timedelta(days=7)).isoformat(),
        "requiereAprobacion": False, "subdominio": "kauze-demo.kauze.cl",
        "subdominioEstado": "activo", "subdominioUrl": "https://kauze-demo.kauze.cl",
    },
    {
        "id": "preview-masterplan", "name": "Esteban", "email": "masterplan@example.com",
        "phone": "+56987654321", "businessName": "Masterplan Soluciones", "categoriaSlug": "barberia",
        "planTipo": "mensual", "estadoSuscripcion": "activo",
        "fechaVencimiento": (date.today() + timedelta(days=30)).isoformat(),
        "requiereAprobacion": False, "subdominio": "masterplansoluciones.kauze.cl",
        "subdominioEstado": "pendiente", "subdominioUrl": None,
    },
    {
        "id": "preview-suspended", "name": "Cuenta de prueba", "email": "suspendido@example.com",
        "phone": "+56955554444", "businessName": "Negocio Suspendido", "categoriaSlug": "barberia",
        "planTipo": "mensual", "estadoSuscripcion": "desactivado",
        "fechaVencimiento": (date.today() - timedelta(days=1)).isoformat(),
        "requiereAprobacion": False, "subdominio": "negocio-suspendido.kauze.cl",
        "subdominioEstado": "activo", "subdominioUrl": "https://negocio-suspendido.kauze.cl",
    },
]


def business_payload(slug=DEMO_SLUG):
    state = BUSINESS_STATES[slug]
    services = [
        _service_payload(item, index)
        for index, item in enumerate(state["services"]["barberia"], 1)
    ]
    professionals = [
        _professional_payload(item, index)
        for index, item in enumerate(state["professionals"]["barberia"], 1)
    ]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    is_masterplan = slug == "masterplan"
    is_new_account_preview = os.environ.get("PREVIEW_NEW_ACCOUNT") == "1" and slug == DEMO_SLUG
    return {
        "id": slug,
        "slug": slug,
        "type": "barberia",
        "name": state["name"],
        "description": "Perfil ficticio conectado a Instagram para probar reservas directas en Kauze." if is_masterplan else "Demo funcional conectada entre cliente y panel.",
        "address": state.get("address") or ("Avenida Demo 456" if is_masterplan else "Avenida Demo 123"),
        "location": state.get("commune") or "Providencia",
        "city": state.get("city") or "Santiago",
        "lat": state.get("latitude"),
        "lng": state.get("longitude"),
        "route": "masterplan.kauze.cl" if is_masterplan else f"{DEMO_SLUG}.kauze.cl",
        "logoUrl": state.get("logoUrl", ""),
        "instagramUrl": state.get("instagramUrl", ""),
        "instagramHandle": state.get("instagramHandle", ""),
        "phone": state.get("publicPhone", ""),
        "rating": None if is_new_account_preview else "5.0",
        "reviews": 0 if is_new_account_preview else (1 if is_masterplan else 24),
        "statusLabel": "Disponible",
        "statusTone": "good",
        "hero": state["pageTitle"],
        "subtitle": state["pageSubtitle"],
        "cta": state["pageCta"],
        "demoMode": True,
        "deposit": {"enabled": False, "mode": "none", "percent": 0, "fixedAmount": 0, "minimum": 0},
        "services": services,
        "professionals": professionals,
        "nextSlots": _available_slots(state, "barberia", tomorrow)[:4],
    }


class PreviewHandler(SimpleHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            return self.json_response(200, {"status": "ok", "preview": True})
        if path == "/email-preview/":
            body = kauze_email_html(
                "Activa tu prueba gratis",
                "Hola Sergio",
                [
                    "Tu negocio Barbería Demo ya fue preparado en KAUZE.",
                    "Crea tu contraseña y entra a configurar el logo, los servicios, los trabajadores y la agenda.",
                    "Tu prueba gratuita dura 7 días.",
                ],
                "http://127.0.0.1:8896/app/",
                "Crear mi contraseña",
                [("Negocio", "Barbería Demo"), ("Plan", "Trial · 7 días")],
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/auth/me":
            return self.json_response(200, {"account": ACCOUNT})
        if path == "/api/admin/clientes":
            return self.json_response(200, PREVIEW_ADMIN_CLIENTS)
        if path == "/api/admin/dashboard/stats":
            stats = {"trial": 0, "activo": 0, "en_mora": 0, "desactivado": 0}
            for client in PREVIEW_ADMIN_CLIENTS:
                state = client.get("estadoSuscripcion", "trial")
                if state in stats:
                    stats[state] += 1
            stats["total"] = len(PREVIEW_ADMIN_CLIENTS)
            return self.json_response(200, stats)
        if path.startswith("/api/public/subdomains/"):
            slug = unquote(path.rstrip("/").split("/")[-1]).lower()
            client = next(
                (
                    item for item in PREVIEW_ADMIN_CLIENTS
                    if str(item.get("subdominio") or "").split(".", 1)[0] == slug
                    and item.get("subdominioEstado") == "activo"
                    and item.get("estadoSuscripcion") in ("trial", "activo")
                ),
                None,
            )
            if not client:
                return self.json_response(404, {"error": "subdomain_not_active"})
            return self.json_response(200, {
                "active": True,
                "slug": slug,
                "destination": f"https://kauze.cl/cliente/?negocio={slug}",
            })
        if path == "/api/app-state":
            return self.json_response(200, BUSINESS_STATES[PREVIEW_BUSINESS_SLUG])
        if path == "/api/public/businesses":
            return self.json_response(200, {"businesses": [business_payload(), business_payload("masterplan")]})
        if path.startswith("/api/public/businesses/") and path.endswith("/availability"):
            parts = [unquote(part) for part in path.strip("/").split("/")]
            slug = parts[3]
            state = BUSINESS_STATES.get(slug)
            if not state:
                return self.json_response(404, {"error": "business_not_found"})
            query = parse_qs(parsed.query)
            target_date = (query.get("date") or [date.today().isoformat()])[0]
            professional_id = (query.get("professionalId") or [None])[0]
            professional = next(
                (
                    item
                    for index, raw in enumerate(state["professionals"]["barberia"], 1)
                    if (item := _professional_payload(raw, index))["id"] == professional_id
                ),
                None,
            )
            slots = _available_slots(
                state,
                "barberia",
                target_date,
                professional["name"] if professional else None,
            )
            return self.json_response(200, {"date": target_date, "slots": slots})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/app-state":
            BUSINESS_STATES[PREVIEW_BUSINESS_SLUG] = self.read_json()
            return self.json_response(200, {"status": "success", "version": 1})
        if path == "/api/account/profile-image":
            data = self.read_json()
            ACCOUNT["user"]["profileImage"] = str(data.get("profileImage") or "")
            return self.json_response(
                200,
                {
                    "status": "success",
                    "profileImage": ACCOUNT["user"]["profileImage"],
                },
            )
        if path == "/api/auth/logout":
            return self.json_response(200, {"status": "success"})
        if path != "/api/public/appointments":
            return self.json_response(404, {"error": "not_found"})

        data = self.read_json()
        slug = data.get("businessSlug", DEMO_SLUG)
        state = BUSINESS_STATES.get(slug)
        if not state:
            return self.json_response(404, {"error": "business_not_found"})
        services = [
            _service_payload(item, index)
            for index, item in enumerate(state["services"]["barberia"], 1)
        ]
        professionals = [
            _professional_payload(item, index)
            for index, item in enumerate(state["professionals"]["barberia"], 1)
        ]
        service = next(item for item in services if item["id"] == data["serviceId"])
        professional = next(item for item in professionals if item["id"] == data["professionalId"])
        appointment = {
            "id": f"preview-{secrets.token_urlsafe(8)}",
            "requestId": data["requestId"],
            "date": data["date"],
            "time": data["time"],
            "client": data["clientName"],
            "name": data["clientName"],
            "phone": data["phone"],
            "email": data.get("email", ""),
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
            "notifications": [],
            "source": "cliente",
            "createdAt": date.today().isoformat(),
            "code": f"{secrets.randbelow(1_000_000):06d}",
        }
        state["appointments"]["barberia"].append(appointment)
        state["clients"]["barberia"].append(
            {
                "id": f"preview-client-{secrets.token_urlsafe(6)}",
                "name": appointment["client"],
                "phone": appointment["phone"],
                "email": appointment["email"],
                "lastService": appointment["service"],
                "nextAction": "Confirmar asistencia",
                "totalBilling": 0,
                "stars": 5,
            }
        )
        return self.json_response(201, {"appointment": appointment, "business": state["name"], "created": True})

    def do_PUT(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["api", "admin", "clientes"]:
            return self.json_response(404, {"error": "not_found"})
        client = next((item for item in PREVIEW_ADMIN_CLIENTS if item["id"] == parts[3]), None)
        if not client:
            return self.json_response(404, {"error": "client_not_found"})
        if parts[4] == "activar":
            client["estadoSuscripcion"] = "trial" if client.get("planTipo") == "trial" else "activo"
            client["fechaVencimiento"] = (
                date.today() + timedelta(days=7 if client["estadoSuscripcion"] == "trial" else 30)
            ).isoformat()
            return self.json_response(200, {"status": "success", "state": client["estadoSuscripcion"]})
        if parts[4] == "editar":
            data = self.read_json()
            mapping = {
                "name": "name", "email": "email", "phone": "phone",
                "businessName": "businessName", "categoriaSlug": "categoriaSlug",
                "planTipo": "planTipo", "estadoSuscripcion": "estadoSuscripcion",
                "fechaVencimiento": "fechaVencimiento",
            }
            for source, target in mapping.items():
                if source in data:
                    client[target] = data[source]
            if data.get("subdominio"):
                slug = str(data["subdominio"]).lower().replace(".kauze.cl", "")
                client["subdominio"] = f"{slug}.kauze.cl"
            return self.json_response(200, {"status": "success", "message": "Cliente actualizado."})
        if parts[4] != "subdominio":
            return self.json_response(404, {"error": "not_found"})
        data = self.read_json()
        slug = str(data.get("subdominio") or "").strip().lower()
        if not slug or any(
            item["id"] != client["id"]
            and str(item.get("subdominio") or "").split(".", 1)[0] == slug
            for item in PREVIEW_ADMIN_CLIENTS
        ):
            return self.json_response(400, {"message": "El subdominio ya está en uso."})
        target = "activo" if data.get("action") == "activar" else "suspendido"
        client["subdominio"] = f"{slug}.kauze.cl"
        client["subdominioEstado"] = target
        client["subdominioUrl"] = f"https://{slug}.kauze.cl" if target == "activo" else None
        return self.json_response(200, {
            "status": "success",
            "message": "Subdominio activado correctamente." if target == "activo" else "Subdominio suspendido.",
            "subdominio": client["subdominio"],
            "subdominioEstado": target,
            "subdominioUrl": client["subdominioUrl"],
        })


if __name__ == "__main__":
    os.chdir(PROJECT_DIR)
    ThreadingHTTPServer(("127.0.0.1", PORT), PreviewHandler).serve_forever()
