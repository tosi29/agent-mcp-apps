import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

const agentDigest = `sha256:${"a".repeat(64)}`;
const mcpDigest = `sha256:${"b".repeat(64)}`;

function fixture(t, variables) {
  const directory = mkdtempSync(path.join(tmpdir(), "push-images-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  for (const name of ["scripts", "terraform", "bin"]) mkdirSync(path.join(directory, name));
  copyFileSync(
    new URL("./push-images.mjs", import.meta.url),
    path.join(directory, "scripts/push-images.mjs"),
  );
  const file = path.join(directory, "terraform/images.auto.tfvars.json");
  if (variables !== undefined) writeFileSync(file, JSON.stringify(variables));
  const log = path.join(directory, "commands.jsonl");
  // These executables replace every external CLI. No AWS, Docker, or Terraform is invoked.
  const mock = `#!${process.execPath}
const fs = require('node:fs');
const name = require('node:path').basename(process.argv[1]);
const args = process.argv.slice(2);
fs.appendFileSync(process.env.MOCK_LOG, JSON.stringify({name, args}) + '\\n');
if (name === 'terraform') {
  const target = args.at(-1).replace('_repository_url', '');
  console.log('123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/custom/' + target);
} else if (name === 'git') console.log('0123456789ab');
else if (name === 'aws') {
  if (args[1] === 'get-login-password') console.log('test-password-never-print');
  else console.log('sha256:' + (args.includes('custom/agent') ? 'a' : 'b').repeat(64));
} else if (name === 'docker') {
  if (args[0] === 'login') {
    if (fs.readFileSync(0, 'utf8').trim() !== 'test-password-never-print') process.exit(4);
  }
  if (args[0] === 'push' && args[1].includes('/mcp:') && process.env.FAIL_MCP) process.exit(2);
}
`;
  for (const name of ["terraform", "git", "aws", "docker"]) {
    writeFileSync(path.join(directory, "bin", name), mock, { mode: 0o755 });
  }
  return {
    file,
    calls: () =>
      existsSync(log) ? readFileSync(log, "utf8").trim().split("\n").map(JSON.parse) : [],
    run: (target, env = {}) =>
      spawnSync(process.execPath, [path.join(directory, "scripts/push-images.mjs"), target], {
        cwd: tmpdir(),
        encoding: "utf8",
        env: { ...process.env, PATH: path.join(directory, "bin"), MOCK_LOG: log, ...env },
      }),
  };
}

test("all pushes both ARM64 images and reports the saved digests without leaking the password", (t) => {
  const f = fixture(t);
  const result = f.run("all");
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(readFileSync(f.file)), {
    agent_image_digest: agentDigest,
    mcp_image_digest: mcpDigest,
  });
  for (const value of [agentDigest, mcpDigest, f.file, "JSON更新"])
    assert.ok(result.stdout.includes(value));
  assert.ok(!result.stdout.includes("test-password-never-print"));
  assert.ok(!result.stderr.includes("test-password-never-print"));
  const calls = f.calls();
  assert.equal(calls.filter((c) => c.name === "docker" && c.args[0] === "login").length, 1);
  const builds = calls.filter((c) => c.name === "docker" && c.args[0] === "build");
  assert.deepEqual(
    builds.map((c) => c.args.at(-1)),
    ["agent", "mcp"],
  );
  assert.ok(builds.every((c) => c.args.includes("linux/arm64")));
  assert.ok(!calls.some((c) => c.name === "terraform" && c.args.includes("apply")));
});

for (const target of ["agent", "mcp"]) {
  test(`${target} updates only its own digest`, (t) => {
    const other = target === "agent" ? "mcp" : "agent";
    const previous = `sha256:${"c".repeat(64)}`;
    const f = fixture(t, { [`${other}_image_digest`]: previous });
    const result = f.run(target);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(readFileSync(f.file)), {
      [`${other}_image_digest`]: previous,
      [`${target}_image_digest`]: target === "agent" ? agentDigest : mcpDigest,
    });
    assert.equal(f.calls().filter((c) => c.name === "docker" && c.args[0] === "push").length, 1);
  });
}

test("a second image failure leaves the existing JSON intact", (t) => {
  const previous = { agent_image_digest: mcpDigest, mcp_image_digest: agentDigest };
  const f = fixture(t, previous);
  const before = readFileSync(f.file, "utf8");
  const result = f.run("all", { FAIL_MCP: "1" });
  assert.equal(result.status, 1);
  assert.equal(readFileSync(f.file, "utf8"), before);
  assert.ok(result.stderr.includes("JSONは更新していません"));
  assert.ok(!result.stdout.includes("JSON更新:"));
});

test("invalid input fails before external commands", (t) => {
  const f = fixture(t, { agent_image_digest: "invalid" });
  assert.equal(f.run("all").status, 1);
  assert.equal(f.run("unknown").status, 1);
  assert.equal(f.run("--help").status, 0);
  assert.deepEqual(f.calls(), []);
});
