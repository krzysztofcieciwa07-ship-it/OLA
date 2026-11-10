import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const EXPECTED_BRANCH = "pilot/netlify-nina-api-20261110";
const EXPECTED_API_ORIGIN = "https://ola-fastapi-api-staging.up.railway.app";
const root = process.cwd();
const publishDir = join(root, "netlify-pilot");
const requiredFiles = ["index.html", "pilot.css", "pilot.js", "pilot-manifest.json", "_headers"];
const allowedFiles = new Set([...requiredFiles, "build-proof.json"]);
const requiredRedirects = new Map([
  ["/api/health", EXPECTED_API_ORIGIN + "/health"],
  ["/api/readyz", EXPECTED_API_ORIGIN + "/readyz"],
  ["/api/nina-run", EXPECTED_API_ORIGIN + "/nina-run"],
]);
const secretPatterns = [
  /(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}/i,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /(?:SUPABASE_SERVICE_ROLE_KEY|STRIPE_SECRET_KEY|DATABASE_URL|OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|RAILWAY_TOKEN)\s*[:=]\s*["'][^"']{8,}/i,
  /(?:service_role|secret_key)\s*[:=]\s*["'][^"']{8,}/i,
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

const config = await readFile(join(root, "netlify.toml"), "utf8");
const redirectBlocks = config.split("[[redirects]]").slice(1);
if (redirectBlocks.length !== requiredRedirects.size) {
  fail("Exactly three API proxy rules are required.");
}
const observedRedirects = new Set();
for (const block of redirectBlocks) {
  const from = block.match(/^\s*from\s*=\s*"([^"]+)"/m)?.[1];
  const to = block.match(/^\s*to\s*=\s*"([^"]+)"/m)?.[1];
  const status = block.match(/^\s*status\s*=\s*(\d+)/m)?.[1];
  const force = block.match(/^\s*force\s*=\s*(true|false)/m)?.[1];
  if (!from || !to || !requiredRedirects.has(from) || requiredRedirects.get(from) !== to) {
    fail("Proxy source or target does not match the staging allowlist.");
  }
  if (status !== "200" || force !== "true") {
    fail("Each allowlisted proxy must be an explicit forced 200 rewrite.");
  }
  if (observedRedirects.has(from)) fail("Duplicate proxy route.");
  observedRedirects.add(from);
}
if (observedRedirects.size !== requiredRedirects.size) fail("One or more required proxy routes are missing.");
if (config.includes("production.up.railway.app") || /from\s*=\s*["']\/api\/\*["']/.test(config)) {
  fail("Production targets and wildcard API proxies are forbidden.");
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
  manifest.scope !== "nina-api-staging" ||
  manifest.target !== "staging" ||
  manifest.api_origin !== EXPECTED_API_ORIGIN ||
  manifest.api_routes?.join(",") !== [...requiredRedirects.keys()].join(",") ||
  manifest.secrets_included !== false ||
  manifest.production_deployment_allowed !== false
) {
  fail("Pilot manifest does not match the NINA staging-only contract.");
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
  target: "staging",
  apiOrigin: EXPECTED_API_ORIGIN,
  checks: {
    netlify_build_context: true,
    approved_pilot_branch: true,
    non_production_context: true,
    staging_only_proxy: true,
    api_routes_allowlisted: true,
    static_assets_present: true,
    manifest_contract: true,
    published_assets_secret_scan: true,
    security_headers_declared: true,
  },
};
await writeFile(join(publishDir, "build-proof.json"), JSON.stringify(proof, null, 2) + "\n", "utf8");
console.log("NETLIFY_NINA_API_PILOT_BUILD_PASS");
console.log(JSON.stringify(proof));
