import assert from "node:assert/strict";
import { test } from "node:test";
import { resultCsvFilename, resultCsvPath } from "../src/lib/result-csv.ts";

const id = "0123456789abcdef0123456789abcdef";

test("only the result CSV resource_link template is followed", () => {
  assert.equal(resultCsvFilename(`exploration://results/${id}.csv`), `result-${id}.csv`);
  for (const uri of [
    "ui://exploration/transaction-dashboard-v1.html",
    "exploration://results/../x.csv",
    `exploration://results/${id.toUpperCase()}.csv`,
    `exploration://results/${id}.csv?x=1`,
    `https://example.com/${id}.csv`,
  ]) {
    assert.equal(resultCsvFilename(uri), undefined, uri);
  }
});

test("the URI is passed as an encoded query value", () => {
  assert.equal(
    resultCsvPath(`exploration://results/${id}.csv`),
    `/api/resources?uri=exploration%3A%2F%2Fresults%2F${id}.csv`,
  );
});
