import { spawnSync } from "node:child_process";
import { chmod, cp, mkdir, readdir, rm, utimes } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (
  process.platform !== "linux" ||
  process.arch !== "arm64" ||
  !process.versions.node.startsWith("26.")
) {
  throw new Error("Lambda ZIP must be built with Dockerfile.lambda on Linux ARM64 / Node.js 26");
}
const root = fileURLToPath(new URL("../", import.meta.url));
const staging = path.join(root, "dist/staging");
await rm(staging, { recursive: true, force: true });
await mkdir(staging, { recursive: true });
await cp(path.join(root, ".next/standalone"), staging, { recursive: true, dereference: true });
await cp(path.join(root, "lambda/run.sh"), path.join(staging, "run.sh"));
await chmod(path.join(staging, "run.sh"), 0o755);
const files = [];
async function visit(directory) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, item.name);
    if (item.name.startsWith(".env")) throw new Error("Environment files must not enter the ZIP");
    if (item.isDirectory()) await visit(absolute);
    else {
      if (item.isSymbolicLink()) throw new Error(`Unexpected symlink: ${absolute}`);
      await utimes(absolute, new Date("2000-01-01T00:00:00Z"), new Date("2000-01-01T00:00:00Z"));
      files.push(path.relative(staging, absolute));
    }
  }
}
await visit(staging);
await rm(path.join(root, "dist/web.zip"), { force: true });
const result = spawnSync("zip", ["-Xq", "../web.zip", "-@"], {
  cwd: staging,
  input: files.sort().join("\n") + "\n",
  stdio: ["pipe", "inherit", "inherit"],
  env: { ...process.env, TZ: "UTC" },
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
await rm(staging, { recursive: true, force: true });
