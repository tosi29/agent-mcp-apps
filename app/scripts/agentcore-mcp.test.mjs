import assert from "node:assert/strict";
import { test } from "node:test";
import { mcpRuntimeFetch, validMcpRuntimeArn } from "../src/lib/agentcore-mcp.ts";

const ARN = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/mcp-AbCdEf1234";
const body = (text) => ({ transformToString: async () => text });

test("a POST is sent through InvokeAgentRuntime with the MCP session and version", async () => {
  const calls = [];
  const fetch = mcpRuntimeFetch(ARN, async (input) => {
    calls.push(input);
    return {
      statusCode: 200,
      contentType: "application/json",
      mcpSessionId: "returned-session",
      response: body('{"jsonrpc":"2.0","id":1,"result":{}}'),
    };
  });
  const first = await fetch("http://agentcore.internal/mcp", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: '{"jsonrpc":"2.0","id":1,"method":"initialize"}',
  });
  assert.equal(first.status, 200);
  assert.equal(first.headers.get("mcp-session-id"), "returned-session");
  assert.deepEqual(await first.json(), { jsonrpc: "2.0", id: 1, result: {} });
  assert.equal(calls[0].agentRuntimeArn, ARN);
  assert.equal(calls[0].qualifier, "DEFAULT");
  // AgentCore routes by MCP session, so a new connection gets a fresh one.
  assert.match(calls[0].mcpSessionId, /^[0-9a-f-]{36}$/);
  assert.equal(
    new TextDecoder().decode(calls[0].payload),
    '{"jsonrpc":"2.0","id":1,"method":"initialize"}',
  );

  await fetch("http://agentcore.internal/mcp", {
    method: "POST",
    headers: { "mcp-session-id": "returned-session", "mcp-protocol-version": "2025-11-25" },
    body: "{}",
  });
  assert.equal(calls[1].mcpSessionId, "returned-session");
  assert.equal(calls[1].mcpProtocolVersion, "2025-11-25");
});

test("notifications get an empty 202, and GET/DELETE never reach AgentCore", async () => {
  let called = 0;
  const fetch = mcpRuntimeFetch(ARN, async () => {
    called += 1;
    return { statusCode: 202, contentType: undefined, response: body("") };
  });
  const accepted = await fetch("x", { method: "POST", body: "{}" });
  assert.equal(accepted.status, 202);
  assert.equal(await accepted.text(), "");
  assert.equal((await fetch("x", { method: "GET" })).status, 405);
  assert.equal((await fetch("x", { method: "DELETE" })).status, 405);
  assert.equal(called, 1);
});

test("AWS errors keep their HTTP status without leaking details", async () => {
  const failing = (error) => mcpRuntimeFetch(ARN, async () => Promise.reject(error));
  const notFound = Object.assign(new Error("secret detail"), {
    $metadata: { httpStatusCode: 404 },
  });
  const response = await failing(notFound)("x", { method: "POST", body: "{}" });
  assert.equal(response.status, 404);
  assert.equal(await response.text(), "");
  assert.equal(
    (await failing(new Error("network"))("x", { method: "POST", body: "{}" })).status,
    502,
  );
});

test("only a Tokyo AgentCore Runtime ARN is accepted", () => {
  assert.equal(validMcpRuntimeArn(ARN), ARN);
  for (const arn of [
    ARN.replace("ap-northeast-1", "us-east-1"),
    `${ARN}?x=1`,
    "https://example.com/mcp",
    "",
  ]) {
    assert.throws(() => validMcpRuntimeArn(arn), arn);
  }
});
