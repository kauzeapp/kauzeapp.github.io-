const assert = require("assert");
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "app", "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
if (!script) throw new Error("No se encontró el script principal.");

function extractFunction(name) {
  const start = script.indexOf(`function ${name}`);
  if (start < 0) throw new Error(`No se encontró ${name}.`);
  const openingBrace = script.indexOf("{", start);
  let depth = 0;
  for (let index = openingBrace; index < script.length; index += 1) {
    if (script[index] === "{") depth += 1;
    if (script[index] === "}") depth -= 1;
    if (depth === 0) return script.slice(start, index + 1);
  }
  throw new Error(`No se pudo extraer ${name}.`);
}

const clientFunctions = new Function(
  "servicePrice",
  `${extractFunction("normalizeStoredClient")}
   ${extractFunction("buildClientsFromAppointments")}
   return { normalizeStoredClient, buildClientsFromAppointments };`,
)(() => 15000);

const stored = [{
  id: "cli-1",
  name: "Cliente existente",
  phone: "Sin teléfono",
  lastService: "Fade",
  nextAction: "Seguimiento",
  totalBilling: 10000,
  stars: 5,
}];
const appointments = [{
  id: "appt-1",
  client: "Cliente nuevo",
  service: "Corte clásico",
  status: "Confirmada",
}];
const renderedClients = clientFunctions.buildClientsFromAppointments(appointments, stored);
assert.strictEqual(renderedClients.length, 2);
assert.strictEqual(renderedClients[1].name, "Cliente nuevo");
assert.strictEqual(renderedClients[1].phone, "Sin teléfono");
const legacyClient = clientFunctions.normalizeStoredClient(
  ["Cliente antiguo", "Barba", "Seguimiento", 9000],
  0,
);
assert.strictEqual(legacyClient.name, "Cliente antiguo");
assert.strictEqual(legacyClient.totalBilling, 9000);

const state = {type: "barberia", clients: {barberia: [...stored]}};
const syncClient = new Function(
  "state",
  "getClients",
  `${extractFunction("syncClientFromAppointment")}
   return syncClientFromAppointment;`,
)(state, () => state.clients.barberia);
syncClient(appointments[0]);
assert.strictEqual(state.clients.barberia.length, 2);
assert.strictEqual(state.clients.barberia[1].name, "Cliente nuevo");
syncClient({...appointments[0], service: "Fade", status: "Pendiente"});
assert.strictEqual(state.clients.barberia.length, 2);
assert.strictEqual(state.clients.barberia[1].lastService, "Fade");

console.log("Sincronización válida: clientes y citas aparecen inmediatamente.");
