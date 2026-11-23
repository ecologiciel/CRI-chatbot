export interface Env {
  /** HTTPS origin of the Hostinger temporary project URL, no trailing slash. */
  ORIGIN: string;
  /** Shared only with the backend; Meta credentials never enter this Worker. */
  PROXY_SHARED_SECRET: string;
}

/** HTTPS relay for Meta's WhatsApp webhook when the temporary host is unsuitable. */
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const incoming = new URL(request.url);
    if (incoming.pathname !== "/whatsapp") return new Response("Not found", { status: 404 });
    if (request.method !== "GET" && request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const upstream = new URL(env.ORIGIN);
    if (upstream.protocol !== "https:") return new Response("Invalid relay origin", { status: 500 });
    upstream.pathname = "/api/v1/webhook/whatsapp";
    upstream.search = incoming.search;

    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.set("X-Demo-Webhook-Proxy", env.PROXY_SHARED_SECRET);
    return fetch(upstream.toString(), {
      method: request.method,
      headers,
      body: request.method === "POST" ? request.body : undefined,
      redirect: "manual",
    });
  },
};
