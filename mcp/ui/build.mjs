import { mkdir, readFile, writeFile } from "node:fs/promises";
import { Script } from "node:vm";
import { build } from "esbuild";

const result = await build({
  entryPoints: [new URL("./src/dashboard.ts", import.meta.url).pathname],
  bundle: true,
  minify: true,
  write: false,
  format: "iife",
  target: "es2022",
});
const template = await readFile(new URL("./src/dashboard.html", import.meta.url), "utf8");
const script = result.outputFiles[0].text.replaceAll("</script", "<\\/script");
const directory = new URL("../src/exploration_mcp/ui/", import.meta.url);
await mkdir(directory, { recursive: true });
const html = template.replace("/* APP_SCRIPT */", () => script);
// Check the actual embedded script, including replacement/HTML escaping.
new Script(html.match(/<script>([\s\S]*)<\/script>/)[1]);
await writeFile(new URL("dashboard.html", directory), html);
console.log("MCP App生成: mcp/src/exploration_mcp/ui/dashboard.html");
