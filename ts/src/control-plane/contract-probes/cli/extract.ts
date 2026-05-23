/**
 * `autoctx probes extract` -- synthesize a contract-probe suite from a
 * harness-trace JSON file.
 *
 * A harness trace bundles both:
 *
 *   - `observations`: what actually happened during a recorded run
 *     (terminal exit code / stdout / stderr; the workdir's present files;
 *     observed service endpoints; emitted artifacts and their content).
 *   - `expectations`: what the operator declared SHOULD have happened
 *     (expected exit code; required / allowed / ignored files; required
 *     endpoints; per-artifact JSON-field / substring / line-ending
 *     expectations).
 *
 * The extractor joins them into a runnable `ContractProbeSuite`. The
 * slice-6 `autoctx probes check` runs the resulting suite.
 *
 * Slice 7 supports the four AC-728 slice-1 probe kinds (terminal,
 * directory, service, artifact). Cleanup / media / distributed kinds
 * land in follow-up slices once their trace formats are settled.
 *
 * Wire-format invariants mirror the suite runner (PR #990):
 *
 *   - Every nested object is `.strict()`; unknown keys fail validation.
 *   - RegExp values may be a bare string or `{ source, flags? }`; invalid
 *     regexes surface as Zod issues, not raw SyntaxError.
 *   - Date values transform from ISO-8601 strings; malformed dates
 *     surface as Zod issues.
 */

import { parseArgs } from "node:util";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { z } from "zod";

import type { ContractProbeSuite } from "../index.js";

export interface ProbesExtractResult {
  readonly stdout: string;
  readonly stderr: string;
  readonly exitCode: number;
}

export const EXTRACT_HELP_TEXT = `autoctx probes extract -- synthesize a contract-probe suite from a harness trace.

Usage:
  autoctx probes extract --trace <path> [--output <path>]
  autoctx probes extract --help

A harness trace bundles observations (what happened in a recorded run)
and expectations (what the operator declared should have happened). The
extractor joins them into a runnable probe suite that \`autoctx probes
check\` can execute. See the "Contract Probes" section of the autoctx
README for the harness-trace JSON format and a minimal example.

Options:
  --trace <path>   Path to a harness-trace JSON file. Required.
  --output <path>  Write the resulting suite to this path. Parent
                   directories are created. If omitted, the suite is
                   emitted to stdout so it can be piped to
                   \`autoctx probes check --suite -\`.
  -h, --help       Show this help text.

Exit codes:
  0   the trace parsed and a suite was emitted.
  1   the trace failed to load / parse, or a write to --output failed.

The slice-7 extractor supports four probe kinds (terminal, directory,
service, artifact). Cleanup / media / distributed kinds are scaffolded
in follow-up slices once their trace formats settle.
`;

// --- Shared Zod helpers (mirroring runner.ts) ------------------------------

const RegExpJson = z
  .union([z.string(), z.object({ source: z.string(), flags: z.string().optional() }).strict()])
  .transform((value, ctx) => {
    try {
      return typeof value === "string" ? new RegExp(value) : new RegExp(value.source, value.flags);
    } catch (err) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `invalid regular expression: ${err instanceof Error ? err.message : String(err)}`,
      });
      return z.NEVER;
    }
  });

// --- Per-kind observation + expectation schemas ----------------------------

const TerminalObservation = z
  .object({
    exitCode: z.number(),
    stdout: z.string().default(""),
    stderr: z.string().default(""),
  })
  .strict();

const TerminalExpectations = z
  .object({
    expectedExitCode: z.number().optional(),
    requiredStdoutPatterns: z.array(RegExpJson).optional(),
    forbiddenStdoutPatterns: z.array(RegExpJson).optional(),
    requiredStderrPatterns: z.array(RegExpJson).optional(),
    forbiddenStderrPatterns: z.array(RegExpJson).optional(),
  })
  .strict();

const WorkdirObservation = z
  .object({
    presentFiles: z.array(z.string()),
  })
  .strict();

const DirectoryExpectations = z
  .object({
    requiredFiles: z.array(z.string()).default([]),
    allowedFiles: z.array(z.string()).default([]),
    ignoredPatterns: z.array(RegExpJson).optional(),
  })
  .strict();

const ServiceEndpoint = z
  .object({
    host: z.string(),
    port: z.number(),
    protocol: z.enum(["tcp", "udp"]).optional(),
  })
  .strict();

const ServiceExpectations = z
  .object({
    required: z.array(ServiceEndpoint).default([]),
    allowed: z.array(ServiceEndpoint).optional(),
  })
  .strict();

const ArtifactObservation = z
  .object({
    path: z.string(),
    content: z.string(),
  })
  .strict();

const ArtifactExpectations = z
  .object({
    path: z.string(),
    label: z.string().optional(),
    expectedLineEnding: z.enum(["lf", "crlf"]).optional(),
    requiredSubstrings: z.array(z.string()).optional(),
    forbiddenSubstrings: z.array(z.string()).optional(),
    requiredJsonFields: z.array(z.string()).optional(),
  })
  .strict();

// --- HarnessTrace envelope -------------------------------------------------

const HarnessObservationsSchema = z
  .object({
    terminal: TerminalObservation.optional(),
    workdir: WorkdirObservation.optional(),
    services: z.array(ServiceEndpoint).optional(),
    artifacts: z.array(ArtifactObservation).optional(),
  })
  .strict();

const HarnessExpectationsSchema = z
  .object({
    terminal: TerminalExpectations.optional(),
    directory: DirectoryExpectations.optional(),
    services: ServiceExpectations.optional(),
    artifacts: z.array(ArtifactExpectations).optional(),
  })
  .strict();

export const HarnessTraceSchema = z
  .object({
    schema_version: z.literal(1),
    label: z.string().optional(),
    observations: HarnessObservationsSchema,
    expectations: HarnessExpectationsSchema.optional(),
  })
  .strict()
  // PR #992 review (P2): every declared expectation must have its matching
  // observation. Without this guard, an expectation-only section was
  // silently dropped at extraction time and the resulting suite passed
  // vacuously -- the same silent-pass class of bug the slice-5
  // `missing-observation` failure kind was added to close.
  .superRefine((trace, ctx) => {
    const obs = trace.observations;
    const exp = trace.expectations;
    if (exp === undefined) {
      return;
    }
    if (exp.terminal !== undefined && obs.terminal === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["expectations", "terminal"],
        message:
          "expectation declared without a matching observation; add `observations.terminal` to record exit code / stdout / stderr",
      });
    }
    if (exp.directory !== undefined && obs.workdir === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["expectations", "directory"],
        message:
          "expectation declared without a matching observation; add `observations.workdir` to record present files",
      });
    }
    if (exp.services !== undefined && obs.services === undefined) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["expectations", "services"],
        message:
          "expectation declared without a matching observation; add `observations.services` to record observed endpoints",
      });
    }
    if (exp.artifacts !== undefined) {
      if (obs.artifacts === undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["expectations", "artifacts"],
          message:
            "per-artifact expectations declared without `observations.artifacts`; add the matching artifact observations",
        });
      } else {
        // Per-artifact: every expectation must reference a path that the
        // observations actually contain.
        const observedPaths = new Set(obs.artifacts.map((a) => a.path));
        exp.artifacts.forEach((artExp, index) => {
          if (!observedPaths.has(artExp.path)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["expectations", "artifacts", index, "path"],
              message: `expectation references artifact path ${JSON.stringify(
                artExp.path,
              )} but no observation with that path was recorded`,
            });
          }
        });
      }
    }
  });

export type HarnessTrace = z.infer<typeof HarnessTraceSchema>;

// --- Extractor -------------------------------------------------------------

/** Build a `ContractProbeSuite` (slice 5 wire shape) from a harness trace.
 * Pure function: no IO. The CLI handler wraps this with file IO + arg
 * parsing. */
export function extractContractProbeSuite(trace: HarnessTrace): ContractProbeSuite {
  const probes: ContractProbeSuite["probes"] = [];
  const expectations = trace.expectations ?? {};
  const label = trace.label;

  if (trace.observations.terminal !== undefined) {
    const exp = expectations.terminal ?? {};
    probes.push({
      kind: "terminal",
      ...(label !== undefined ? { label } : {}),
      inputs: {
        exitCode: trace.observations.terminal.exitCode,
        stdout: trace.observations.terminal.stdout,
        stderr: trace.observations.terminal.stderr,
        ...(exp.expectedExitCode !== undefined ? { expectedExitCode: exp.expectedExitCode } : {}),
        ...(exp.requiredStdoutPatterns !== undefined
          ? { requiredStdoutPatterns: exp.requiredStdoutPatterns }
          : {}),
        ...(exp.forbiddenStdoutPatterns !== undefined
          ? { forbiddenStdoutPatterns: exp.forbiddenStdoutPatterns }
          : {}),
        ...(exp.requiredStderrPatterns !== undefined
          ? { requiredStderrPatterns: exp.requiredStderrPatterns }
          : {}),
        ...(exp.forbiddenStderrPatterns !== undefined
          ? { forbiddenStderrPatterns: exp.forbiddenStderrPatterns }
          : {}),
      },
    });
  }

  if (trace.observations.workdir !== undefined) {
    const exp = expectations.directory ?? { requiredFiles: [], allowedFiles: [] };
    probes.push({
      kind: "directory",
      ...(label !== undefined ? { label } : {}),
      inputs: {
        presentFiles: trace.observations.workdir.presentFiles,
        requiredFiles: exp.requiredFiles,
        allowedFiles: exp.allowedFiles,
        ...(exp.ignoredPatterns !== undefined ? { ignoredPatterns: exp.ignoredPatterns } : {}),
      },
    });
  }

  if (trace.observations.services !== undefined) {
    const exp = expectations.services ?? { required: [] };
    probes.push({
      kind: "service",
      ...(label !== undefined ? { label } : {}),
      inputs: {
        observed: trace.observations.services,
        required: exp.required,
        ...(exp.allowed !== undefined ? { allowed: exp.allowed } : {}),
      },
    });
  }

  if (trace.observations.artifacts !== undefined) {
    // Per-artifact: match each observation by `path` against an expectations
    // entry; absent expectations leave the artifact probe in a no-op shape
    // (path + content only, no required/forbidden lists).
    const expectationsByPath = new Map<string, z.infer<typeof ArtifactExpectations>>();
    for (const artExp of expectations.artifacts ?? []) {
      expectationsByPath.set(artExp.path, artExp);
    }
    for (const artifact of trace.observations.artifacts) {
      const exp = expectationsByPath.get(artifact.path);
      probes.push({
        kind: "artifact",
        ...(exp?.label !== undefined ? { label: exp.label } : label !== undefined ? { label } : {}),
        inputs: {
          path: artifact.path,
          content: artifact.content,
          ...(exp?.expectedLineEnding !== undefined
            ? { expectedLineEnding: exp.expectedLineEnding }
            : {}),
          ...(exp?.requiredSubstrings !== undefined
            ? { requiredSubstrings: exp.requiredSubstrings }
            : {}),
          ...(exp?.forbiddenSubstrings !== undefined
            ? { forbiddenSubstrings: exp.forbiddenSubstrings }
            : {}),
          ...(exp?.requiredJsonFields !== undefined
            ? { requiredJsonFields: exp.requiredJsonFields }
            : {}),
        },
      });
    }
  }

  return { schema_version: 1, probes };
}

/** Serialize a `ContractProbeSuite` back to JSON suitable for the suite
 * runner. RegExp values are emitted as `{ source, flags }` objects (the
 * runner schema accepts both bare strings and that object form). */
function serializeSuite(suite: ContractProbeSuite): string {
  return JSON.stringify(
    suite,
    (_key, value) => {
      if (value instanceof RegExp) {
        return { source: value.source, flags: value.flags };
      }
      return value;
    },
    2,
  );
}

// --- CLI handler -----------------------------------------------------------

interface ParsedArgs {
  readonly tracePath?: string;
  readonly outputPath?: string;
  readonly help: boolean;
}

function parseExtractArgs(args: readonly string[]): ParsedArgs | { readonly error: string } {
  try {
    const { values } = parseArgs({
      args: [...args],
      options: {
        trace: { type: "string" },
        output: { type: "string" },
        help: { type: "boolean", short: "h", default: false },
      },
      allowPositionals: false,
    });
    return {
      tracePath: typeof values.trace === "string" ? values.trace : undefined,
      outputPath: typeof values.output === "string" ? values.output : undefined,
      help: values.help === true,
    };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

export async function runExtract(args: readonly string[]): Promise<ProbesExtractResult> {
  const parsed = parseExtractArgs(args);
  if ("error" in parsed) {
    return {
      stdout: "",
      stderr: `autoctx probes extract: ${parsed.error}\n\n${EXTRACT_HELP_TEXT}`,
      exitCode: 1,
    };
  }

  if (parsed.help) {
    return { stdout: EXTRACT_HELP_TEXT, stderr: "", exitCode: 0 };
  }

  if (parsed.tracePath === undefined || parsed.tracePath.length === 0) {
    return {
      stdout: "",
      stderr: `autoctx probes extract: --trace <path> is required\n\n${EXTRACT_HELP_TEXT}`,
      exitCode: 1,
    };
  }

  let raw: string;
  try {
    raw = readFileSync(parsed.tracePath, "utf-8");
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      stdout: "",
      stderr: `autoctx probes extract: failed to read trace from ${parsed.tracePath}: ${message}`,
      exitCode: 1,
    };
  }

  let raw_parsed: unknown;
  try {
    raw_parsed = JSON.parse(raw);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      stdout: "",
      stderr: `autoctx probes extract: invalid JSON in ${parsed.tracePath}: ${message}`,
      exitCode: 1,
    };
  }

  const validation = HarnessTraceSchema.safeParse(raw_parsed);
  if (!validation.success) {
    const issues = validation.error.issues
      .map((issue) => {
        const path = issue.path.length > 0 ? issue.path.join(".") : "<root>";
        return `  - ${path}: ${issue.message}`;
      })
      .join("\n");
    return {
      stdout: "",
      stderr: `autoctx probes extract: trace validation failed\n${issues}`,
      exitCode: 1,
    };
  }

  const suite = extractContractProbeSuite(validation.data);
  const serialized = serializeSuite(suite);

  if (parsed.outputPath !== undefined && parsed.outputPath.length > 0) {
    try {
      mkdirSync(dirname(parsed.outputPath), { recursive: true });
      writeFileSync(parsed.outputPath, serialized + "\n", "utf-8");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        stdout: "",
        stderr: `autoctx probes extract: failed to write suite to ${parsed.outputPath}: ${message}`,
        exitCode: 1,
      };
    }
    return { stdout: `wrote suite to ${parsed.outputPath}`, stderr: "", exitCode: 0 };
  }

  return { stdout: serialized, stderr: "", exitCode: 0 };
}
