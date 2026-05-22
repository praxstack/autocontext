/**
 * AC-728: contract-probe suite runner.
 *
 * Library-level entry point that dispatches a JSON-defined probe suite
 * across all seven AC-728 probes (directory / terminal / service / artifact
 * / cleanup / media / distributed) and aggregates results. The runner is
 * pure: callers do the IO to populate the observations; the runner verifies.
 *
 * The probes themselves stay in `./index.js`. This module adds:
 *
 * - `ContractProbeSuiteSchema` (Zod): validates the JSON spec format.
 * - `runContractProbeSuite(suite)`: dispatches every invocation through the
 *   matching probe and aggregates results.
 * - `loadContractProbeSuite(path)`: file loader mirroring the
 *   `loadContract` pattern from `cli-contract.ts`.
 *
 * JSON wire format notes:
 *
 * - RegExp values are serialised as either a bare string (`"^trace\\."`,
 *   treated as the pattern with no flags) or as `{ source, flags? }`.
 *   The schema transforms either form to a real RegExp before handing it
 *   to the probe.
 * - Date values (cleanup probe's `now` and per-entry `mtime`) are
 *   serialised as ISO-8601 strings and parsed into Date objects by the
 *   schema.
 */

import { readFileSync } from "node:fs";

import { z } from "zod";

import {
  probeArtifactContract,
  probeCleanupContract,
  probeDirectoryContract,
  probeDistributedContract,
  probeMediaContract,
  probeServiceContract,
  probeTerminalContract,
} from "./index.js";

// --- Reusable Zod helpers ---------------------------------------------------

const RegExpJson = z
  .union([z.string(), z.object({ source: z.string(), flags: z.string().optional() })])
  .transform((value) =>
    typeof value === "string" ? new RegExp(value) : new RegExp(value.source, value.flags),
  );

const DateJson = z.union([z.string(), z.date()]).transform((value) => {
  if (value instanceof Date) {
    return value;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`invalid ISO-8601 date: ${JSON.stringify(value)}`);
  }
  return parsed;
});

// --- Per-probe input schemas ------------------------------------------------

const DirectoryInputs = z.object({
  presentFiles: z.array(z.string()),
  requiredFiles: z.array(z.string()),
  allowedFiles: z.array(z.string()),
  ignoredPatterns: z.array(RegExpJson).optional(),
});

const TerminalInputs = z.object({
  exitCode: z.number(),
  stdout: z.string(),
  stderr: z.string(),
  expectedExitCode: z.number().optional(),
  requiredStdoutPatterns: z.array(RegExpJson).optional(),
  forbiddenStdoutPatterns: z.array(RegExpJson).optional(),
  requiredStderrPatterns: z.array(RegExpJson).optional(),
  forbiddenStderrPatterns: z.array(RegExpJson).optional(),
});

const ServiceEndpoint = z.object({
  host: z.string(),
  port: z.number(),
  protocol: z.enum(["tcp", "udp"]).optional(),
});

const ServiceInputs = z.object({
  observed: z.array(ServiceEndpoint),
  required: z.array(ServiceEndpoint),
  allowed: z.array(ServiceEndpoint).optional(),
});

const ArtifactInputs = z.object({
  path: z.string(),
  content: z.string(),
  expectedLineEnding: z.enum(["lf", "crlf"]).optional(),
  requiredSubstrings: z.array(z.string()).optional(),
  forbiddenSubstrings: z.array(z.string()).optional(),
  requiredJsonFields: z.array(z.string()).optional(),
});

const CleanupEntry = z.object({
  path: z.string(),
  isSymlink: z.boolean().optional(),
  symlinkTarget: z.string().optional(),
  symlinkBroken: z.boolean().optional(),
  mtime: DateJson.optional(),
});

const CleanupInputs = z.object({
  entries: z.array(CleanupEntry),
  now: DateJson.optional(),
  maxLockfileAgeMs: z.number().optional(),
  lockfilePatterns: z.array(RegExpJson).optional(),
  sidecarPatterns: z.array(RegExpJson).optional(),
  backupPatterns: z.array(RegExpJson).optional(),
  forbidSymlinks: z.boolean().optional(),
  allowedSymlinkTargets: z.array(z.string()).optional(),
  ignoredPatterns: z.array(RegExpJson).optional(),
});

const MediaInputs = z.object({
  path: z.string(),
  headerBytes: z.array(z.number()).optional(),
  expectedMagicBytes: z.array(z.number()).optional(),
  width: z.number().optional(),
  height: z.number().optional(),
  expectedWidth: z.number().optional(),
  expectedHeight: z.number().optional(),
  byteSize: z.number().optional(),
  minByteSize: z.number().optional(),
  maxByteSize: z.number().optional(),
  columnCount: z.number().optional(),
  expectedColumnCount: z.number().optional(),
  columnNames: z.array(z.string()).optional(),
  requiredColumnNames: z.array(z.string()).optional(),
  lineCount: z.number().optional(),
  expectedLineCount: z.number().optional(),
});

const DistributedRank = z.object({
  rank: z.number(),
  steps: z.number().optional(),
  observations: z.record(z.string(), z.string()).optional(),
});

const DistributedInputs = z.object({
  ranks: z.array(DistributedRank),
  worldSize: z.number().optional(),
  expectedWorldSize: z.number().optional(),
  expectedSteps: z.number().optional(),
  mustMatchAcrossRanks: z.array(z.string()).optional(),
});

// --- Suite envelope ---------------------------------------------------------

export const ContractProbeKindEnum = z.enum([
  "directory",
  "terminal",
  "service",
  "artifact",
  "cleanup",
  "media",
  "distributed",
]);

export type ContractProbeKind = z.infer<typeof ContractProbeKindEnum>;

const InvocationBase = { label: z.string().optional() };

const ContractProbeInvocationSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("directory"), ...InvocationBase, inputs: DirectoryInputs }),
  z.object({ kind: z.literal("terminal"), ...InvocationBase, inputs: TerminalInputs }),
  z.object({ kind: z.literal("service"), ...InvocationBase, inputs: ServiceInputs }),
  z.object({ kind: z.literal("artifact"), ...InvocationBase, inputs: ArtifactInputs }),
  z.object({ kind: z.literal("cleanup"), ...InvocationBase, inputs: CleanupInputs }),
  z.object({ kind: z.literal("media"), ...InvocationBase, inputs: MediaInputs }),
  z.object({ kind: z.literal("distributed"), ...InvocationBase, inputs: DistributedInputs }),
]);

export type ContractProbeInvocation = z.infer<typeof ContractProbeInvocationSchema>;

export const ContractProbeSuiteSchema = z.object({
  schema_version: z.literal(1),
  probes: z.array(ContractProbeInvocationSchema),
});

export type ContractProbeSuite = z.infer<typeof ContractProbeSuiteSchema>;

// --- Results ----------------------------------------------------------------

/** A cross-kind probe failure surface. Every probe failure has at least
 * `kind` and `message`; specific probes attach additional fields (`path`,
 * `rank`, `key`, `endpoint`) that callers refine on after switching on
 * `kind`. */
export interface ContractProbeFailure {
  readonly kind: string;
  readonly message: string;
}

export interface ContractProbeRunResult {
  readonly kind: ContractProbeKind;
  readonly label?: string;
  readonly passed: boolean;
  readonly failures: readonly ContractProbeFailure[];
}

export interface ContractProbeSuiteResult {
  readonly passed: boolean;
  readonly results: readonly ContractProbeRunResult[];
}

// --- Runner -----------------------------------------------------------------

export function runContractProbeSuite(suite: ContractProbeSuite): ContractProbeSuiteResult {
  const results: ContractProbeRunResult[] = [];

  for (const invocation of suite.probes) {
    // Dispatch is exhaustive over ContractProbeKind; the discriminated union
    // ensures that adding a new probe kind without updating this switch is a
    // compile-time error. Each probe returns its own typed failure shape;
    // the runner narrows to the cross-kind `ContractProbeFailure` for
    // aggregation. Callers refine on `kind` to recover the specific shape.
    let probeResult: { passed: boolean; failures: readonly ContractProbeFailure[] };
    switch (invocation.kind) {
      case "directory":
        probeResult = probeDirectoryContract(invocation.inputs);
        break;
      case "terminal":
        probeResult = probeTerminalContract(invocation.inputs);
        break;
      case "service":
        probeResult = probeServiceContract(invocation.inputs);
        break;
      case "artifact":
        probeResult = probeArtifactContract(invocation.inputs);
        break;
      case "cleanup":
        probeResult = probeCleanupContract(invocation.inputs);
        break;
      case "media":
        probeResult = probeMediaContract(invocation.inputs);
        break;
      case "distributed":
        probeResult = probeDistributedContract(invocation.inputs);
        break;
    }

    results.push({
      kind: invocation.kind,
      label: invocation.label,
      passed: probeResult.passed,
      failures: probeResult.failures,
    });
  }

  return {
    passed: results.every((r) => r.passed),
    results,
  };
}

export function loadContractProbeSuite(path: string): ContractProbeSuite {
  const raw = readFileSync(path, "utf-8");
  const parsed: unknown = JSON.parse(raw);
  return ContractProbeSuiteSchema.parse(parsed);
}
