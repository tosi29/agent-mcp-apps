import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { resultCsvFilename, resultCsvPath } from "../src/lib/result-csv.ts";

const id = "0123456789abcdef0123456789abcdef";
const uri = `exploration://results/${id}.csv`;

describe("only the result CSV resource_link is followed", () => {
  test("result CSV URI", () => assert.equal(resultCsvFilename(uri), `result-${id}.csv`));
  const rejected = {
    "MCP App resource": "ui://exploration/transaction-dashboard-v1.html",
    "path traversal": "exploration://results/../x.csv",
    "uppercase id": `exploration://results/${id.toUpperCase()}.csv`,
    "query string": `${uri}?x=1`,
    "web URL": `https://example.com/${id}.csv`,
  };
  for (const [name, value] of Object.entries(rejected)) {
    test(`${name} is rejected`, () => assert.equal(resultCsvFilename(value), undefined));
  }
});

test("the URI is passed as an encoded query value", () => {
  assert.equal(resultCsvPath(uri), `/api/resources?uri=exploration%3A%2F%2Fresults%2F${id}.csv`);
});
