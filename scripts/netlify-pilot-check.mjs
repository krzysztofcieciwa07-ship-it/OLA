import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const EXPECTED_BRANCH = "pilot/netlify-static-20261110";
const root = process.cwd();
const publishDir = join(root, "netlify-pilot");
const requiredFiles = ["index.html", "pilot.css", "pilot.js", "pilot-manifest.json", "_headers"];
const allowedFiles = new Set([...requiredFiles, "build-proof.json"]);
const secretPatterns = [
  /(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}/i,
  /SUPABASE_SERVICE_ROLE_KEY/i,
  /SUPABASE_ANON_KEY/i,
  /SUPABASE_URL/i,
  /service_role/i,
  /STRIPE_SECRET_KEY/i,
  /DATABASE_URL/i,
  /OPENAI_API_KEY/i,
  /ANTHROPIC_API_KEY/i,
  /GITHUB_TOKEN/i,
];

function fail(message) {
  console.error("NETLIFY_PILOT_BLOCKED: " + message);
  process.exit(1);
}

const branch = process.env.BRANCH ?? "";
const context = process.env.CONTEXT ?? "";
if (process.env.NETLIFY !== "true") fail("This build is intended to run only on Netlify.");
if (branch !== EXPECTED_BRANCH) fail("Expected branch " + EXPECTED_BRANCH + "; received " + (branch || "<empty>") + ".");
if (!new Set(["branch-deploy", "deploy-preview"]).has(context)) {
  fail("Production and unknown deploy contexts are blocked; received " + (context || "<empty>") + ".");
}

const entries = await readdir(publishDir, { withFileTypes: true });
if (entries.some((entry) => !entry.isFile() || !allowedFiles.has(entry.name))) {
  fail("The published directory contains an unapproved file or directory.");
}
for (const name of requiredFiles) {
  if (!entries.some((entry) => entry.name === name && entry.isFile())) fail("Missing required static asset: " + name);
}

const assetContents = new Map();
for (const name of requiredFiles) {
  assetContents.set(name, await readFile(join(publishDir, name), "utf8"));
}
for (const [name, contents] of assetContents) {
  if (secretPatterns.some((pattern) => pattern.test(contents))) fail("Potential credential material found in published asset: " + name);
}

let manifest;
try {
  manifest = JSON.parse(assetContents.get("pilot-manifest.json"));
} catch {
  fail("pilot-manifest.json is not valid JSON.");
}
if (
  manifest.schema !== "ola.netlify.pilot.v1" ||
  manifest.scope !== "static-hosting-only" ||
  manifest.backend_connected !== false ||
  manifest.secrets_included !== false ||
  manifest.production_deployment_allowed !== false
) {
  fail("Pilot manifest does not match the isolated static-only contract.");
}

const headers = assetContents.get("_headers");
for (const requiredHeader of [
  "X-Content-Type-Options: nosniff",
  "X-Frame-Options: DENY",
  "Referrer-Policy: no-referrer",
  "X-Robots-Tag: noindex, nofollow, noarchive",
  "Content-Security-Policy: default-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
  "object-src 'none'",
]) {
  if (!headers.includes(requiredHeader)) fail("Missing required security header or directive: " + requiredHeader);
}

const proof = {
  schema: "ola.netlify.pilot-build-proof.v1",
  passed: true,
  branch,
  context,
  checks: {
    netlify_build_context: true,
    approved_pilot_branch: true,
    non_production_context: true,
    static_assets_present: true,
    manifest_contract: true,
    published_assets_secret_scan: true,
    security_headers_declared: true,
  },
};
await writeFile(join(publishDir, "build-proof.json"), JSON.stringify(proof, null, 2) + "\n", "utf8");
console.log("NETLIFY_PILOT_BUILD_PASS");
console.log(JSON.stringify(proof));
