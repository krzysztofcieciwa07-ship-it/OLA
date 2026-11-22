"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const policy = require("../.github/scripts/human-gate-policy.cjs");

const SHA = "a".repeat(40);
const AUTHOR = "task-author";
const REVIEWER = "independent-reviewer";
const paths = ["app/approval.py", ".github/workflows/release.yml"];
const codeowners = [
  "* @task-author @independent-reviewer",
  "/.github/ @task-author @independent-reviewer",
  "/app/ @task-author @independent-reviewer",
].join("\n");
const approved = [{
  user: { login: REVIEWER },
  state: "APPROVED",
  commit_id: SHA,
  submitted_at: "2026-11-22T10:00:00Z",
}];

function input(overrides = {}) {
  return {
    pullRequest: {
      state: "open",
      draft: false,
      body: "Human Gate Task: #292",
      user: { login: AUTHOR },
      head: { sha: SHA },
    },
    pullRequestLabels: ["security"],
    files: paths,
    issues: {
      292: { state: "open", labels: [{ name: "P0" }, { name: "security" }] },
    },
    codeowners,
    reviews: approved,
    permissions: { [REVIEWER]: "write" },
    reviewThreads: [{ isResolved: true }],
    ...overrides,
  };
}

test("low-risk PR is not incorrectly forced into Human Gate", () => {
  const result = policy.evaluateHumanGate(input({
    pullRequestLabels: ["documentation"],
    files: ["README.md"],
  }));
  assert.equal(result.status, "NOT_APPLICABLE");
});

test("high-risk PR requires an explicit existing task issue", () => {
  const result = policy.evaluateHumanGate(input({
    pullRequest: { ...input().pullRequest, body: "No task reference" },
  }));
  assert.equal(result.status, "BLOCKED");
  assert.equal(result.reason, "HUMAN_GATE_TASK_ISSUE_REFERENCE_MISSING");
});

test("closed or absent task issue blocks", () => {
  const result = policy.evaluateHumanGate(input({ issues: {} }));
  assert.equal(result.reason, "TASK_ISSUE_MISSING_OR_CLOSED");
});

test("task issue without a high-risk label blocks", () => {
  const result = policy.evaluateHumanGate(input({
    issues: { 292: { state: "open", labels: [{ name: "documentation" }] } },
  }));
  assert.equal(result.reason, "TASK_ISSUE_NOT_MARKED_HIGH_RISK");
});

test("draft PR cannot receive Human Gate approval", () => {
  const result = policy.evaluateHumanGate(input({
    pullRequest: { ...input().pullRequest, draft: true },
  }));
  assert.equal(result.reason, "PR_IS_DRAFT");
});

test("author self-approval is not counted", () => {
  const result = policy.evaluateHumanGate(input({
    reviews: [{
      user: { login: AUTHOR }, state: "APPROVED", commit_id: SHA,
      submitted_at: "2026-11-22T10:00:00Z",
    }],
    permissions: { [AUTHOR]: "admin" },
  }));
  assert.equal(result.reason, "NO_CURRENT_HEAD_APPROVAL_FROM_INDEPENDENT_WRITE_ENABLED_CODEOWNER");
});

test("read-only reviewer cannot approve Human Gate", () => {
  const result = policy.evaluateHumanGate(input({
    permissions: { [REVIEWER]: "read" },
  }));
  assert.equal(result.reason, "NO_CURRENT_HEAD_APPROVAL_FROM_INDEPENDENT_WRITE_ENABLED_CODEOWNER");
});

test("stale approval for a previous HEAD is rejected", () => {
  const result = policy.evaluateHumanGate(input({
    reviews: [{ ...approved[0], commit_id: "b".repeat(40) }],
  }));
  assert.equal(result.reason, "NO_CURRENT_HEAD_APPROVAL_FROM_INDEPENDENT_WRITE_ENABLED_CODEOWNER");
});

test("newer CHANGES_REQUESTED supersedes an older approval", () => {
  const result = policy.evaluateHumanGate(input({
    reviews: [
      ...approved,
      {
        user: { login: REVIEWER }, state: "CHANGES_REQUESTED", commit_id: SHA,
        submitted_at: "2026-11-22T11:00:00Z",
      },
    ],
  }));
  assert.equal(result.reason, "NO_CURRENT_HEAD_APPROVAL_FROM_INDEPENDENT_WRITE_ENABLED_CODEOWNER");
});

test("CODEOWNER must cover every changed high-risk path", () => {
  const result = policy.evaluateHumanGate(input({
    files: ["scripts/release.py"],
    codeowners: "* @task-author\n/app/ @task-author @independent-reviewer\n/.github/ @task-author @independent-reviewer",
  }));
  assert.equal(result.reason, "NO_INDEPENDENT_CODEOWNER_FOR_PATH");
});

test("unresolved review threads block", () => {
  const result = policy.evaluateHumanGate(input({
    reviewThreads: [{ isResolved: false }],
  }));
  assert.equal(result.reason, "UNRESOLVED_REVIEW_THREADS");
});

test("current-head write-enabled independent CODEOWNER approval passes", () => {
  const result = policy.evaluateHumanGate(input());
  assert.equal(result.status, "APPROVED");
  assert.equal(result.headSha, SHA);
  assert.deepEqual(result.approvers, [REVIEWER]);
});

test("unknown or empty CODEOWNERS fails closed", () => {
  const result = policy.evaluateHumanGate(input({ codeowners: "" }));
  assert.equal(result.reason, "CODEOWNERS_MISSING_OR_EMPTY");
});