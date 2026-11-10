const ui = {
  infraOverall: document.querySelector("#infra-overall"),
  infraSummary: document.querySelector("#infra-summary"),
  health: document.querySelector("#health-check"),
  ready: document.querySelector("#ready-check"),
  auth: document.querySelector("#auth-check"),
  infraTime: document.querySelector("#infra-time"),
  refresh: document.querySelector("#refresh"),
  runOverall: document.querySelector("#run-overall"),
  key: document.querySelector("#api-key"),
  confirm: document.querySelector("#staging-confirm"),
  form: document.querySelector("#run-form"),
  runButton: document.querySelector("#run-nina"),
  clear: document.querySelector("#clear-key"),
  result: document.querySelector("#run-result"),
  runTime: document.querySelector("#run-time"),
  policy: document.querySelector("#policy-check"),
  nina: document.querySelector("#nina-check"),
  igor: document.querySelector("#igor-check"),
  proof: document.querySelector("#proof-check"),
  gate: document.querySelector("#gate-check"),
  final: document.querySelector("#final-check"),
};

function mark(node, state) {
  node.textContent = state ? "PASS" : "FAIL";
  node.classList.toggle("pass", state);
  node.classList.toggle("fail", !state);
}

function setOverall(node, passed, pending = false) {
  node.textContent = pending ? "SPRAWDZANIE" : passed ? "PASS" : "FAIL";
  node.className = "status " + (pending ? "pending" : passed ? "pass" : "fail");
}

function showResult(lines) {
  ui.result.replaceChildren();
  for (const line of lines) {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    ui.result.appendChild(paragraph);
  }
}

async function requestJson(path, options = {}, timeoutMs = 22000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    const raw = await response.text();
    let body = null;
    try { body = raw ? JSON.parse(raw) : null; } catch { body = { message: "Invalid JSON response" }; }
    return { response, body };
  } finally {
    clearTimeout(timer);
  }
}

async function checkInfrastructure() {
  ui.refresh.disabled = true;
  setOverall(ui.infraOverall, false, true);
  ui.infraSummary.textContent = "Sprawdzam liveness, core readiness i odmowę niezautoryzowanego wywołania.";
  const start = performance.now();
  let healthOk = false;
  let readyOk = false;
  let authOk = false;

  try {
    const { response, body } = await requestJson("/api/health", { method: "GET" }, 12000);
    healthOk = response.status === 200 && body?.status === "ok";
  } catch { healthOk = false; }

  try {
    const { response, body } = await requestJson("/api/readyz", { method: "GET" }, 12000);
    readyOk = response.status === 200 && body?.core_status === "READY" &&
      body?.scope === "local_core_only" && body?.system_acceptance === "NOT_VERIFIED";
  } catch { readyOk = false; }

  try {
    const { response } = await requestJson("/api/nina-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: "Unauthenticated NINA API probe", requested_tools: ["safe_expression"] }),
    }, 12000);
    authOk = response.status === 401;
  } catch { authOk = false; }

  mark(ui.health, healthOk);
  mark(ui.ready, readyOk);
  mark(ui.auth, authOk);
  const passed = healthOk && readyOk && authOk;
  setOverall(ui.infraOverall, passed);
  ui.infraSummary.textContent = passed
    ? "API staging odpowiada. /readyz potwierdza lokalną gotowość rdzenia, a /nina-run odrzuca brak klucza."
    : "Co najmniej jedna kontrola nie przeszła. Sprawdź status staging i logi Railway.";
  ui.infraTime.textContent = Math.round(performance.now() - start) + " ms";
  ui.refresh.disabled = false;
  return passed;
}

function resetRunChecks() {
  for (const node of [ui.policy, ui.nina, ui.igor, ui.proof, ui.gate, ui.final]) {
    node.textContent = "NIEURUCHOMIONE";
    node.classList.remove("pass", "fail");
  }
}

ui.key.addEventListener("input", () => {
  ui.runButton.disabled = !(ui.key.value.trim().length >= 12 && ui.confirm.checked);
});
ui.confirm.addEventListener("change", () => {
  ui.runButton.disabled = !(ui.key.value.trim().length >= 12 && ui.confirm.checked);
});
ui.clear.addEventListener("click", () => {
  ui.key.value = "";
  ui.confirm.checked = false;
  ui.runButton.disabled = true;
  showResult(["Klucz wyczyszczony z formularza."]);
});
ui.refresh.addEventListener("click", checkInfrastructure);

ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let apiKey = ui.key.value.trim();
  if (!apiKey || !ui.confirm.checked || ui.runButton.disabled) return;

  // Keep the key only for this request sequence; never write it to browser storage or the DOM.
  ui.key.value = "";
  ui.confirm.checked = false;
  ui.runButton.disabled = true;
  ui.clear.disabled = true;
  ui.result.textContent = "Najpierw sprawdzam blokadę narzędzi spoza allowlisty…";
  ui.runTime.textContent = "";
  resetRunChecks();
  setOverall(ui.runOverall, false, true);
  const start = performance.now();

  try {
    // The real NINA endpoint returns a nested BLOCK decision before runtime or evidence writes.
    const policyProbe = await requestJson("/api/nina-run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify({
        task: "This probe must be blocked before execution.",
        requested_tools: ["shell"],
      }),
    }, 12000);

    const policyBody = policyProbe.body;
    const policyReason = policyBody?.nina?.reason ?? "";
    const policyOk = policyProbe.response.status === 200 &&
      policyBody?.status === "BLOCK" &&
      policyBody?.nina?.status === "BLOCK" &&
      policyReason.includes("unknown tool: shell") &&
      policyBody?.igor?.status === "UNKNOWN" &&
      policyBody?.provenance?.status === "NOT_CREATED" &&
      Array.isArray(policyBody?.replay) && policyBody.replay.length === 0 &&
      policyBody?.human_gate?.status === "BLOCK" &&
      typeof policyBody?.run_id === "undefined";
    mark(ui.policy, policyOk);

    if (!policyOk) {
      setOverall(ui.runOverall, false);
      showResult([
        "FAIL: NINA nie potwierdziła blokady niezarejestrowanego narzędzia.",
        "Bezpieczny przebieg nie został uruchomiony.",
        "HTTP " + policyProbe.response.status,
      ]);
      return;
    }

    ui.result.textContent = "Nieznane narzędzie zablokowane. Uruchamiam ograniczony test safe_expression…";
    const run = await requestJson("/api/nina-run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify({
        task: "Calculate 17 * 23 and return the verified result.",
        requested_tools: ["safe_expression"],
      }),
    }, 23000);

    const body = run.body;
    const runIdOk = typeof body?.run_id === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(body.run_id);
    const tipHashOk = typeof body?.tip_hash === "string" && /^[a-f0-9]{64}$/i.test(body.tip_hash);
    const ninaOk = run.response.status === 200 && body?.nina?.status === "VERIFIED";
    const igorOk = run.response.status === 200 && body?.igor?.status === "VERIFIED";
    const proofOk = body?.provenance?.status === "VERIFIED" &&
      /^[a-f0-9]{40}$/i.test(body?.provenance?.commit ?? "") &&
      body?.replay_verification?.status === "VERIFIED" &&
      runIdOk && tipHashOk &&
      Array.isArray(body?.replay) && body.replay.length === 9;
    const gateOk = body?.human_gate?.status === "BLOCK" &&
      body?.decision_report?.human_review?.approved === false &&
      body?.status_fields?.HUMAN_GATE === "REVIEW" &&
      body?.status_fields?.EXECUTION_ALLOWED === "REVIEW";
    const finalOk = body?.status === "REVIEW";

    mark(ui.nina, ninaOk);
    mark(ui.igor, igorOk);
    mark(ui.proof, proofOk);
    mark(ui.gate, gateOk);
    mark(ui.final, finalOk);

    const passed = policyOk && ninaOk && igorOk && proofOk && gateOk && finalOk;
    setOverall(ui.runOverall, passed);
    showResult([
      passed
        ? "PASS: NINA i IGOR zweryfikowały przebieg; Human Gate poprawnie pozostał zamknięty."
        : "FAIL: odpowiedź API nie spełniła pełnego kontraktu NINA/IGOR/Human Gate.",
      "HTTP " + run.response.status,
      "run_id: " + (runIdOk ? body.run_id : "brak lub nieprawidłowy"),
      "NINA: " + (body?.nina?.status ?? "UNKNOWN"),
      "IGOR: " + (body?.igor?.status ?? "UNKNOWN"),
      "Provenance: " + (body?.provenance?.status ?? "UNKNOWN"),
      "Replay: " + (body?.replay_verification?.status ?? "UNKNOWN") +
        " / events=" + (Array.isArray(body?.replay) ? body.replay.length : "brak"),
      "Human Gate: " + (body?.human_gate?.status ?? "UNKNOWN"),
      "Decision: " + (body?.status ?? "UNKNOWN"),
      "REVIEW oznacza: przebieg runtime zweryfikowany, ale bez zatwierdzenia człowieka. To nie jest autoryzacja produkcyjna.",
    ]);
    if (!run.response.ok && body?.detail) {
      const detail = document.createElement("p");
      detail.textContent = "API: " + String(body.detail).slice(0, 240);
      ui.result.appendChild(detail);
    }
  } catch (error) {
    setOverall(ui.runOverall, false);
    showResult([
      error?.name === "AbortError"
        ? "TIMEOUT: proxy Netlify ma limit 26 s. Test deterministyczny nie zakończył się w oknie klienta."
        : "BŁĄD POŁĄCZENIA: " + (error?.name || "NetworkError") + ". Nie traktuj testu jako zaliczonego.",
    ]);
  } finally {
    apiKey = "";
    ui.key.value = "";
    ui.confirm.checked = false;
    ui.runButton.disabled = true;
    ui.clear.disabled = false;
    ui.runTime.textContent = Math.round(performance.now() - start) + " ms";
  }
});

checkInfrastructure();
