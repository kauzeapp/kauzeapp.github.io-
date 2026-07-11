import http.server
import socketserver
import json
import os
import sys

# Puerto para desarrollo local o provisto por plataformas como Render/Railway
PORT = int(os.environ.get("PORT", 8000))
DB_FILE = "tasks_db.json"

class KauzeAdminHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Habilitar CORS para permitir llamadas API desde entornos locales o externos
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        # API: Obtener las tareas completadas desde la base de datos JSON
        if self.path == "/api/tasks":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            data = {"checked_tasks": []}
            if os.path.exists(DB_FILE):
                try:
                    with open(DB_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception as e:
                    print(f"Error leyendo base de datos: {e}")
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return
            

            
        # Servir archivos estáticos del proyecto de forma tradicional
        super().do_GET()

    def do_POST(self):
        # API: Guardar la lista de tareas completadas
        if self.path == "/api/tasks":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                if "checked_tasks" not in data:
                    # Si envían la lista directo en lugar de un objeto con clave
                    data = {"checked_tasks": data}
                    
                with open(DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "count": len(data["checked_tasks"])}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return
            
        self.send_response(404)
        self.end_headers()

def run():
    # Ajustar codificación para evitar problemas con emojis en consolas de Windows
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
    if sys.stderr:
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
        
    print(f"Iniciando servidor de desarrollo Kauze en el puerto {PORT}...")
    print(f"Accede a la consola de administración en: http://localhost:{PORT}/admin")
    
    server_address = ('', PORT)
    # Habilitar reutilización de dirección para evitar cuelgues rápidos al reiniciar
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(server_address, KauzeAdminHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido por el usuario.")

if __name__ == "__main__":
    run()
