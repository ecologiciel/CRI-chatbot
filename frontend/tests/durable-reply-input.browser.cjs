/* Component/network test on localhost with a synthetic API. */
const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");
const { test } = require("node:test");
const esbuild = require("esbuild");
const { chromium } = require("playwright");

const entry = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DurableReplyInput } from './src/components/escalations/durable-reply-input';
window.fixture = { tenant: 'tenant-a', actor: 'actor-a', token: 'token-a' };
const client = new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}><DurableReplyInput escalationId="escalation-a" maySend={true}/></QueryClientProvider>);
`;
const mocks = {
  api: `
export class ApiError extends Error { constructor(status) { super('fixture error'); this.status = status; } }
async function request(path, options) { const response = await fetch('/fixture'+path, options); if (!response.ok) throw new ApiError(response.status); return response.json(); }
export const api = {getTenantId:()=>window.fixture.tenant,getAccessToken:()=>window.fixture.token,
  get:(path)=>request(path),post:(path,body)=>request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})};
`,
  auth: `import {api} from 'fixture-api'; export function useApiClient(){return api} export function useAuth(){return {admin:{id:window.fixture.actor}}}`,
  button: `import React from 'react'; export function Button({children,variant,size,...props}){return <button {...props}>{children}</button>}`,
  textarea: `import React from 'react'; export function Textarea(props){return <textarea {...props}/>}`,
  legacy: `import React from 'react'; export function ResponseInput(){return <div>legacy</div>}`,
};

async function bundle() {
  const alias = {
    "@/hooks/use-auth": "auth", "@/lib/api-client": "api", "fixture-api": "api",
    "@/components/ui/button": "button", "@/components/ui/textarea": "textarea", "./response-input": "legacy",
  };
  const result = await esbuild.build({
    stdin: { contents: entry, resolveDir: path.join(__dirname, ".."), loader: "tsx" },
    bundle: true, write: false, platform: "browser", jsx: "automatic",
    plugins: [{ name: "fixture-mocks", setup(build) {
      build.onResolve({ filter: /^(fixture-api|@\/hooks\/use-auth|@\/lib\/api-client|@\/components\/ui\/(button|textarea)|\.\/response-input)$/ },
        (args) => ({ path: alias[args.path], namespace: "fixture" }));
      build.onLoad({ filter: /.*/, namespace: "fixture" }, (args) => ({ contents: mocks[args.path], loader: "tsx", resolveDir: path.join(__dirname, "..") }));
    }}],
  });
  return result.outputFiles[0].text;
}

test("lost responses preserve request identity and session changes prevent sending", async () => {
  const js = await bundle();
  const records = new Map();
  const attempts = [];
  let serverPosts = 0;
  let failure = "after";
  const server = http.createServer(async (req, res) => {
    if (!req.url.startsWith("/fixture/")) {
      res.writeHead(200, { "Content-Type": "text/html" });
      return res.end(`<div id="root"></div><script>${js.replaceAll("</script", "<\\/script")}</script>`);
    }
    if (req.method === "POST") {
      serverPosts += 1;
      let raw = ""; for await (const part of req) raw += part;
      const body = JSON.parse(raw);
      records.set(body.request_key, { id: "fixture", state: "pending", outcome_code: null });
      res.writeHead(202, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ id: "fixture", state: "pending", created: true }));
    }
    const key = req.url.split("/").at(-1);
    const record = records.get(key);
    res.writeHead(record ? 200 : 404, { "Content-Type": "application/json" });
    return res.end(JSON.stringify(record || {}));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH && { executablePath: process.env.CHROME_PATH }) });
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.route("**/fixture/escalations/*/reply-requests", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts.push(route.request().postDataJSON());
      if (failure === "after") { failure = ""; await route.fetch(); return route.abort("failed"); }
      if (failure === "before") { failure = ""; return route.abort("failed"); }
      return route.continue();
    });
    const url = `http://127.0.0.1:${server.address().port}`;
    await page.goto(url);
    await page.locator("textarea:enabled").fill("première réponse synthétique");
    await page.getByRole("button", { name: "Enregistrer la réponse" }).click();
    try { await page.getByText("Résultat non confirmé", { exact: false }).waitFor({ timeout: 7000 }); }
    catch (error) { throw new Error(`First failure not displayed; attempts=${attempts.length}; view=${await page.locator("body").innerText()}`, { cause: error }); }
    assert.equal(attempts.length, 1);
    const key = attempts[0].request_key;
    assert.equal(await page.evaluate(() => Object.values(localStorage).some((value) => value.includes("première réponse"))), false);
    await page.reload();
    await page.getByText("État : pending", { exact: false }).waitFor();
    assert.equal(await page.locator("textarea").isDisabled(), true);
    assert.equal(attempts.length, 1);
    records.get(key).state = "accepted";
    await page.getByRole("button", { name: "J’ai pris connaissance du résultat" }).waitFor({ timeout: 12000 });
    await page.getByRole("button", { name: "J’ai pris connaissance du résultat" }).click();
    await page.locator("textarea:enabled").waitFor();

    failure = "before";
    await page.locator("textarea").fill("deuxième réponse synthétique");
    await page.getByRole("button", { name: "Enregistrer la réponse" }).click();
    await page.getByRole("button", { name: "Réessayer avec la même référence" }).waitFor();
    const secondKey = attempts[1].request_key;
    await page.getByRole("button", { name: "Réessayer avec la même référence" }).click();
    await page.getByText("Demande enregistrée", { exact: false }).waitFor();
    assert.equal(attempts[2].request_key, secondKey);
    assert.equal(attempts[2].message, attempts[1].message);

    await context.close();
    const session = await browser.newContext();
    const other = await session.newPage();
    await other.goto(url);
    await other.locator("textarea:enabled").fill("troisième réponse synthétique");
    await other.evaluate(async () => {
      window.lockReady = new Promise((resolve) => { window.lockAcquired = resolve; });
      window.lockHold = new Promise((resolve) => { window.releaseLock = resolve; });
      void navigator.locks.request("agent-reply:v1:tenant-a:actor-a:escalation-a", async () => { window.lockAcquired(); await window.lockHold; });
      await window.lockReady;
    });
    await other.getByRole("button", { name: "Enregistrer la réponse" }).click();
    await other.evaluate(() => { window.fixture.token = "other-session"; window.releaseLock(); });
    await other.getByText("La session a changé", { exact: false }).waitFor();
    assert.equal(attempts.length, 3);
    assert.equal(serverPosts, 2);
    await session.close();
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
