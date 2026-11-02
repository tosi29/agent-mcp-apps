import { existsSync } from "node:fs";
import { cp } from "node:fs/promises";

await cp(".next/static", ".next/standalone/.next/static", { recursive: true });
if (existsSync("public")) await cp("public", ".next/standalone/public", { recursive: true });
