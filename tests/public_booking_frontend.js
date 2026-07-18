const fs = require("fs");
const path = require("path");

const htmlPath = path.join(__dirname, "..", "cliente", "index.html");
const source = fs.readFileSync(htmlPath, "utf8");
const scripts = Array.from(source.matchAll(/<script>([\s\S]*?)<\/script>/g));

if (!scripts.length) throw new Error("No se encontró el script del portal cliente.");
for (const script of scripts) new Function(script[1]);

for (const required of [
  "/api/public/businesses",
  "/api/public/appointments",
  "createOnlineAppointment",
  "refreshAvailability",
  "Reservas conectadas a PostgreSQL",
]) {
  if (!source.includes(required)) throw new Error(`Falta integración: ${required}`);
}

if (source.includes("También quedará visible en el panel del negocio cuando abras /app/ en este mismo navegador")) {
  throw new Error("El portal aún promete sincronización limitada al mismo navegador.");
}

console.log("Portal cliente válido: catálogo, disponibilidad y reservas usan la API pública.");
