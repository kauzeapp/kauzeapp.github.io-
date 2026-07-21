const fs = require("fs");
const path = require("path");

const htmlPath = path.join(__dirname, "..", "app", "index.html");
const source = fs.readFileSync(htmlPath, "utf8");
const script = source.match(/<script>([\s\S]*?)<\/script>/);

if (!script) throw new Error("No se encontró el script principal.");
new Function(script[1]);

const ids = Array.from(source.matchAll(/id="([^"]+)"/g), match => match[1]);
const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
if (duplicates.length) {
  throw new Error(`IDs duplicados: ${Array.from(new Set(duplicates)).join(", ")}`);
}

for (const forbidden of ["LOGIN_PASSWORD", "LOGIN_EMAIL", "kauzeAppV3RememberedAuth"] ) {
  if (source.includes(forbidden)) throw new Error(`Referencia insegura encontrada: ${forbidden}`);
}

for (const required of [
  "/api/account/profile-image",
  "settingsUserPhotoFile",
  "saveUserPhoto",
  "proPhotoFile",
  "resizeProfilePhoto",
  "proCommissionPreset",
  "proCommissionCustomType",
  "commissionFixedAmount",
  "professionalCommissionLabel",
  "startDayBtn",
  "businessStatus:'CERRADO'",
  "Küyen te acompaña",
  "id=\"businessTypeSwitch\" disabled",
  "id=\"settingsType\" disabled",
  "view-integraciones",
  "directBookingLink",
  "integrationInstagramUrl",
  "integrationPublicWhatsapp",
  "searchPreviewLogo",
  "businessPublicUrl",
]) {
  if (!source.includes(required)) throw new Error(`Falta personalización de perfil: ${required}`);
}

console.log(`Frontend válido: ${ids.length} IDs únicos y JavaScript correcto.`);
