#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const variablesFile = path.join(root, "terraform/images.auto.tfvars.json");
const region = "ap-northeast-1";
const names = ["agent", "mcp"];
const digestPattern = /^sha256:[0-9a-f]{64}$/;

function run(command, args, { capture = false, input } = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: { ...process.env, CHECKPOINT_DISABLE: "1", AWS_PAGER: "" },
    encoding: "utf8",
    stdio: [input === undefined ? "ignore" : "pipe", capture ? "pipe" : "inherit", "inherit"],
    input,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} ${args[0]} が失敗しました`);
  return result.stdout?.trim();
}

function readVariables() {
  let value;
  try {
    value = JSON.parse(readFileSync(variablesFile, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
  if (!value || Array.isArray(value) || typeof value !== "object") {
    throw new Error("images.auto.tfvars.jsonはJSONオブジェクトにしてください");
  }
  for (const [key, digest] of Object.entries(value)) {
    if (!names.some((name) => key === `${name}_image_digest`) || !digestPattern.test(digest)) {
      throw new Error(`images.auto.tfvars.jsonの項目が不正です: ${key}`);
    }
  }
  return value;
}

function main() {
  const [target, ...extra] = process.argv.slice(2);
  if (extra.length || ![...names, "all"].includes(target)) {
    console.log("使い方: node scripts/push-images.mjs <agent|mcp|all>");
    process.exitCode = target === "--help" && !extra.length ? 0 : 1;
    return;
  }
  const variables = readVariables();
  const selected = target === "all" ? names : [target];
  // Resolve all repositories before building or pushing either image.
  const repositories = selected.map((name) => {
    const url = run("terraform", ["-chdir=terraform", "output", "-raw", `${name}_repository_url`], {
      capture: true,
    });
    if (!/^\d{12}\.dkr\.ecr\.ap-northeast-1\.amazonaws\.com\/[a-z0-9][a-z0-9/_.-]*$/.test(url)) {
      throw new Error(`${name}のECR URLが不正です。Terraformのoutputを確認してください`);
    }
    return {
      name,
      url,
      registry: url.split("/")[0],
      repository: url.split("/").slice(1).join("/"),
    };
  });
  const commit = run("git", ["rev-parse", "--short=12", "HEAD"], { capture: true });
  // ECR uses immutable tags; a fresh suffix allows rebuilding the same commit.
  const tag = `${commit}-${Date.now()}`;
  const loggedIn = new Set();
  for (const { name, url, registry, repository } of repositories) {
    console.log(`\n[${name}] ビルド・push先: ${url}:${tag}`);
    if (!loggedIn.has(registry)) {
      const password = run("aws", ["ecr", "get-login-password", "--region", region], {
        capture: true,
      });
      run("docker", ["login", "--username", "AWS", "--password-stdin", registry], {
        input: `${password}\n`,
      });
      loggedIn.add(registry);
    }
    run("docker", ["build", "--platform", "linux/arm64", "-t", `${url}:${tag}`, name]);
    run("docker", ["push", `${url}:${tag}`]);
    const digest = run(
      "aws",
      [
        "ecr",
        "describe-images",
        "--region",
        region,
        "--repository-name",
        repository,
        "--image-ids",
        `imageTag=${tag}`,
        "--query",
        "imageDetails[0].imageDigest",
        "--output",
        "text",
      ],
      { capture: true },
    );
    if (!digestPattern.test(digest)) throw new Error(`${name}のダイジェストが不正です`);
    variables[`${name}_image_digest`] = digest;
    console.log(`[${name}] ダイジェスト: ${digest}`);
  }
  const json = `${JSON.stringify(variables, null, 2)}\n`;
  const temporary = `${variablesFile}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, json, { flag: "wx", mode: 0o600 });
    renameSync(temporary, variablesFile);
  } finally {
    rmSync(temporary, { force: true });
  }
  console.log(`\nJSON更新: ${variablesFile}\n${json}`);
  console.log("配備は未実施です。terraform -chdir=terraform plan で差分を確認してください。");
}

try {
  main();
} catch (error) {
  console.error(
    `エラー: ${error.message}\nJSONは更新していません。push済みのイメージはECRに残ります。`,
  );
  process.exitCode = 1;
}
