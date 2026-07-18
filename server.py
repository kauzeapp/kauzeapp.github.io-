import http.server
import json
import os
import socketserver
import sys
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlparse

from backend.auth import (
    AccountUnavailable,
    BusinessSelectionRequired,
    InvalidCredentials,
    current_session,
    load_business_state,
    login,
    logout,
    request_password_reset,
    reset_password,
    save_business_state,
)
from backend.db import DatabaseNotConfigured, is_configured
from backend.public_booking import (
    PublicBookingError,
    create_public_appointment,
    list_public_businesses,
    public_availability,
)


PORT = int(os.environ.get("PORT", 8000))
DB_FILE = "tasks_db.json"
APP_STATE_FILE = "app_state_db.json"
MAX_JSON_BYTES = 1_500_000
COOKIE_SECURE = os.environ.get(
    "KAUZE_COOKIE_SECURE", "1" if os.environ.get("RAILWAY_ENVIRONMENT") else "0"
) != "0"
COOKIE_NAME = "__Host-kauze_session" if COOKIE_SECURE else "kauze_session"


class KauzeHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "KauzeServer/1.0"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        if self.path.startswith("/app"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "base-uri 'self'; "
                "connect-src 'self'; "
                "font-src 'self' https://fonts.gstatic.com; "
                "form-action 'self'; "
                "frame-ancestors 'self'; "
                "img-src 'self' data: https:; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            )
        if self.path.startswith("/api/") or self.path.startswith("/app"):
            self.send_header("Cache-Control", "no-store")
        if COOKIE_SECURE or self.headers.get("X-Forwarded-Proto") == "https":
            self.send_header(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        super().end_headers()

    def _json_response(self, status, payload, extra_headers=None):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length inválido.") from exc
        if content_length <= 0 or content_length > MAX_JSON_BYTES:
            raise ValueError("El contenido está vacío o supera el límite permitido.")
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON inválido.") from exc

    def _cookie_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _session(self):
        return current_session(self._cookie_token())

    def _require_session(self):
        account = self._session()
        if not account:
            self._json_response(401, {"error": "authentication_required"})
            return None
        return account

    def _session_cookie(self, token, remember):
        parts = [f"{COOKIE_NAME}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if COOKIE_SECURE:
            parts.append("Secure")
        if remember:
            parts.append("Max-Age=2592000")
        return "; ".join(parts)

    def _clear_session_cookie(self):
        parts = [
            f"{COOKIE_NAME}=",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0",
        ]
        if COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        origin_host = urlparse(origin).netloc.lower()
        request_host = self.headers.get("Host", "").lower()
        configured = {
            item.strip().lower()
            for item in os.environ.get("KAUZE_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        }
        return origin_host == request_host or origin.rstrip("/").lower() in configured

    def do_OPTIONS(self):
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/health":
            self._json_response(
                200,
                {
                    "status": "ok",
                    "databaseConfigured": is_configured(),
                    "authMode": "postgresql",
                },
            )
            return

        if path == "/api/public/businesses":
            try:
                self._json_response(200, {"businesses": list_public_businesses()})
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            return

        if path.startswith("/api/public/businesses/") and path.endswith("/availability"):
            parts = [unquote(part) for part in path.strip("/").split("/")]
            if len(parts) != 5:
                self._json_response(404, {"error": "not_found"})
                return
            query = parse_qs(parsed_url.query)
            try:
                result = public_availability(
                    parts[3],
                    (query.get("date") or [""])[0],
                    (query.get("professionalId") or [None])[0],
                )
                self._json_response(200, result)
            except PublicBookingError as exc:
                self._json_response(
                    exc.status, {"error": exc.code, "message": str(exc)}
                )
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            return

        if path == "/api/auth/me":
            try:
                account = self._session()
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
                return
            if not account:
                self._json_response(401, {"error": "authentication_required"})
                return
            self._json_response(200, {"account": account})
            return

        if path == "/api/app-state":
            try:
                account = self._require_session()
                if not account:
                    return
                result = load_business_state(account["business"]["id"])
                self._json_response(200, result["state"])
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            return

        if path == "/api/tasks":
            self._json_response(200, self._read_file_json(DB_FILE, {"checked_tasks": []}))
            return

        if path == "/api/tasks-structure":
            self._json_response(
                200, self._read_file_json("tasks_structure.json", {"status": "default"})
            )
            return

        if path == "/api/notes":
            self._json_response(200, self._read_file_json("notes_db.json", {"notes": []}))
            return

        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host.startswith("admin.") and path in ("/", "/index.html"):
            self.path = "/admin/index.html"

        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if not self._origin_allowed():
            self._json_response(403, {"error": "origin_not_allowed"})
            return

        if path == "/api/public/appointments":
            try:
                data = self._read_json()
                client_key = (
                    self.headers.get("CF-Connecting-IP")
                    or self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
                    or self.client_address[0]
                )
                result = create_public_appointment(data, client_key)
                self._json_response(201 if result["created"] else 200, result)
            except PublicBookingError as exc:
                self._json_response(
                    exc.status, {"error": exc.code, "message": str(exc)}
                )
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            except ValueError as exc:
                self._json_response(400, {"error": "invalid_request", "message": str(exc)})
            return

        if path == "/api/auth/login":
            try:
                data = self._read_json()
                result = login(
                    data.get("email"),
                    data.get("password"),
                    bool(data.get("remember")),
                    data.get("localSlug"),
                    self.headers.get("User-Agent", ""),
                )
                self._json_response(
                    200,
                    {"status": "success", "account": result["account"]},
                    [("Set-Cookie", self._session_cookie(result["token"], result["remember"]))],
                )
            except BusinessSelectionRequired as exc:
                self._json_response(
                    409,
                    {
                        "error": "business_selection_required",
                        "businesses": exc.businesses,
                    },
                )
            except (InvalidCredentials, AccountUnavailable):
                self._json_response(
                    401,
                    {
                        "error": "invalid_credentials",
                        "message": "Correo o contraseña incorrectos.",
                    },
                )
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            except ValueError as exc:
                self._json_response(400, {"error": "invalid_request", "message": str(exc)})
            return

        if path == "/api/auth/logout":
            try:
                logout(self._cookie_token())
            except DatabaseNotConfigured:
                pass
            self._json_response(
                200,
                {"status": "success"},
                [("Set-Cookie", self._clear_session_cookie())],
            )
            return

        if path == "/api/auth/forgot-password":
            try:
                data = self._read_json()
                request_password_reset(data.get("email"))
            except Exception as exc:
                print(f"No fue posible enviar la recuperación: {type(exc).__name__}")
            self._json_response(
                202,
                {
                    "status": "accepted",
                    "message": "Si la cuenta existe, enviaremos un enlace de recuperación.",
                },
            )
            return

        if path == "/api/auth/reset-password":
            try:
                data = self._read_json()
                reset_password(data.get("token"), data.get("password"))
                self._json_response(
                    200,
                    {
                        "status": "success",
                        "message": "Contraseña actualizada. Ya puedes iniciar sesión.",
                    },
                )
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            except ValueError as exc:
                self._json_response(400, {"error": "invalid_reset", "message": str(exc)})
            return

        if path == "/api/app-state":
            try:
                account = self._require_session()
                if not account:
                    return
                data = self._read_json()
                result = save_business_state(
                    account["business"]["id"], account["user"]["id"], data
                )
                self._json_response(200, {"status": "success", **result})
            except DatabaseNotConfigured:
                self._json_response(503, {"error": "database_not_configured"})
            except ValueError as exc:
                self._json_response(400, {"error": "invalid_state", "message": str(exc)})
            return

        if path == "/api/tasks":
            self._save_tasks()
            return

        if path == "/api/tasks-structure":
            self._save_json_endpoint("tasks_structure.json")
            return

        if path == "/api/notes":
            self._save_json_endpoint("notes_db.json")
            return

        self._json_response(404, {"error": "not_found"})

    def _read_file_json(self, filename, fallback):
        if not os.path.exists(filename):
            return fallback
        try:
            with open(filename, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:
            print(f"Error leyendo {filename}: {exc}")
            return fallback

    def _save_json_endpoint(self, filename):
        try:
            data = self._read_json()
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            self._json_response(200, {"status": "success"})
        except ValueError as exc:
            self._json_response(400, {"status": "error", "message": str(exc)})
        except Exception as exc:
            self._json_response(500, {"status": "error", "message": str(exc)})

    def _save_tasks(self):
        try:
            data = self._read_json()
            if "checked_tasks" not in data:
                data = {"checked_tasks": data}
            with open(DB_FILE, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            self._json_response(
                200, {"status": "success", "count": len(data["checked_tasks"])}
            )
        except ValueError as exc:
            self._json_response(400, {"status": "error", "message": str(exc)})
        except Exception as exc:
            self._json_response(500, {"status": "error", "message": str(exc)})


class KauzeThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run():
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    if sys.stderr:
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print(f"Iniciando servidor KAUZE en el puerto {PORT}...")
    print(f"PostgreSQL configurado: {'sí' if is_configured() else 'no'}")
    with KauzeThreadingServer(("", PORT), KauzeHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido por el usuario.")


if __name__ == "__main__":
    run()
