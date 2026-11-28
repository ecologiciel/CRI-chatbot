import test from "node:test";
import assert from "node:assert/strict";
import worker from "./src/index.ts";

const env = { ORIGIN: "https://origin.example", PROXY_SHARED_SECRET: "fixture-secret" };

test("routes authenticated institution callbacks and preserves the challenge", async () => {
  const previous = globalThis.fetch;
  let actual;
  globalThis.fetch = async (url, options) => { actual = { url, options }; return new Response("ok"); };
  try {
    const response = await worker.fetch(new Request("https://relay.example/whatsapp/tenant/onssa?hub.challenge=test"), env);
    assert.equal(response.status, 200);
    assert.equal(actual.url, "https://origin.example/api/v1/webhook/whatsapp/tenant/onssa?hub.challenge=test");
    assert.equal(actual.options.headers.get("X-Demo-Webhook-Proxy"), "fixture-secret");
    const posted = new Request("https://relay.example/whatsapp/tenant/onssa", {method: "POST", body: "fixture", headers: {"X-Demo-Webhook-Proxy": "forged"}});
    await worker.fetch(posted, env);
    assert.equal(actual.options.headers.get("X-Demo-Webhook-Proxy"), "fixture-secret");
    await worker.fetch(new Request("https://relay.example/whatsapp"), env);
    assert.equal(actual.url, "https://origin.example/api/v1/webhook/whatsapp");
  } finally { globalThis.fetch = previous; }
});

test("rejects unrecognized paths, methods and insecure origins", async () => {
  assert.equal((await worker.fetch(new Request("https://relay.example/whatsapp/tenant/ONSSA"), env)).status, 404);
  assert.equal((await worker.fetch(new Request("https://relay.example/whatsapp/tenant/onssa/extra"), env)).status, 404);
  assert.equal((await worker.fetch(new Request("https://relay.example/whatsapp/tenant/onssa", {method: "PUT"}), env)).status, 405);
  assert.equal((await worker.fetch(new Request("https://relay.example/whatsapp/tenant/onssa"), {...env, ORIGIN: "http://origin.example"})).status, 500);
});
