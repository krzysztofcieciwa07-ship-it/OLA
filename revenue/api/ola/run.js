const json = (res, status, payload) => {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store, max-age=0");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.end(JSON.stringify(payload));
};

function getBaseUrl() {
  const raw = process.env.OLA_API_BASE_URL || "https://ola-fastapi-api-staging.up.railway.app";
  const url = new URL(raw);
  if (url.protocol !== "https:" || !url.hostname.endsWith(".up.railway.app")) {
    throw new Error("OLA_API_BASE_URL must be an HTTPS Railway service domain");
  }
  return url.toString().replace(/\/$/, "");
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return json(res, 405, { error: "method_not_allowed" });
  }

  const contentType = String(req.headers["content-type"] || "").toLowerCase();
  if (!contentType.includes("application/json")) {
    return json(res, 415, { error: "content_type_must_be_application_json" });
  }

  let body;
  try {
    body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  } catch {
    return json(res, 400, { error: "invalid_json" });
  }

  const task = body && typeof body.task === "string" ? body.task.trim() : "";
  if (!task) return json(res, 400, { error: "task_required" });
  if (task.length > 2000) return json(res, 413, { error: "task_too_long", max_characters: 2000 });

  const apiKey = process.env.OLA_BFF_API_KEY;
  if (!apiKey) {
    return json(res, 503, {
      error: "bff_api_key_not_configured",
      message: "The server-side OLA service key has not been provisioned. No key is exposed to the browser."
    });
  }

  let base;
  try { base = getBaseUrl(); }
  catch (error) {
    return json(res, 503, { error: "staging_api_not_configured", message: error.message });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 240000);
  try {
    const upstream = await fetch(base + "/nina-run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Key": apiKey
      },
      body: JSON.stringify({
        task,
        requested_tools: ["safe_expression"],
        human_approved: false,
        human_actor: "staging-console",
        human_reason: "Browser submission is not independent human approval."
      }),
      cache: "no-store",
      signal: controller.signal
    });

    const raw = await upstream.text();
    let result;
    try { result = JSON.parse(raw); }
    catch { result = { error: "invalid_upstream_response" }; }

    if (!upstream.ok) {
      const detail = result && typeof result.detail === "string"
        ? result.detail.slice(0, 400)
        : "The OLA runtime rejected or could not complete this request.";
      return json(res, upstream.status >= 500 ? 503 : upstream.status, {
        error: "ola_run_failed",
        upstream_status: upstream.status,
        detail
      });
    }

    const evidenceIds = Array.isArray(result.evidence_ids)
      ? result.evidence_ids.slice(0, 100)
      : (result.decision_report && Array.isArray(result.decision_report.evidence_ids)
        ? result.decision_report.evidence_ids.slice(0, 100)
        : []);

    // Explicit allowlist: expose the result and proof contract, never arbitrary upstream headers.
    return json(res, 200, {
      status: result.status || "UNKNOWN",
      task_id: result.task_id || null,
      run_id: result.run_id || null,
      result: Object.prototype.hasOwnProperty.call(result, "result") ? result.result : null,
      evidence_ids: evidenceIds,
      evidence_count: Number.isInteger(result.evidence_count)
        ? result.evidence_count
        : evidenceIds.length,
      tip_hash: result.tip_hash || null,
      nina: result.nina || { status: "UNKNOWN" },
      igor: result.igor || { status: "UNKNOWN" },
      provenance: result.provenance || { status: "UNKNOWN" },
      replay: Array.isArray(result.replay) ? result.replay.slice(0, 100) : [],
      replay_verification: result.replay_verification || { status: "UNKNOWN" },
      policy: result.policy || { status: "UNKNOWN" },
      status_fields: result.status_fields || {},
      human_gate: result.human_gate || { status: "UNKNOWN" },
      decision_report: result.decision_report || null
    });
  } catch (error) {
    return json(res, 503, {
      error: "ola_upstream_unavailable",
      message: error && error.name === "AbortError"
        ? "OLA execution exceeded the 240-second BFF timeout."
        : "Unable to complete the request against the staging OLA runtime."
    });
  } finally {
    clearTimeout(timer);
  }
};
