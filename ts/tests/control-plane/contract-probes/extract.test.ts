import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
  ContractProbeSuiteSchema,
  runContractProbeSuite,
} from "../../../src/control-plane/contract-probes/index.js";
import {
  EXTRACT_HELP_TEXT,
  extractContractProbeSuite,
  HarnessTraceSchema,
  runExtract,
} from "../../../src/control-plane/contract-probes/cli/index.js";

function writeTrace(spec: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "probes-extract-"));
  const path = join(dir, "trace.json");
  writeFileSync(path, JSON.stringify(spec), "utf-8");
  return path;
}

describe("HarnessTraceSchema", () => {
  test("parses a minimal observation-only trace", () => {
    const parsed = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: {
        terminal: { exitCode: 0, stdout: "ok", stderr: "" },
      },
    });
    expect(parsed.observations.terminal?.exitCode).toBe(0);
    expect(parsed.expectations).toBeUndefined();
  });

  test("parses observations + expectations and accepts regex strings", () => {
    const parsed = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: {
        terminal: { exitCode: 0, stdout: "All checks passed.", stderr: "" },
        workdir: { presentFiles: ["solution.txt", "trace.log"] },
      },
      expectations: {
        terminal: { expectedExitCode: 0, requiredStdoutPatterns: ["checks passed"] },
        directory: {
          requiredFiles: ["solution.txt"],
          allowedFiles: ["solution.txt"],
          ignoredPatterns: ["^trace\\."],
        },
      },
    });
    expect(parsed.expectations?.terminal?.requiredStdoutPatterns?.[0]).toBeInstanceOf(RegExp);
    expect(parsed.expectations?.directory?.ignoredPatterns?.[0]).toBeInstanceOf(RegExp);
  });

  test("rejects unknown keys at the trace envelope", () => {
    const result = HarnessTraceSchema.safeParse({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "", stderr: "" } },
      extra: "ignored",
    });
    expect(result.success).toBe(false);
  });

  test("rejects unknown keys nested inside an observation", () => {
    const result = HarnessTraceSchema.safeParse({
      schema_version: 1,
      observations: {
        terminal: { exitCode: 0, stdout: "", stderr: "", surprise: 1 },
      },
    });
    expect(result.success).toBe(false);
  });

  test("safeParse returns { success: false } for an invalid regex pattern", () => {
    const result = HarnessTraceSchema.safeParse({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "", stderr: "" } },
      expectations: { terminal: { requiredStdoutPatterns: ["[unclosed"] } },
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(
        result.error.issues.some((i) => i.message.includes("invalid regular expression")),
      ).toBe(true);
    }
  });
});

describe("extractContractProbeSuite", () => {
  test("an observations-only trace produces probes with no declared expectations", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "ok", stderr: "" } },
    });
    const suite = extractContractProbeSuite(trace);
    expect(suite.probes.map((p) => p.kind)).toEqual(["terminal"]);
    // With no terminal expectation, the terminal probe's `expectedExitCode`
    // defaults to 0 -- so exitCode=0 still passes.
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(true);
  });

  test("observation-only workdir fails by default (no allowlist declared)", () => {
    // The directory probe's contract is "files must be on the allowlist".
    // A trace with workdir observations but no directory expectations
    // produces a probe with empty `allowedFiles`, so every present file is
    // unexpected. This is intended: it prompts the operator to declare an
    // allowlist rather than silently passing.
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: { workdir: { presentFiles: ["a.txt"] } },
    });
    const suite = extractContractProbeSuite(trace);
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(false);
    const probe = result.results[0];
    if (probe.kind !== "directory") {
      throw new Error("expected directory");
    }
    expect(probe.failures[0].kind).toBe("unexpected-file");
  });

  test("joins terminal observation + expectation into a single probe", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "done", stderr: "" } },
      expectations: { terminal: { expectedExitCode: 0, requiredStdoutPatterns: ["done"] } },
    });
    const suite = extractContractProbeSuite(trace);
    expect(suite.probes).toHaveLength(1);
    const probe = suite.probes[0];
    if (probe.kind !== "terminal") {
      throw new Error("expected terminal");
    }
    expect(probe.inputs.expectedExitCode).toBe(0);
    expect(runContractProbeSuite(suite).passed).toBe(true);
  });

  test("joins workdir observation + directory expectation; ignoredPatterns flow through", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: {
        workdir: { presentFiles: ["solution.txt", "trace.log"] },
      },
      expectations: {
        directory: {
          requiredFiles: ["solution.txt"],
          allowedFiles: ["solution.txt"],
          ignoredPatterns: ["^trace\\."],
        },
      },
    });
    const suite = extractContractProbeSuite(trace);
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(true);
  });

  test("flags unexpected files when the directory expectation omits the ignore", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: { workdir: { presentFiles: ["solution.txt", "trace.log"] } },
      expectations: {
        directory: { requiredFiles: ["solution.txt"], allowedFiles: ["solution.txt"] },
      },
    });
    const suite = extractContractProbeSuite(trace);
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(false);
    const probe = result.results[0];
    if (probe.kind !== "directory") {
      throw new Error("expected directory");
    }
    expect(probe.failures[0].kind).toBe("unexpected-file");
    expect(probe.failures[0].path).toBe("trace.log");
  });

  test("matches per-artifact expectations by path", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: {
        artifacts: [
          { path: "manifest.json", content: JSON.stringify({ name: "x" }) },
          { path: "notes.txt", content: "hello\n" },
        ],
      },
      expectations: {
        artifacts: [
          { path: "manifest.json", requiredJsonFields: ["name", "version"] },
          { path: "notes.txt", requiredSubstrings: ["hello"] },
        ],
      },
    });
    const suite = extractContractProbeSuite(trace);
    expect(suite.probes).toHaveLength(2);
    const result = runContractProbeSuite(suite);
    // manifest.json is missing "version" -> fail; notes.txt has "hello" -> pass.
    expect(result.passed).toBe(false);
    const manifestProbe = result.results[0];
    if (manifestProbe.kind !== "artifact") {
      throw new Error("expected artifact");
    }
    expect(manifestProbe.failures[0].kind).toBe("missing-json-field");
    expect(manifestProbe.failures[0].path).toBe("version");
  });

  test("emits an artifact probe with no expectations when the trace doesn't list one for that path", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      observations: {
        artifacts: [{ path: "extra.txt", content: "" }],
      },
      expectations: {
        artifacts: [{ path: "other.txt", requiredSubstrings: ["x"] }],
      },
    });
    const suite = extractContractProbeSuite(trace);
    expect(suite.probes).toHaveLength(1);
    const probe = suite.probes[0];
    if (probe.kind !== "artifact") {
      throw new Error("expected artifact");
    }
    expect(probe.inputs.path).toBe("extra.txt");
    expect(probe.inputs.requiredSubstrings).toBeUndefined();
  });

  test("end-to-end: extracted suite passes ContractProbeSuiteSchema and runs through runner", () => {
    const trace = HarnessTraceSchema.parse({
      schema_version: 1,
      label: "smoke-run-2026-05-22",
      observations: {
        terminal: { exitCode: 0, stdout: "All checks passed.", stderr: "" },
        workdir: { presentFiles: ["solution.txt"] },
        services: [{ host: "127.0.0.1", port: 8080, protocol: "tcp" }],
      },
      expectations: {
        terminal: { expectedExitCode: 0, requiredStdoutPatterns: ["checks passed"] },
        directory: { requiredFiles: ["solution.txt"], allowedFiles: ["solution.txt"] },
        services: { required: [{ host: "127.0.0.1", port: 8080, protocol: "tcp" }] },
      },
    });
    const suite = extractContractProbeSuite(trace);
    // Round-trip the suite through its own schema to confirm the extractor
    // produces a runnable, fully-validated ContractProbeSuite (not just a
    // structurally-similar TypeScript value).
    const reparsed = ContractProbeSuiteSchema.parse(
      JSON.parse(
        JSON.stringify(suite, (_k, v) =>
          v instanceof RegExp ? { source: v.source, flags: v.flags } : v,
        ),
      ),
    );
    const result = runContractProbeSuite(reparsed);
    expect(result.passed).toBe(true);
    expect(result.results.every((r) => r.label === "smoke-run-2026-05-22")).toBe(true);
  });
});

describe("runExtract", () => {
  test("--help prints subcommand help and exits 0", async () => {
    const result = await runExtract(["--help"]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe(EXTRACT_HELP_TEXT);
  });

  test("missing --trace exits 1 with a helpful message", async () => {
    const result = await runExtract([]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("--trace <path> is required");
  });

  test("non-existent trace path exits 1", async () => {
    const result = await runExtract(["--trace", "/no/such/file.json"]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("failed to read trace");
  });

  test("malformed JSON trace exits 1", async () => {
    const dir = mkdtempSync(join(tmpdir(), "probes-extract-"));
    const path = join(dir, "bad.json");
    writeFileSync(path, "{not valid", "utf-8");
    const result = await runExtract(["--trace", path]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("invalid JSON");
  });

  test("schema-invalid trace exits 1 with Zod issues", async () => {
    const path = writeTrace({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "", stderr: "", typo: 1 } },
    });
    const result = await runExtract(["--trace", path]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("validation failed");
  });

  test("emits the suite to stdout when --output is not supplied", async () => {
    const path = writeTrace({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "ok", stderr: "" } },
      expectations: { terminal: { expectedExitCode: 0 } },
    });
    const result = await runExtract(["--trace", path]);
    expect(result.exitCode).toBe(0);
    const suite = JSON.parse(result.stdout) as {
      schema_version: number;
      probes: { kind: string }[];
    };
    expect(suite.schema_version).toBe(1);
    expect(suite.probes[0].kind).toBe("terminal");
  });

  test("writes the suite to --output when supplied; report on stdout", async () => {
    const path = writeTrace({
      schema_version: 1,
      observations: { terminal: { exitCode: 0, stdout: "ok", stderr: "" } },
    });
    const dir = mkdtempSync(join(tmpdir(), "probes-extract-out-"));
    const outPath = join(dir, "nested", "suite.json");
    const result = await runExtract(["--trace", path, "--output", outPath]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain(`wrote suite to ${outPath}`);
    const written = JSON.parse(readFileSync(outPath, "utf-8")) as {
      schema_version: number;
      probes: unknown[];
    };
    expect(written.schema_version).toBe(1);
  });

  test("end-to-end: emitted suite passes the slice-5 suite-runner schema", async () => {
    // The serialized suite must be valid input for `loadContractProbeSuite`
    // / `ContractProbeSuiteSchema.parse`. RegExp values are serialized as
    // `{ source, flags }` objects so the runner schema can re-parse them.
    const path = writeTrace({
      schema_version: 1,
      observations: { workdir: { presentFiles: ["solution.txt"] } },
      expectations: {
        directory: {
          requiredFiles: ["solution.txt"],
          allowedFiles: ["solution.txt"],
          ignoredPatterns: ["^trace\\."],
        },
      },
    });
    const result = await runExtract(["--trace", path]);
    expect(result.exitCode).toBe(0);
    const raw = JSON.parse(result.stdout) as unknown;
    const suite = ContractProbeSuiteSchema.parse(raw);
    const probe = suite.probes[0];
    if (probe.kind !== "directory") {
      throw new Error("expected directory");
    }
    expect(probe.inputs.ignoredPatterns?.[0]).toBeInstanceOf(RegExp);
    expect(runContractProbeSuite(suite).passed).toBe(true);
  });
});
