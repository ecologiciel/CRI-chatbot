/* Run with `node --test tests/reply-request-storage.browser.cjs` after
 * `npx playwright install chromium`, or set CHROME_PATH to a local Chrome.
 * All data is synthetic and the HTTP server binds to localhost only. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { test } = require("node:test");
const ts = require("typescript");
const { chromium } = require("playwright");

test("request keys remain stable across tabs and fail closed", async () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/components/escalations/reply-request-storage.ts"), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(`<script>window.fixture={};(function(exports){${js}})(window.fixture)</script>`);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH && { executablePath: process.env.CHROME_PATH }) });
    const context = await browser.newContext();
    const [first, second] = await Promise.all([context.newPage(), context.newPage()]);
    const url = `http://127.0.0.1:${server.address().port}`;
    await Promise.all([first.goto(url), second.goto(url)]);
    const name = await first.evaluate(() => window.fixture.replyStorageName("tenant-a", "agent-a", "escalation-a"));
    const values = await Promise.all(Array.from({ length: 30 }, (_, i) =>
      (i % 2 ? first : second).evaluate((key) => window.fixture.acquireReplyKey(key), name)));
    assert.equal(new Set(values).size, 1);
    assert.match(values[0], /^[0-9a-f-]{36}$/);
    assert.equal(await second.evaluate((key) => window.fixture.readReplyKey(key), name), values[0]);
    assert.equal(await first.evaluate((key) => window.fixture.releaseReplyKey(key, "older-key"), name), values[0]);
    const other = await second.evaluate(() => window.fixture.acquireReplyKey(window.fixture.replyStorageName("tenant-b", "agent-a", "escalation-a")));
    assert.notEqual(other, values[0]);
    assert.equal(await first.evaluate(({ key, value }) => window.fixture.releaseReplyKey(key, value), { key: name, value: values[0] }), null);
    const replacement = await second.evaluate((key) => window.fixture.acquireReplyKey(key), name);
    assert.notEqual(replacement, values[0]);
    assert.equal(await first.evaluate(({ key, value }) => window.fixture.releaseReplyKey(key, value), { key: name, value: values[0] }), replacement);
    await first.evaluate(() => Object.defineProperty(navigator, "locks", { value: undefined, configurable: true }));
    assert.equal(await first.evaluate(async (key) => { try { await window.fixture.acquireReplyKey(key); return false; } catch { return true; } }, name), true);
    await second.evaluate(() => { Storage.prototype.setItem = () => { throw new Error("fixture denied"); }; });
    assert.equal(await second.evaluate(async () => { try { await window.fixture.acquireReplyKey("new-unavailable-key"); return false; } catch { return true; } }), true);
    await context.close();
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
