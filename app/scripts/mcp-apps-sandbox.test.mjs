import assert from "node:assert/strict";
import { test } from "node:test";
import { request } from "node:http";
import { once } from "node:events";
import { runInNewContext } from "node:vm";
import { createSandboxServer, sandboxDocument } from "./mcp-apps-sandbox.mjs";

test("sandbox HTTP response restricts networks, frames, permissions and embedding origins", async t => {
  const server = createSandboxServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}/sandbox`;
  const response = await fetch(url);
  assert.equal(response.status, 200);
  const csp = response.headers.get("content-security-policy");
  for (const directive of ["connect-src 'none'", "frame-src 'self'", "object-src 'none'", "base-uri 'none'", "form-action 'none'", "frame-ancestors http://127.0.0.1:3000 http://localhost:3000"]) {
    assert.ok(csp.includes(directive));
  }
  assert.ok(response.headers.get("permissions-policy").includes("camera=()"));
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal((await fetch(url.replace("/sandbox", "/other"))).status, 404);
  await new Promise((resolve, reject) => {
    request(url, { headers: { host: "evil.invalid" } }, response => {
      assert.equal(response.statusCode, 403);
      response.resume(); response.on("end", resolve);
    }).on("error", reject).end();
  });
});

test("proxy relays only the configured host and its own view and accepts HTML once", () => {
  const hostOrigin = "http://127.0.0.1:3000";
  const proxyOrigin = "http://127.0.0.1:3001";
  const parentMessages = [];
  const viewMessages = [];
  const parent = { postMessage: (message, origin) => parentMessages.push({ message, origin }) };
  const view = { setAttribute: () => {}, contentWindow: {
    postMessage: (message, origin) => viewMessages.push({ message, origin }),
  } };
  let receive;
  const window = { parent, addEventListener: (_type, callback) => { receive = callback; } };
  const document = { referrer: `${hostOrigin}/`, createElement: () => view, body: { append: () => {} } };
  const html = sandboxDocument([hostOrigin]);
  runInNewContext(html.match(/<script>([\s\S]*)<\/script>/)[1], {
    window, document, URL, location: { origin: proxyOrigin },
  });
  assert.equal(parentMessages[0].message.method, "ui/notifications/sandbox-proxy-ready");
  const resource = { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: "<html>test</html>" } };
  receive({ source: parent, origin: "https://evil.invalid", data: resource });
  receive({ source: {}, origin: hostOrigin, data: resource });
  assert.equal(view.srcdoc, undefined);
  receive({ source: parent, origin: hostOrigin, data: resource });
  assert.ok(view.srcdoc.endsWith(resource.params.html));
  assert.ok(view.srcdoc.includes("frame-src 'none'"));
  const original = view.srcdoc;
  receive({ source: parent, origin: hostOrigin, data: { ...resource, params: { html: "replacement" } } });
  assert.equal(view.srcdoc, original);
  const initialized = { jsonrpc: "2.0", method: "ui/notifications/initialized" };
  receive({ source: view.contentWindow, origin: "https://evil.invalid", data: initialized });
  assert.equal(parentMessages.length, 1);
  receive({ source: view.contentWindow, origin: proxyOrigin, data: initialized });
  assert.equal(parentMessages.at(-1).message, initialized);
  assert.equal(parentMessages.at(-1).origin, hostOrigin);
  const result = { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: {} };
  receive({ source: parent, origin: hostOrigin, data: result });
  assert.equal(viewMessages[0].message, result);
  assert.equal(viewMessages[0].origin, proxyOrigin);
  assert.throws(() => createSandboxServer(["https://example.com/path"]));
});
