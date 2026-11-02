import { build } from "esbuild";
import { mkdir, rm, utimes } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const dist = new URL("../dist/", import.meta.url);
await mkdir(dist, { recursive: true });
await build({
  absWorkingDir: root, entryPoints: ["index.mjs"], outfile: "dist/index.cjs",
  bundle: true, platform: "node", target: "node26", format: "cjs", legalComments: "none",
});
// Stable ZIP timestamps keep an unchanged build from triggering a deployment.
await utimes(new URL("index.cjs", dist), new Date("2000-01-01T00:00:00Z"), new Date("2000-01-01T00:00:00Z"));
await rm(new URL("bridge.zip", dist), { force: true });
const result = spawnSync("zip", ["-Xq", "bridge.zip", "index.cjs"], { cwd: dist, stdio: "inherit", env: { ...process.env, TZ: "UTC" } });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
