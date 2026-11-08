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

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return json(res, 405, { error: "method_not_allowed" });
  }

  const expected = process.env.OLA_STAGING_BOOTSTRAP_TRIGGER || "";
  const supplied = typeof req.query?.trigger === "string" ? req.query.trigger : "";
  if (
    expected.length < 48 ||
    supplied.length !== expected.length ||
    !crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(supplied))
  ) {
    return json(res, 404, { error: "not_found" });
  }

  const base = process.env.OLA_API_BASE_URL || "https://ola-fastapi-api-staging.up.railway.app";
  let upstream;
  try {
    const url = new URL(base);
    if (url.protocol !== "https:" || !url.hostname.endsWith(".up.railway.app")) {
      return json(res, 503, { error: "invalid_staging_api_configuration" });
    }
    upstream = await fetch(url.toString().replace(/\/$/, "") + "/_internal/staging/bootstrap-bff-key", {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "X-Staging-Bootstrap-Token": process.env.OLA_STAGING_BOOTSTRAP_SECRET || ""
      },
      cache: "no-store",
      signal: AbortSignal.timeout(15000)
    });
  } catch {
    return json(res, 503, { error: "staging_bootstrap_unavailable" });
  }

  let payload;
  try { payload = await upstream.json(); }
  catch { return json(res, 502, { error: "invalid_bootstrap_response" }); }

  if (upstream.status !== 201 || !payload || typeof payload.api_key !== "string") {
    return json(res, upstream.status >= 500 ? 503 : upstream.status, {
      error: payload && payload.detail ? payload.detail : "staging_bootstrap_failed",
      diagnostics: payload && payload.diagnostics ? payload.diagnostics : null
    });
  }

  // The API key is returned once to this protected caller and is not persisted here.
  return json(res, 201, {
    api_key: payload.api_key,
    tenant_id: payload.tenant_id,
    key_id: payload.key_id,
    scope: payload.scope,
    issued_once: payload.issued_once
  });
};
