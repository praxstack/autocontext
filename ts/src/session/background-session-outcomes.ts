import { buildArtifactCreatedSessionEvent, type NormalizedSessionEvent } from "./background-session-events.js";
import type {
  BackgroundSessionArtifact,
  BackgroundSessionArtifactKind,
} from "./background-session-read-model.js";

export type SessionOutcomeKind =
  | "branch"
  | "commit"
  | "pull_request"
  | "screenshot"
  | "report"
  | "trace"
  | "dataset"
  | "verification_result";

export type SessionOutcomeStatus = "available" | "pending" | "unavailable";
export type SessionOutcomeMetadataValue = string | number | boolean;

export interface SessionOutcomeInput {
  readonly sessionId: string;
  readonly kind: SessionOutcomeKind;
  readonly outcomeId?: string;
  readonly status?: SessionOutcomeStatus;
  readonly title?: string;
  readonly createdAt: string;
  readonly url?: string;
  readonly path?: string;
  readonly ref?: string;
  readonly sha?: string;
  readonly summary?: string;
  readonly metadata?: Record<string, unknown>;
}

export interface SessionOutcome {
  readonly outcome_id: string;
  readonly session_id: string;
  readonly kind: SessionOutcomeKind;
  readonly status: SessionOutcomeStatus;
  readonly title: string;
  readonly created_at: string;
  readonly url: string;
  readonly path: string;
  readonly ref: string;
  readonly sha: string;
  readonly summary: string;
  readonly metadata: Record<string, SessionOutcomeMetadataValue>;
}

export interface MissingHostCapabilityOutcomeInput {
  readonly sessionId: string;
  readonly kind: SessionOutcomeKind;
  readonly requiredCapability: string;
  readonly createdAt: string;
}

export interface SessionOutcomeArtifactEventInput {
  readonly sequence: number;
  readonly timestamp: string;
}

export function buildSessionOutcome(input: SessionOutcomeInput): SessionOutcome {
  assertSessionOutcomeKind(input.kind);
  const status = input.status ?? "available";
  assertSessionOutcomeStatus(status);
  const normalized: SessionOutcome = {
    outcome_id: input.outcomeId || deriveOutcomeId(input),
    session_id: input.sessionId,
    kind: input.kind,
    status,
    title: input.title || labelForKind(input.kind),
    created_at: input.createdAt,
    url: input.url ?? "",
    path: input.path ?? "",
    ref: input.ref ?? "",
    sha: input.sha ?? "",
    summary: input.summary ?? "",
    metadata: sanitizeMetadata(input.metadata ?? {}),
  };
  return normalized;
}

export function buildMissingHostCapabilityOutcome(
  input: MissingHostCapabilityOutcomeInput,
): SessionOutcome {
  assertSessionOutcomeKind(input.kind);
  return {
    outcome_id: `${input.kind}:missing:${input.requiredCapability}`,
    session_id: input.sessionId,
    kind: input.kind,
    status: "unavailable",
    title: `${labelForKind(input.kind)} unavailable`,
    created_at: input.createdAt,
    url: "",
    path: "",
    ref: "",
    sha: "",
    summary: `Host capability ${input.requiredCapability} is unavailable for ${input.kind} outcomes.`,
    metadata: {
      reason: "missing_host_capability",
      required_capability: input.requiredCapability,
    },
  };
}

export function sessionOutcomeToArtifact(outcome: SessionOutcome): BackgroundSessionArtifact {
  assertAvailableSessionOutcome(outcome, "artifacts");
  return {
    artifact_id: outcome.outcome_id,
    kind: outcome.kind as BackgroundSessionArtifactKind,
    label: outcome.title,
    path: outcome.path,
    url: outcome.url,
  };
}

export function buildSessionOutcomeArtifactEvent(
  outcome: SessionOutcome,
  input: SessionOutcomeArtifactEventInput,
): NormalizedSessionEvent {
  assertAvailableSessionOutcome(outcome, "artifact events");
  return buildArtifactCreatedSessionEvent({
    sessionId: outcome.session_id,
    sequence: input.sequence,
    timestamp: input.timestamp,
    artifactId: outcome.outcome_id,
    kind: outcome.kind,
    label: outcome.title || undefined,
    path: outcome.path || undefined,
    url: outcome.url || undefined,
  });
}

function deriveOutcomeId(input: SessionOutcomeInput): string {
  const identity = input.ref || input.sha || input.path || input.url || input.title || input.kind;
  return `${input.kind}:${encodeURIComponent(identity)}`;
}

function sanitizeMetadata(record: Record<string, unknown>): Record<string, SessionOutcomeMetadataValue> {
  const clean: Record<string, SessionOutcomeMetadataValue> = {};
  for (const [key, value] of Object.entries(record)) {
    if (isSensitiveKey(key)) {
      continue;
    }
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      clean[key] = value;
    }
  }
  return clean;
}

function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return ["secret", "token", "password", "credential", "api_key", "apikey", "private_key"].some(
    (marker) => normalized.includes(marker),
  );
}

function assertAvailableSessionOutcome(outcome: SessionOutcome, target: string): void {
  assertSessionOutcomeKind(outcome.kind);
  assertSessionOutcomeStatus(outcome.status);
  if (outcome.status !== "available") {
    throw new RangeError(`Only available session outcomes can be converted to ${target}`);
  }
}

const SESSION_OUTCOME_KINDS = new Set<string>([
  "branch",
  "commit",
  "pull_request",
  "screenshot",
  "report",
  "trace",
  "dataset",
  "verification_result",
]);

function assertSessionOutcomeKind(kind: unknown): asserts kind is SessionOutcomeKind {
  if (typeof kind !== "string" || !SESSION_OUTCOME_KINDS.has(kind)) {
    throw new RangeError(`Unsupported session outcome kind: ${String(kind)}`);
  }
}

const SESSION_OUTCOME_STATUSES = new Set<string>(["available", "pending", "unavailable"]);

function assertSessionOutcomeStatus(status: unknown): asserts status is SessionOutcomeStatus {
  if (typeof status !== "string" || !SESSION_OUTCOME_STATUSES.has(status)) {
    throw new RangeError(`Unsupported session outcome status: ${String(status)}`);
  }
}

function labelForKind(kind: SessionOutcomeKind): string {
  switch (kind) {
    case "branch":
      return "Branch";
    case "commit":
      return "Commit";
    case "pull_request":
      return "Pull request";
    case "screenshot":
      return "Screenshot";
    case "report":
      return "Report";
    case "trace":
      return "Trace";
    case "dataset":
      return "Dataset";
    case "verification_result":
      return "Verification result";
  }
}
