import { App } from "@modelcontextprotocol/ext-apps";

type Row = Record<string, string | number | null>;
const app = new App({ name: "取引ダッシュボード", version: "1.0.0" }, {}, { autoResize: true });
let rows: Row[] = [];
let groupBy = "year";
const element = (id: string) => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing element: ${id}`);
  return found;
};
const metric = element("metric") as HTMLSelectElement;
const format = (value: unknown) =>
  typeof value === "number" ? value.toLocaleString("ja-JP") : "—";

function render() {
  const chart = element("chart");
  const table = element("rows");
  chart.replaceChildren();
  table.replaceChildren();
  const maximum = Math.max(1, ...rows.map((row) => Number(row[metric.value]) || 0));
  for (const row of rows) {
    const label = String(row[groupBy] ?? "—");
    const line = document.createElement("div");
    line.className = "bar-row";
    const name = document.createElement("span");
    name.textContent = label;
    const track = document.createElement("div");
    track.className = "track";
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.width = `${(Math.max(0, Number(row[metric.value]) || 0) / maximum) * 100}%`;
    track.append(bar);
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = format(row[metric.value]);
    line.append(name, track, value);
    chart.append(line);
    const tr = document.createElement("tr");
    for (const cell of [
      label,
      ...["transaction_count", "average_price_yen", "min_price_yen", "max_price_yen"].map((key) =>
        format(row[key]),
      ),
    ]) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.append(td);
    }
    table.append(tr);
  }
  chart.setAttribute(
    "aria-label",
    `${metric.selectedOptions[0].textContent}の棒グラフ、${rows.length}区分`,
  );
}

metric.addEventListener("change", render);
app.ontoolresult = (result) => {
  const preview = result._meta?.preview as { preview_rows?: Row[]; group_by?: string } | undefined;
  if (!Array.isArray(preview?.preview_rows)) {
    element("status").textContent = "表示用の集計結果を読み取れませんでした。";
    return;
  }
  rows = preview.preview_rows;
  groupBy = preview.group_by ?? "year";
  element("subtitle").textContent = `${rows.length}区分の集計結果`;
  element("status").textContent = rows.length
    ? "合成データによる集計です。実際の市場価格ではありません。"
    : "条件に合うデータはありませんでした。";
  render();
};
app.connect().catch(() => {
  element("status").textContent = "MCP Appsへの接続に失敗しました。";
});
