import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pilotBranch = "pilot/netlify-nina-api-20261110";
const tempRoots = [];

async function isolatedCopy() {
  const root = await mkdtemp(path.join(os.tmpdir(), "ola-netlify-nina-pilot-"));
  tempRoots.push(root);
  await cp(path.join(repoRoot, "netlify.toml"), path.join(root, "netlify.toml"));
  await cp(path.join(repoRoot, "scripts"), path.join(root, "scripts"), { recursive: true });
  await cp(path.join(repoRoot, "netlify-pilot"), path.join(root, "netlify-pilot"), { recursive: true });
  return root;
}

function runGuard(root, overrides = {}) {
  return spawnSync(
    process.execPath,
    ["scripts/netlify-pilot-check.mjs"],
    {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        NETLIFY: "true",
        BRANCH: pilotBranch,
        CONTEXT: "branch-deploy",
        ...overrides,
      },
    },
  );
}

test("approved NINA staging branch produces a build proof", async () => {
  const root = await isolatedCopy();
  const result = runGuard(root);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /NETLIFY_NINA_API_PILOT_BUILD_PASS/);

  const proof = JSON.parse(await readFile(path.join(root, "netlify-pilot", "build-proof.json"), "utf8"));
  assert.equal(proof.passed, true);
  assert.equal(proof.branch, pilotBranch);
  assert.equal(proof.target, "staging");
  assert.equal(proof.checks.staging_only_proxy, true);
  assert.equal(proof.checks.api_routes_allowlisted, true);
});

test("main/production build is blocked", async () => {
  const root = await isolatedCopy();
  const result = runGuard(root, { BRANCH: "main", CONTEXT: "production" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /NETLIFY_PILOT_BLOCKED/);
  assert.match(result.stderr, /Expected branch/);
});

test("production context on the pilot branch is blocked", async () => {
  const root = await isolatedCopy();
  const result = runGuard(root, { CONTEXT: "production" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Production and unknown deploy contexts are blocked/);
});

test("deploy-preview is accepted for the exact pilot branch", async () => {
  const root = await isolatedCopy();
  const result = runGuard(root, { CONTEXT: "deploy-preview" });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /NETLIFY_NINA_API_PILOT_BUILD_PASS/);
});

test("a changed API target is rejected", async () => {
  const root = await isolatedCopy();
  const configPath = path.join(root, "netlify.toml");
  const config = await readFile(configPath, "utf8");
  await writeFile(
    configPath,
    config.replace(
      "https://ola-fastapi-api-staging.up.railway.app/nina-run",
      "https://ola-fastapi-api-production.up.railway.app/nina-run",
    ),
    "utf8",
  );

  const result = runGuard(root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Proxy source or target does not match the staging allowlist/);
});

test("an additional wildcard proxy route is rejected", async () => {
  const root = await isolatedCopy();
  const configPath = path.join(root, "netlify.toml");
  const config = await readFile(configPath, "utf8");
  await writeFile(
    configPath,
    config + [
      "",
      "[[redirects]]",
      '  from = "/api/*"',
      '  to = "https://ola-fastapi-api-staging.up.railway.app/:splat"',
      "  status = 200",
      "  force = true",
      "",
    ].join("\n"),
    "utf8",
  );

  const result = runGuard(root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Exactly three API proxy rules are required/);
});

test("potential live credentials in a published asset are rejected", async () => {
  const root = await isolatedCopy();
  const pagePath = path.join(root, "netlify-pilot", "pilot.js");
  const page = await readFile(pagePath, "utf8");
  await writeFile(pagePath, page + '\nconst accidentalCredential = "sk_live_abcdefgh12345678";\n', "utf8");

  const result = runGuard(root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Potential credential material found/);
});

test("missing Netlify context is rejected", async () => {
  const root = await isolatedCopy();
  const result = runGuard(root, { NETLIFY: "false" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /intended to run only on Netlify/);
});

test("browser tester matches NINA's deployed policy and proof response contract", async () => {
  const script = await readFile(path.join(repoRoot, "netlify-pilot", "pilot.js"), "utf8");
  assert.match(script, /requested_tools:\s*\["shell"\]/);
  assert.match(script, /policyBody\?\.nina\?\.status === "BLOCK"/);
  assert.match(script, /policyBody\?\.provenance\?\.status === "NOT_CREATED"/);
  assert.match(script, /Array\.isArray\(policyBody\?\.replay\) && policyBody\.replay\.length === 0/);
  assert.match(script, /requested_tools:\s*\["safe_expression"\]/);
  assert.match(script, /Array\.isArray\(body\?\.replay\)/);
  assert.match(script, /body\.replay\.length === 9/);
  assert.match(script, /body\?\.decision_report\?\.human_review\?\.approved === false/);
  assert.match(script, /body\?\.status === "REVIEW"/);
  assert.match(script, /"X-API-Key": apiKey/);
  assert.match(script, /ui\.key\.value = ""/);
  assert.doesNotMatch(script, /localStorage|sessionStorage/);
});

test.after(async () => {
  await Promise.all(tempRoots.map((root) => rm(root, { recursive: true, force: true })));
});
