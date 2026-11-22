"use strict";

const HIGH_RISK_LABELS = new Set(["p0", "p1", "security", "human-gate:required", "production"]);
const WRITE_PERMISSIONS = new Set(["write", "maintain", "admin"]);

function isHighRisk(labels = [], paths = []) {
  if (labels.some((label) => HIGH_RISK_LABELS.has(String(label).toLowerCase()))) return true;
  return paths.some((path) =>
    /^\.github\//i.test(path) ||
    /^app\//i.test(path) ||
    /^scripts\//i.test(path) ||
    /(^|\/)(migrations?|database|payments?|identity|auth|security)(\/|\.|$)/i.test(path)
  );
}

function extractTaskIssue(body = "") {
  const matches = [...String(body).matchAll(/^\s*Human Gate Task:\s*#([1-9][0-9]*)\s*$/gim)];
  if (matches.length !== 1) return null;
  return Number(matches[0][1]);
}

function parseCodeowners(content) {
  if (typeof content !== "string" || !content.trim()) {
    throw new Error("CODEOWNERS_MISSING_OR_EMPTY");
  }

  const rules = [];
  const supportedPatterns = [
    /^\*$/,
    /^\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*\/$/,
    /^\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/,
    /^\*\.[A-Za-z0-9]+$/,
    /^[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*\/?$/,
  ];
  const validOwner = /^@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\/[a-z0-9][a-z0-9_.-]*)?$/i;

  for (const raw of content.split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, "").trim();
    if (!line) continue;

    const parts = line.split(/\s+/);
    if (parts.length < 2) {
      throw new Error("CODEOWNERS_RULE_WITHOUT_OWNER");
    }

    const pattern = parts[0];
    if (!supportedPatterns.some((candidate) => candidate.test(pattern))
        || pattern.includes("..") || pattern.includes("//")) {
      throw new Error("CODEOWNERS_UNSUPPORTED_PATTERN: " + pattern);
    }

    const ownerTokens = parts.slice(1);
    if (ownerTokens.length === 0 || ownerTokens.some((owner) => !validOwner.test(owner))) {
      throw new Error("CODEOWNERS_RULE_WITHOUT_OWNER");
    }

    const owners = ownerTokens.map((owner) => owner.slice(1).toLowerCase());
    rules.push({ pattern, owners });
  }

  if (rules.length === 0) {
    throw new Error("CODEOWNERS_MISSING_OR_EMPTY");
  }
  return rules;
}

function ownersForPath(path, rules) {
  let owners = new Set();
  for (const rule of rules) {
    const p = rule.pattern;
    let matches = false;
    if (p === "*") matches = true;
    else if (p.startsWith("/") && p.endsWith("/")) {
      matches = path.startsWith(p.slice(1));
    } else if (p.startsWith("/") && !p.includes("*")) {
      matches = path === p.slice(1);
    } else if (p.startsWith("*.")) {
      matches = path.toLowerCase().endsWith(p.slice(1).toLowerCase());
    } else if (!p.includes("*") && !p.startsWith("!")) {
      matches = path === p || path.startsWith(p.replace(/\/$/, "") + "/");
    }
    if (matches) owners = new Set(rule.owners);
  }
  return owners;
}

function latestReviewByUser(reviews = []) {
  const ordered = [...reviews].filter((r) => r && r.user && r.submitted_at)
    .sort((a, b) => new Date(a.submitted_at) - new Date(b.submitted_at));
  const latest = new Map();
  for (const review of ordered) latest.set(String(review.user.login).toLowerCase(), review);
  return latest;
}

function evaluateHumanGate(input) {
  const pr = input.pullRequest || {};
  const files = input.files || [];
  const labels = input.pullRequestLabels || [];
  const paths = files.map((f) => typeof f === "string" ? f : f.filename).filter(Boolean);

  if (!isHighRisk(labels, paths)) {
    return { status: "NOT_APPLICABLE", reason: "PR is not labelled or scoped as a Human Gate task" };
  }
  if (pr.state !== "open") return { status: "BLOCKED", reason: "PR_NOT_OPEN" };
  if (pr.draft === true) return { status: "BLOCKED", reason: "PR_IS_DRAFT" };
  if (!pr.head || !/^[0-9a-f]{40}$/i.test(pr.head.sha || "")) {
    return { status: "BLOCKED", reason: "CURRENT_HEAD_SHA_MISSING" };
  }

  const taskIssueNumber = extractTaskIssue(pr.body || "");
  if (!taskIssueNumber) return { status: "BLOCKED", reason: "HUMAN_GATE_TASK_ISSUE_REFERENCE_MISSING" };
  const taskIssue = (input.issues || {})[taskIssueNumber];
  if (!taskIssue || taskIssue.state !== "open") {
    return { status: "BLOCKED", reason: "TASK_ISSUE_MISSING_OR_CLOSED", taskIssueNumber };
  }
  const issueLabels = (taskIssue.labels || []).map((x) => typeof x === "string" ? x.toLowerCase() : x.name.toLowerCase());
  if (!issueLabels.some((x) => HIGH_RISK_LABELS.has(x))) {
    return { status: "BLOCKED", reason: "TASK_ISSUE_NOT_MARKED_HIGH_RISK", taskIssueNumber };
  }

  let codeowners;
  try {
    codeowners = parseCodeowners(input.codeowners);
  } catch (error) {
    return { status: "BLOCKED", reason: error.message, taskIssueNumber };
  }
  if (paths.length === 0) return { status: "BLOCKED", reason: "CHANGED_FILE_INVENTORY_EMPTY", taskIssueNumber };

  const requiredOwnersByPath = new Map();
  for (const path of paths) {
    const owners = ownersForPath(path, codeowners);
    const independent = new Set([...owners].filter((x) => x !== String(pr.user?.login || "").toLowerCase()));
    if (independent.size === 0) {
      return { status: "BLOCKED", reason: "NO_INDEPENDENT_CODEOWNER_FOR_PATH", path, taskIssueNumber };
    }
    requiredOwnersByPath.set(path, independent);
  }

  const latest = latestReviewByUser(input.reviews || []);
  const eligibleApprovers = [];
  for (const [login, review] of latest.entries()) {
    if (login === String(pr.user?.login || "").toLowerCase()) continue;
    if (review.state !== "APPROVED") continue;
    if (review.commit_id !== pr.head.sha) continue;
    const permission = String((input.permissions || {})[login] || "none").toLowerCase();
    if (!WRITE_PERMISSIONS.has(permission)) continue;
    eligibleApprovers.push(login);
  }

  if (eligibleApprovers.length === 0) {
    return {
      status: "BLOCKED",
      reason: "NO_CURRENT_HEAD_APPROVAL_FROM_INDEPENDENT_WRITE_ENABLED_CODEOWNER",
      taskIssueNumber,
      headSha: pr.head.sha,
    };
  }

  for (const [path, owners] of requiredOwnersByPath.entries()) {
    if (!eligibleApprovers.some((login) => owners.has(login))) {
      return {
        status: "BLOCKED",
        reason: "CHANGED_PATH_LACKS_CURRENT_APPROVED_CODEOWNER",
        path,
        taskIssueNumber,
        headSha: pr.head.sha,
      };
    }
  }

  const unresolved = (input.reviewThreads || []).filter((thread) => thread.isResolved !== true);
  if (unresolved.length > 0) {
    return {
      status: "BLOCKED",
      reason: "UNRESOLVED_REVIEW_THREADS",
      unresolvedCount: unresolved.length,
      taskIssueNumber,
      headSha: pr.head.sha,
    };
  }

  return {
    status: "APPROVED",
    taskIssueNumber,
    headSha: pr.head.sha,
    approvers: eligibleApprovers,
    changedFiles: paths.length,
    resolvedReviewThreads: (input.reviewThreads || []).length,
  };
}

module.exports = {
  HIGH_RISK_LABELS,
  WRITE_PERMISSIONS,
  isHighRisk,
  extractTaskIssue,
  parseCodeowners,
  ownersForPath,
  latestReviewByUser,
  evaluateHumanGate,
};