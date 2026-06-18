export const GOAL_RUN_STATUSES = [
  "continued",
  "verified_complete",
  "blocked",
  "budget_exhausted",
  "verifier_failed",
  "no_progress",
  "canceled",
] as const;
export const GOAL_ACTION_KINDS = ["run", "solve", "improve", "mission", "campaign"] as const;
export const GOAL_ACTION_STATUSES = [
  "planned",
  "running",
  "completed",
  "failed",
  "canceled",
] as const;

export type GoalRunStatus = (typeof GOAL_RUN_STATUSES)[number];
export type GoalActionKind = (typeof GOAL_ACTION_KINDS)[number];
export type GoalActionStatus = (typeof GOAL_ACTION_STATUSES)[number];
export type GoalDecisionKind = "continue" | "stop";
export type GoalStopReason = Exclude<GoalRunStatus, "continued">;

export interface GoalEvidenceRef {
  uri: string;
  summary: string;
}

export interface GoalBudget {
  max_iterations: number | null;
  max_actions: number | null;
  max_seconds: number | null;
  max_tokens: number | null;
  max_no_progress_iterations: number | null;
}

export interface GoalUsage {
  iterations: number;
  actions: number;
  elapsed_seconds: number;
  tokens: number;
  no_progress_count: number;
}

export interface GoalActionRecord {
  action_id: string;
  action_kind: GoalActionKind;
  status: GoalActionStatus;
  started_at: string | null;
  completed_at: string | null;
  inner_run_ref: string | null;
  summary: string;
  evidence_refs: GoalEvidenceRef[];
  negative_result_ledger_uri: string | null;
}

export interface GoalVerifierState {
  verifier_ref: string;
  verified: boolean;
  verifier_failed: boolean;
  confidence: number | null;
  summary: string;
  evidence_refs: GoalEvidenceRef[];
}

export interface GoalSupervisorDecision {
  decision_id: string;
  decision_kind: GoalDecisionKind;
  status: GoalRunStatus;
  next_action_kind: GoalActionKind | null;
  stop_reason: GoalStopReason | null;
  rationale: string;
  evidence_refs: GoalEvidenceRef[];
}

export interface GoalRunReport {
  schema_version: 1;
  goal_id: string;
  goal_run_id: string;
  scenario_name: string;
  objective: string;
  generated_at: string;
  resume_token: string;
  status: GoalRunStatus;
  verifier_ref: string;
  budget: GoalBudget;
  usage: GoalUsage;
  actions: GoalActionRecord[];
  verifier_state: GoalVerifierState;
  decision: GoalSupervisorDecision;
}

export interface BuildGoalRunReportInput {
  goal_id: string;
  goal_run_id: string;
  scenario_name: string;
  objective: string;
  verifier_ref: string;
  budget: GoalBudget;
  usage: GoalUsage;
  actions: GoalActionRecord[];
  verifier_state: GoalVerifierState;
  next_action_kind?: GoalActionKind | null;
  blocked_reason?: string | null;
  requested_cancel?: boolean;
  decision_id?: string;
  generated_at?: string;
  resume_token?: string;
}

const GOAL_RUN_STATUS_SET = new Set<string>(GOAL_RUN_STATUSES);
const GOAL_ACTION_KIND_SET = new Set<string>(GOAL_ACTION_KINDS);
const GOAL_ACTION_STATUS_SET = new Set<string>(GOAL_ACTION_STATUSES);

export function buildGoalRunReport(input: BuildGoalRunReportInput): GoalRunReport {
  const budget = parseBudget(input.budget);
  const usage = parseUsage(input.usage);
  const verifierState = parseVerifierState(input.verifier_state);
  const decision = decideGoalRun({
    budget,
    usage,
    verifierState,
    nextActionKind: input.next_action_kind ?? null,
    blockedReason: input.blocked_reason ?? null,
    requestedCancel: input.requested_cancel ?? false,
    decisionId: input.decision_id ?? `${input.goal_run_id}:decision:${usage.iterations}`,
  });
  return parseGoalRunReport({
    schema_version: 1,
    goal_id: input.goal_id,
    goal_run_id: input.goal_run_id,
    scenario_name: input.scenario_name,
    objective: input.objective,
    generated_at: input.generated_at ?? new Date().toISOString(),
    resume_token: input.resume_token ?? `${input.goal_run_id}:${usage.iterations}`,
    status: decision.status,
    verifier_ref: input.verifier_ref,
    budget,
    usage,
    actions: input.actions,
    verifier_state: verifierState,
    decision,
  });
}

export function parseGoalRunReport(value: unknown): GoalRunReport {
  const report = record(value, "goal run report");
  exact(report, [
    "schema_version",
    "goal_id",
    "goal_run_id",
    "scenario_name",
    "objective",
    "generated_at",
    "resume_token",
    "status",
    "verifier_ref",
    "budget",
    "usage",
    "actions",
    "verifier_state",
    "decision",
  ]);
  if (report.schema_version !== 1) throw new Error("schema_version must be 1");
  const status = goalRunStatus(report.status);
  const decision = parseDecision(report.decision);
  if (status !== decision.status) throw new Error("status must match decision.status");
  return {
    schema_version: 1,
    goal_id: string(report.goal_id, "goal_id"),
    goal_run_id: string(report.goal_run_id, "goal_run_id"),
    scenario_name: string(report.scenario_name, "scenario_name"),
    objective: string(report.objective, "objective"),
    generated_at: string(report.generated_at, "generated_at"),
    resume_token: string(report.resume_token, "resume_token"),
    status,
    verifier_ref: string(report.verifier_ref, "verifier_ref"),
    budget: parseBudget(report.budget),
    usage: parseUsage(report.usage),
    actions: array(report.actions, "actions").map(parseAction),
    verifier_state: parseVerifierState(report.verifier_state),
    decision,
  };
}

export function goalRunReportToMarkdown(report: GoalRunReport): string {
  return [
    `# Goal Run Report: ${report.goal_run_id}`,
    `- Goal: ${report.goal_id}`,
    `- Scenario: ${report.scenario_name}`,
    `- Status: ${report.status}`,
    `- Decision: ${report.decision.decision_kind}`,
    `- Next action: ${report.decision.next_action_kind ?? "none"}`,
    `- Rationale: ${report.decision.rationale}`,
    "",
  ].join("\n");
}

function decideGoalRun(input: {
  budget: GoalBudget;
  usage: GoalUsage;
  verifierState: GoalVerifierState;
  nextActionKind: GoalActionKind | null;
  blockedReason: string | null;
  requestedCancel: boolean;
  decisionId: string;
}): GoalSupervisorDecision {
  const evidenceRefs = input.verifierState.evidence_refs;
  if (input.requestedCancel)
    return stopDecision(input.decisionId, "canceled", "Goal canceled by operator.", evidenceRefs);
  if (input.verifierState.verifier_failed)
    return stopDecision(
      input.decisionId,
      "verifier_failed",
      "Verifier failed before goal completion.",
      evidenceRefs,
    );
  if (input.verifierState.verified)
    return stopDecision(
      input.decisionId,
      "verified_complete",
      "Verifier confirmed the goal is complete.",
      evidenceRefs,
    );
  if (input.blockedReason)
    return stopDecision(input.decisionId, "blocked", input.blockedReason, evidenceRefs);
  if (budgetExhausted(input.budget, input.usage))
    return stopDecision(
      input.decisionId,
      "budget_exhausted",
      "Goal budget exhausted before verification.",
      evidenceRefs,
    );
  if (noProgressExhausted(input.budget, input.usage))
    return stopDecision(
      input.decisionId,
      "no_progress",
      "No-progress limit reached with evidence.",
      evidenceRefs,
    );
  const nextActionKind = input.nextActionKind ?? "mission";
  return {
    decision_id: input.decisionId,
    decision_kind: "continue",
    status: "continued",
    next_action_kind: nextActionKind,
    stop_reason: null,
    rationale: `Verifier incomplete; continue with ${nextActionKind} checkpoint.`,
    evidence_refs: evidenceRefs,
  };
}

function stopDecision(
  decisionId: string,
  reason: GoalStopReason,
  rationale: string,
  evidenceRefs: GoalEvidenceRef[],
): GoalSupervisorDecision {
  return {
    decision_id: decisionId,
    decision_kind: "stop",
    status: reason,
    next_action_kind: null,
    stop_reason: reason,
    rationale,
    evidence_refs: evidenceRefs,
  };
}

function budgetExhausted(budget: GoalBudget, usage: GoalUsage): boolean {
  return (
    (budget.max_iterations !== null && usage.iterations >= budget.max_iterations) ||
    (budget.max_actions !== null && usage.actions >= budget.max_actions) ||
    (budget.max_seconds !== null && usage.elapsed_seconds >= budget.max_seconds) ||
    (budget.max_tokens !== null && usage.tokens >= budget.max_tokens)
  );
}

function noProgressExhausted(budget: GoalBudget, usage: GoalUsage): boolean {
  return (
    budget.max_no_progress_iterations !== null &&
    usage.no_progress_count >= budget.max_no_progress_iterations
  );
}

function parseBudget(value: unknown): GoalBudget {
  const item = record(value, "goal budget");
  exact(item, [
    "max_iterations",
    "max_actions",
    "max_seconds",
    "max_tokens",
    "max_no_progress_iterations",
  ]);
  return {
    max_iterations: nullableNonNegativeInteger(item.max_iterations, "max_iterations"),
    max_actions: nullableNonNegativeInteger(item.max_actions, "max_actions"),
    max_seconds: nullableNonNegativeNumber(item.max_seconds, "max_seconds"),
    max_tokens: nullableNonNegativeInteger(item.max_tokens, "max_tokens"),
    max_no_progress_iterations: nullableNonNegativeInteger(
      item.max_no_progress_iterations,
      "max_no_progress_iterations",
    ),
  };
}

function parseUsage(value: unknown): GoalUsage {
  const item = record(value, "goal usage");
  exact(item, ["iterations", "actions", "elapsed_seconds", "tokens", "no_progress_count"]);
  return {
    iterations: nonNegativeInteger(item.iterations, "iterations"),
    actions: nonNegativeInteger(item.actions, "actions"),
    elapsed_seconds: nonNegativeNumber(item.elapsed_seconds, "elapsed_seconds"),
    tokens: nonNegativeInteger(item.tokens, "tokens"),
    no_progress_count: nonNegativeInteger(item.no_progress_count, "no_progress_count"),
  };
}

function parseAction(value: unknown): GoalActionRecord {
  const item = record(value, "goal action");
  exact(item, [
    "action_id",
    "action_kind",
    "status",
    "started_at",
    "completed_at",
    "inner_run_ref",
    "summary",
    "evidence_refs",
    "negative_result_ledger_uri",
  ]);
  return {
    action_id: string(item.action_id, "action_id"),
    action_kind: goalActionKind(item.action_kind),
    status: goalActionStatus(item.status),
    started_at: nullableString(item.started_at, "started_at"),
    completed_at: nullableString(item.completed_at, "completed_at"),
    inner_run_ref: nullableString(item.inner_run_ref, "inner_run_ref"),
    summary: string(item.summary, "summary"),
    evidence_refs: array(item.evidence_refs, "evidence_refs").map(parseEvidenceRef),
    negative_result_ledger_uri: nullableString(
      item.negative_result_ledger_uri,
      "negative_result_ledger_uri",
    ),
  };
}

function parseVerifierState(value: unknown): GoalVerifierState {
  const item = record(value, "goal verifier state");
  exact(item, [
    "verifier_ref",
    "verified",
    "verifier_failed",
    "confidence",
    "summary",
    "evidence_refs",
  ]);
  const verified = boolean(item.verified, "verified");
  const verifierFailed = boolean(item.verifier_failed, "verifier_failed");
  if (verified && verifierFailed) throw new Error("verified and verifier_failed are mutually exclusive");
  return {
    verifier_ref: string(item.verifier_ref, "verifier_ref"),
    verified,
    verifier_failed: verifierFailed,
    confidence: nullableNumber(item.confidence, "confidence"),
    summary: string(item.summary, "summary"),
    evidence_refs: array(item.evidence_refs, "evidence_refs").map(parseEvidenceRef),
  };
}

function parseDecision(value: unknown): GoalSupervisorDecision {
  const item = record(value, "goal decision");
  exact(item, [
    "decision_id",
    "decision_kind",
    "status",
    "next_action_kind",
    "stop_reason",
    "rationale",
    "evidence_refs",
  ]);
  const status = goalRunStatus(item.status);
  const decisionKind = goalDecisionKind(item.decision_kind);
  const nextActionKind = item.next_action_kind === null ? null : goalActionKind(item.next_action_kind);
  const stopReason = item.stop_reason === null ? null : goalStopReason(item.stop_reason);
  if (decisionKind === "continue") {
    if (status !== "continued" || nextActionKind === null || stopReason !== null) {
      throw new Error("continue decisions require continued status, next action, and no stop reason");
    }
  } else if (status === "continued" || nextActionKind !== null || stopReason !== status) {
    throw new Error("stop decisions require terminal status, no next action, and matching stop reason");
  }
  return {
    decision_id: string(item.decision_id, "decision_id"),
    decision_kind: decisionKind,
    status,
    next_action_kind: nextActionKind,
    stop_reason: stopReason,
    rationale: string(item.rationale, "rationale"),
    evidence_refs: array(item.evidence_refs, "evidence_refs").map(parseEvidenceRef),
  };
}

function parseEvidenceRef(value: unknown): GoalEvidenceRef {
  const item = record(value, "goal evidence ref");
  exact(item, ["uri", "summary"]);
  return { uri: string(item.uri, "uri"), summary: string(item.summary, "summary") };
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function exact(item: Record<string, unknown>, allowed: string[]): void {
  const allowedSet = new Set(allowed);
  const keys = Object.keys(item);
  const missing = allowed.filter((key) => !keys.includes(key));
  if (missing.length) throw new Error(`missing field(s): ${missing.sort().join(", ")}`);
  const extra = keys.filter((key) => !allowedSet.has(key));
  if (extra.length) throw new Error(`unexpected field(s): ${extra.sort().join(", ")}`);
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} must be a string`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  return value === null ? null : string(value, label);
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value))
    throw new Error(`${label} must be a number`);
  return value;
}

function nullableNumber(value: unknown, label: string): number | null {
  return value === null ? null : number(value, label);
}

function nonNegativeNumber(value: unknown, label: string): number {
  const result = number(value, label);
  if (result < 0) throw new Error(`${label} must be non-negative`);
  return result;
}

function nullableNonNegativeNumber(value: unknown, label: string): number | null {
  return value === null ? null : nonNegativeNumber(value, label);
}

function integer(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new Error(`${label} must be an integer`);
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  const result = integer(value, label);
  if (result < 0) throw new Error(`${label} must be a non-negative integer`);
  return result;
}

function nullableNonNegativeInteger(value: unknown, label: string): number | null {
  return value === null ? null : nonNegativeInteger(value, label);
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} must be a boolean`);
  return value;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function goalRunStatus(value: unknown): GoalRunStatus {
  const result = string(value, "status");
  if (!GOAL_RUN_STATUS_SET.has(result)) throw new Error("status must be a goal run status");
  return result as GoalRunStatus;
}

function goalActionKind(value: unknown): GoalActionKind {
  const result = string(value, "action_kind");
  if (!GOAL_ACTION_KIND_SET.has(result)) throw new Error("action_kind must be a goal action kind");
  return result as GoalActionKind;
}

function goalActionStatus(value: unknown): GoalActionStatus {
  const result = string(value, "action status");
  if (!GOAL_ACTION_STATUS_SET.has(result)) throw new Error("status must be a goal action status");
  return result as GoalActionStatus;
}

function goalDecisionKind(value: unknown): GoalDecisionKind {
  const result = string(value, "decision_kind");
  if (result !== "continue" && result !== "stop")
    throw new Error("decision_kind must be continue or stop");
  return result;
}

function goalStopReason(value: unknown): GoalStopReason {
  const result = goalRunStatus(value);
  if (result === "continued") throw new Error("stop_reason must be terminal");
  return result;
}
