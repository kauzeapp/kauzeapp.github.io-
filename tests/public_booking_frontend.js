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
  "requestedBusinessSlug",
  "directBusinessMode",
  "instagramUrl",
  "logoUrl",
  "businessLogoMarkup",
  "businessPublicLogo",
  "Reservas conectadas a PostgreSQL",
]) {
  if (!source.includes(required)) throw new Error(`Falta integración: ${required}`);
}

const masterplanLogo = path.join(__dirname, "..", "cliente", "assets", "masterplan-logo.jpg");
if (!fs.existsSync(masterplanLogo) || fs.statSync(masterplanLogo).size < 1000) {
  throw new Error("Falta el logo local de Masterplan.");
}

if (source.includes("También quedará visible en el panel del negocio cuando abras /app/ en este mismo navegador")) {
  throw new Error("El portal aún promete sincronización limitada al mismo navegador.");
}

console.log("Portal cliente válido: catálogo, disponibilidad y reservas usan la API pública.");
