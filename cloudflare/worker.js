const UPSTREAM = "https://web-production-ac4ff.up.railway.app";

// Orígenes permitidos para hacer llamadas a la API (CORS).
// Incluye el dominio principal, www y el panel de administración.
const ALLOWED_ORIGINS = new Set([
  "https://kauze.cl",
  "https://www.kauze.cl",
  "https://admin.kauze.cl",
]);

export default {
  async fetch(request) {
    const incomingUrl = new URL(request.url);
    const hostname = incomingUrl.hostname.toLowerCase();
    const hostParts = hostname.split(".");

    // Detectar si es un subdominio de kauze.cl (ej. "masterplan.kauze.cl")
    const isSubdomain =
      hostParts.length === 3 && hostParts.slice(1).join(".") === "kauze.cl";
    const businessSubdomain = isSubdomain ? hostParts[0] : "";

    // Subdominio de negocio → redirigir a la página pública del cliente
    if (businessSubdomain && !["www", "admin"].includes(businessSubdomain)) {
      const destination = new URL("https://kauze.cl/cliente/");
      destination.searchParams.set("negocio", businessSubdomain);
      return Response.redirect(destination.toString(), 302);
    }

    // Rutas /api/* O cualquier ruta de admin.kauze.cl → proxy al servidor Railway (backend Python)
    if (incomingUrl.pathname.startsWith("/api/") || hostname === "admin.kauze.cl") {
      const origin = request.headers.get("Origin");

      // Verificar CORS solo para las llamadas a la API
      if (incomingUrl.pathname.startsWith("/api/") && origin && !ALLOWED_ORIGINS.has(origin)) {
        return Response.json({ error: "origin_not_allowed" }, { status: 403 });
      }

      const upstreamUrl = new URL(
        incomingUrl.pathname + incomingUrl.search,
        UPSTREAM,
      );
      const headers = new Headers(request.headers);
      headers.delete("host");
      headers.delete("origin");
      headers.set("x-forwarded-host", incomingUrl.host);
      headers.set("x-forwarded-proto", "https");

      // Preservar cookies de sesión (importante para la autenticación del admin)
      const init = {
        method: request.method,
        headers,
        redirect: "manual",
      };
      if (request.method !== "GET" && request.method !== "HEAD") {
        init.body = request.body;
      }

      const upstreamResponse = await fetch(new Request(upstreamUrl, init));
      const responseHeaders = new Headers(upstreamResponse.headers);
      
      // Solo desactivar caché para la API
      if (incomingUrl.pathname.startsWith("/api/")) {
        responseHeaders.set("Cache-Control", "no-store");
      }

      // Agregar cabeceras CORS para que el admin pueda leer la respuesta de la API
      if (incomingUrl.pathname.startsWith("/api/") && origin && ALLOWED_ORIGINS.has(origin)) {
        responseHeaders.set("Access-Control-Allow-Origin", origin);
        responseHeaders.set("Access-Control-Allow-Credentials", "true");
        responseHeaders.set(
          "Access-Control-Allow-Methods",
          "GET, POST, PUT, DELETE, OPTIONS",
        );
        responseHeaders.set(
          "Access-Control-Allow-Headers",
          "Content-Type, Cookie",
        );
      }

      return new Response(upstreamResponse.body, {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: responseHeaders,
      });
    }

    // Preflight OPTIONS (CORS pre-check) → responder directamente
    if (request.method === "OPTIONS") {
      const origin = request.headers.get("Origin");
      if (origin && ALLOWED_ORIGINS.has(origin)) {
        return new Response(null, {
          status: 204,
          headers: {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Cookie",
            "Access-Control-Max-Age": "86400",
          },
        });
      }
    }

    // Cualquier otra ruta que no sea /api/ ni admin.kauze.cl → 404
    return new Response("Not found", { status: 404 });
  },
};
