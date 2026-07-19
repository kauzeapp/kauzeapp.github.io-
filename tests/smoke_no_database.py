import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = "8877"
BASE_URL = f"http://127.0.0.1:{PORT}"


def request(path, method="GET", payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main():
    env = os.environ.copy()
    env["PORT"] = PORT
    env.pop("DATABASE_URL", None)
    process = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=PROJECT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            try:
                status, health = request("/api/health")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("El servidor no inició.")

        assert health["databaseConfigured"] is False
        assert health["emailConfigured"] is False
        assert health["authMode"] == "postgresql"
        assert request("/api/auth/me")[0] == 401
        assert request(
            "/api/auth/login",
            method="POST",
            payload={"email": "prueba@kauze.cl", "password": "no-es-real"},
        )[0] == 503
        assert request("/api/public/businesses")[0] == 503
        assert request(
            "/api/public/appointments",
            method="POST",
            payload={"businessSlug": "demo"},
        )[0] in (400, 503)
        assert request("/api/tasks")[0] == 200
        print("Servidor válido: rutas públicas y fallo seguro sin DATABASE_URL.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
