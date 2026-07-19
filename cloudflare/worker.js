const UPSTREAM = "https://web-production-ac4ff.up.railway.app";
const ALLOWED_ORIGINS = new Set([
  "https://kauze.cl",
  "https://www.kauze.cl",
]);
const BUSINESS_SUBDOMAINS = new Map([
  ["masterplan", "masterplan"],
]);

export default {
  async fetch(request) {
    const incomingUrl = new URL(request.url);
    const hostParts = incomingUrl.hostname.toLowerCase().split(".");
    const businessSubdomain = hostParts.length === 3 && hostParts.slice(1).join(".") === "kauze.cl"
      ? hostParts[0]
      : "";

    if (businessSubdomain && !["www", "admin"].includes(businessSubdomain)) {
      const destination = new URL("https://kauze.cl/cliente/");
      destination.searchParams.set("negocio", businessSubdomain);
      return Response.redirect(destination.toString(), 302);
    }

    if (!incomingUrl.pathname.startsWith("/api/")) {
      return new Response("Not found", { status: 404 });
    }

    const origin = request.headers.get("Origin");
    if (origin && !ALLOWED_ORIGINS.has(origin)) {
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
    responseHeaders.set("Cache-Control", "no-store");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  },
};
