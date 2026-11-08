const crypto = require("crypto");

function json(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store, max-age=0");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Robots-Tag", "noindex, nofollow");
  res.end(JSON.stringify(payload));
}

function constantTimeMatch(expected, supplied) {
  if (typeof expected !== "string" || typeof supplied !== "string" ||
      expected.length < 48 || supplied.length !== expected.length) return false;
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(supplied));
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return json(res, 405, { error: "method_not_allowed" });
  }

  const trigger = req.query && typeof req.query.trigger === "string" ? req.query.trigger : "";
  if (!constantTimeMatch(process.env.OLA_STAGING_BOOTSTRAP_TRIGGER || "", trigger)) {
    return json(res, 404, { error: "not_found" });
  }

  const apiKey = process.env.OLA_BFF_API_KEY || "";
  if (!apiKey) return json(res, 503, { error: "bff_api_key_not_configured" });

  const rawBase = process.env.OLA_API_BASE_URL || "https://ola-fastapi-api-staging.up.railway.app";
  let base;
  try {
    const parsed = new URL(rawBase);
    if (parsed.protocol !== "https:" || !parsed.hostname.endsWith(".up.railway.app")) {
      return json(res, 503, { error: "invalid_staging_api_configuration" });
    }
    base = parsed.toString().replace(/\/$/, "");
  } catch {
    return json(res, 503, { error: "invalid_staging_api_configuration" });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 240000);
  try {
    const upstream = await fetch(base + "/nina-run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Key": apiKey
      },
      body: JSON.stringify({
        task: "Calculate 17 * 23 and return the exact verified result 391.",
        requested_tools: ["safe_expression"]
      }),
      cache: "no-store",
      signal: controller.signal
    });

    let result;
    try { result = await upstream.json(); }
    catch { return json(res, 502, { error: "invalid_upstream_response" }); }

    if (!upstream.ok) {
      return json(res, upstream.status >= 500 ? 503 : upstream.status, {
        error: "ola_run_failed",
        upstream_status: upstream.status,
        detail: typeof result.detail === "string" ? result.detail.slice(0, 300) : null
      });
    }

    const nina = result.nina || { status: "UNKNOWN" };
    const evidenceIds = Array.isArray(result.evidence_ids) ? result.evidence_ids.slice(0, 50) : [];
    return json(res, 200, {
      test: "staging_bff_post",
      source_commit: result.provenance && result.provenance.commit || null,
      status: result.status || "UNKNOWN",
      result: Object.prototype.hasOwnProperty.call(result, "result") ? result.result : null,
      nina,
      igor: result.igor || { status: "UNKNOWN" },
      provenance: result.provenance || { status: "UNKNOWN" },
      replay_verification: result.replay_verification || { status: "UNKNOWN" },
      policy: result.policy || { status: "UNKNOWN" },
      human_gate: result.human_gate || { status: "UNKNOWN" },
      evidence_count: Number.isInteger(result.evidence_count) ? result.evidence_count : evidenceIds.length,
      evidence_ids: evidenceIds,
      runtime_kind: nina.invocation_type === "real_llm" ? "real_llm" : "local_deterministic"
    });
  } catch (error) {
    return json(res, 503, {
      error: error && error.name === "AbortError" ? "execution_timeout" : "staging_api_unavailable"
    });
  } finally {
    clearTimeout(timeout);
  }
};
