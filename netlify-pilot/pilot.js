const expectedBranch = "pilot/netlify-static-20261110";
const overall = document.querySelector("#overall");
const summary = document.querySelector("#summary");
const duration = document.querySelector("#duration");
const button = document.querySelector("#rerun");

function setCheck(name, passed) {
  const node = document.querySelector(`[data-check="${name}"]`);
  node.textContent = passed ? "PASS" : "FAIL";
  node.classList.toggle("pass", passed);
  node.classList.toggle("fail", !passed);
}

async function runChecks() {
  button.disabled = true;
  overall.textContent = "SPRAWDZANIE";
  overall.className = "status pending";
  summary.textContent = "Sprawdzam zasoby i nagłówki tej konkretnej wersji pilota.";
  const start = performance.now();
  let manifestOk = false;
  let buildOk = false;
  let headersOk = false;

  try {
    const response = await fetch("/pilot-manifest.json", { cache: "no-store" });
    const manifest = await response.json();
    manifestOk = response.ok && manifest.schema === "ola.netlify.pilot.v1" &&
      manifest.scope === "static-hosting-only" && manifest.backend_connected === false &&
      manifest.secrets_included === false && manifest.production_deployment_allowed === false;
  } catch {
    manifestOk = false;
  }

  try {
    const response = await fetch("/build-proof.json", { cache: "no-store" });
    const proof = await response.json();
    buildOk = response.ok && proof.schema === "ola.netlify.pilot-build-proof.v1" &&
      proof.passed === true && proof.branch === expectedBranch &&
      ["branch-deploy", "deploy-preview"].includes(proof.context);
  } catch {
    buildOk = false;
  }

  try {
    const response = await fetch("/", { method: "HEAD", cache: "no-store" });
    const robots = response.headers.get("x-robots-tag") || "";
    const csp = response.headers.get("content-security-policy") || "";
    headersOk = response.ok &&
      (response.headers.get("x-content-type-options") || "").toLowerCase() === "nosniff" &&
      (response.headers.get("x-frame-options") || "").toUpperCase() === "DENY" &&
      robots.toLowerCase().includes("noindex") &&
      csp.includes("frame-ancestors 'none'");
  } catch {
    headersOk = false;
  }

  setCheck("manifest", manifestOk);
  setCheck("build", buildOk);
  setCheck("headers", headersOk);
  const passed = manifestOk && buildOk && headersOk;
  overall.textContent = passed ? "PASS" : "FAIL";
  overall.className = `status ${passed ? "pass" : "fail"}`;
  summary.textContent = passed
    ? "Pilot działa. Potwierdzono wyłącznie statyczne dostarczanie zasobów i zabezpieczenia odpowiedzi."
    : "Pilot nie przeszedł wszystkich kontroli. Nie traktuj tego wdrożenia jako gotowego.";
  duration.textContent = `${Math.round(performance.now() - start)} ms`;
  button.disabled = false;
}

button.addEventListener("click", runChecks);
runChecks();
