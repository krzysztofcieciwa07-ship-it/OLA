const json = (res, status, payload) => {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store, max-age=0");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.end(JSON.stringify(payload));
};

function getBaseUrl() {
  const raw = process.env.OLA_API_BASE_URL || "https://ola-fastapi-api-staging.up.railway.app";
  if (!raw) throw new Error("OLA_API_BASE_URL is not configured");
  const url = new URL(raw);
  if (url.protocol !== "https:" || !url.hostname.endsWith(".up.railway.app")) {
    throw new Error("OLA_API_BASE_URL must be an HTTPS Railway service domain");
  }
  return url.toString().replace(/\/$/, "");
}

async function getJson(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "Accept": "application/json" },
      cache: "no-store",
      signal: controller.signal
    });
    const raw = await response.text();
    let body;
    try { body = JSON.parse(raw); }
    catch { body = { message: "Upstream returned a non-JSON response" }; }
    return { http_status: response.status, ok: response.ok, body };
  } finally {
    clearTimeout(timer);
  }
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return json(res, 405, { error: "method_not_allowed" });
  }
  try {
    const base = getBaseUrl();
    const [liveness, readiness] = await Promise.all([
      getJson(base + "/health", 5000),
      getJson(base + "/readyz", 10000)
    ]);
    return json(res, 200, {
      service: "ola-fastapi-staging",
      checked_at: new Date().toISOString(),
      reachable: true,
      liveness: {
        ok: liveness.ok,
        http_status: liveness.http_status,
        body: liveness.body
      },
      readiness: {
        ready: readiness.ok && readiness.body && readiness.body.core_status === "READY",
        http_status: readiness.http_status,
        body: readiness.body
      },
      note: "CORE readiness is not whole-system acceptance."
    });
  } catch (error) {
    const message = error && error.message === "OLA_API_BASE_URL is not configured"
      ? error.message
      : (error && error.message === "OLA_API_BASE_URL must be an HTTPS Railway service domain"
        ? error.message
        : "Unable to reach the staging API");
    return json(res, 502, {
      service: "ola-fastapi-staging",
      checked_at: new Date().toISOString(),
      reachable: false,
      error: message
    });
  }
};
