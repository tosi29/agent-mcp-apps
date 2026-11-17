import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { mcpRuntimeFetch, validMcpRuntimeArn } from "../src/lib/agentcore-mcp.ts";

const ARN = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/mcp-AbCdEf1234";
const output = (fields) => ({
  statusCode: 200,
  ...fields,
  response: { transformToString: async () => fields.text ?? "" },
});
const post = (headers = {}) => ({ method: "POST", headers, body: '{"jsonrpc":"2.0"}' });

describe("request sent to InvokeAgentRuntime", () => {
  const cases = [
    {
      name: "first request opens a fresh MCP session",
      headers: { "content-type": "application/json" },
      expected: { mcpSessionId: /^[0-9a-f-]{36}$/, contentType: /^application\/json$/ },
    },
    {
      name: "later requests keep the session and protocol version",
      headers: { "mcp-session-id": "s-1", "mcp-protocol-version": "2025-11-25" },
      expected: { mcpSessionId: /^s-1$/, mcpProtocolVersion: /^2025-11-25$/ },
    },
  ];
  for (const { name, headers, expected } of cases) {
    test(name, async () => {
      let sent;
      await mcpRuntimeFetch(ARN, async (input) => {
        sent = input;
        return output({});
      })("ignored", post(headers));
      assert.equal(sent.agentRuntimeArn, ARN);
      assert.equal(sent.qualifier, "DEFAULT");
      assert.equal(new TextDecoder().decode(sent.payload), '{"jsonrpc":"2.0"}');
      for (const [key, pattern] of Object.entries(expected)) assert.match(sent[key], pattern, key);
    });
  }
});

describe("response returned to the MCP client", () => {
  const cases = [
    {
      name: "JSON-RPC reply is passed through",
      upstream: () =>
        output({ contentType: "application/json", mcpSessionId: "s-2", text: '{"id":1}' }),
      expected: { status: 200, body: '{"id":1}' },
    },
    {
      name: "AWS error keeps its status, not its message",
      upstream: () =>
        Promise.reject(Object.assign(new Error("secret"), { $metadata: { httpStatusCode: 404 } })),
      expected: { status: 404, body: "" },
    },
    {
      name: "network failure becomes 502",
      upstream: () => Promise.reject(new Error("network")),
      expected: { status: 502, body: "" },
    },
  ];
  for (const { name, upstream, expected } of cases) {
    test(name, async () => {
      const response = await mcpRuntimeFetch(ARN, upstream)("ignored", post());
      assert.equal(response.status, expected.status);
      assert.equal(await response.text(), expected.body);
    });
  }
  test("the session AgentCore returns is passed back to the client", async () => {
    const fetch = mcpRuntimeFetch(ARN, async () => output({ mcpSessionId: "s-2" }));
    assert.equal((await fetch("ignored", post())).headers.get("mcp-session-id"), "s-2");
  });
});

test("the SSE stream request (GET) never reaches AgentCore", async () => {
  const fetch = mcpRuntimeFetch(ARN, () => assert.fail("AgentCore was called"));
  assert.equal((await fetch("ignored", { method: "GET" })).status, 405);
});

describe("MCP Runtime ARN", () => {
  test("Tokyo runtime is accepted", () => assert.equal(validMcpRuntimeArn(ARN), ARN));
  const rejected = {
    "other region": ARN.replace("ap-northeast-1", "us-east-1"),
    "trailing text": `${ARN}?x=1`,
  };
  for (const [name, arn] of Object.entries(rejected)) {
    test(`${name} is rejected`, () => assert.throws(() => validMcpRuntimeArn(arn)));
  }
});
