import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const version = (await readFile(new URL("../../.node-version", import.meta.url), "utf8")).trim();
if (!/^26\.\d+\.\d+$/.test(version)) throw new Error("Lambda build requires a pinned Node.js 26 version");
const result = spawnSync("docker", [
  "buildx", "build", "--platform", "linux/arm64", "--build-arg", `NODE_VERSION=${version}`,
  "--file", "app/Dockerfile.lambda", "--output", "type=local,dest=app/dist", "app",
], { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
