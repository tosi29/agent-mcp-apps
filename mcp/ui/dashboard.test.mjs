import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";

class Element {
  children = [];
  style = {};
  attributes = {};
  listeners = {};
  textContent = "";
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  setAttribute(key, value) {
    this.attributes[key] = value;
  }
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }
}

test("dashboard renders tool data, changes the metric, treats labels as text and clears empty results", async () => {
  // The SDK/bridge protocol is tested in app/. Here the adapter is replaced so
  // the view's real rendering code can be exercised without a browser or network.
  const output = await build({
    entryPoints: [new URL("./src/dashboard.ts", import.meta.url).pathname],
    bundle: true,
    write: false,
    format: "iife",
    plugins: [
      {
        name: "app-adapter",
        setup(builder) {
          builder.onResolve({ filter: /^@modelcontextprotocol\/ext-apps$/ }, () => ({
            path: "app",
            namespace: "test",
          }));
          builder.onLoad({ filter: /.*/, namespace: "test" }, () => ({
            contents: "export class App { constructor(){globalThis.app=this} async connect(){} }",
          }));
        },
      },
    ],
  });
  const elements = Object.fromEntries(
    ["chart", "rows", "metric", "subtitle", "status"].map((id) => [id, new Element()]),
  );
  elements.metric.value = "average_price_yen";
  elements.metric.selectedOptions = [{ textContent: "平均取引総額" }];
  const context = {
    document: {
      getElementById: (id) => elements[id],
      createElement: () => new Element(),
    },
  };
  runInNewContext(output.outputFiles[0].text, context);
  const data = {
    _meta: {
      preview: {
        group_by: "municipality",
        preview_rows: [
          { municipality: "<img src=x>", transaction_count: 4, average_price_yen: 100 },
          { municipality: "新宿区", transaction_count: 1, average_price_yen: 200 },
        ],
      },
    },
  };
  context.app.ontoolresult(data);
  assert.equal(elements.rows.children.length, 2);
  assert.equal(elements.rows.children[0].children[0].textContent, "<img src=x>");
  assert.equal(elements.chart.children[0].children[1].children[0].style.width, "50%");
  assert.equal(elements.chart.children[1].children[1].children[0].style.width, "100%");
  elements.metric.value = "transaction_count";
  elements.metric.selectedOptions = [{ textContent: "取引件数" }];
  elements.metric.listeners.change();
  assert.equal(elements.chart.children[0].children[1].children[0].style.width, "100%");
  assert.equal(elements.chart.children[1].children[1].children[0].style.width, "25%");
  assert.equal(elements.chart.attributes["aria-label"], "取引件数の棒グラフ、2区分");
  context.app.ontoolresult({ _meta: { preview: { preview_rows: [] } } });
  assert.equal(elements.rows.children.length, 0);
  assert.equal(elements.chart.children.length, 0);
  assert.ok(elements.status.textContent.includes("条件に合うデータはありません"));
});
