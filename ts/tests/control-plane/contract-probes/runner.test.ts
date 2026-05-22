import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
  ContractProbeSuiteSchema,
  loadContractProbeSuite,
  runContractProbeSuite,
} from "../../../src/control-plane/contract-probes/index.js";
import type { ContractProbeSuite } from "../../../src/control-plane/contract-probes/index.js";

describe("ContractProbeSuiteSchema", () => {
  test("parses a minimal empty suite", () => {
    const parsed = ContractProbeSuiteSchema.parse({ schema_version: 1, probes: [] });
    expect(parsed.probes).toEqual([]);
  });

  test("rejects an unknown probe kind", () => {
    expect(() =>
      ContractProbeSuiteSchema.parse({
        schema_version: 1,
        probes: [{ kind: "nonsense", inputs: {} }],
      }),
    ).toThrow();
  });

  test("rejects schema_version != 1", () => {
    expect(() => ContractProbeSuiteSchema.parse({ schema_version: 99, probes: [] })).toThrow();
  });

  test("transforms string ignoredPatterns into RegExp", () => {
    const parsed = ContractProbeSuiteSchema.parse({
      schema_version: 1,
      probes: [
        {
          kind: "directory",
          inputs: {
            presentFiles: ["a"],
            requiredFiles: ["a"],
            allowedFiles: ["a"],
            ignoredPatterns: ["^trace\\."],
          },
        },
      ],
    });
    const invocation = parsed.probes[0];
    expect(invocation.kind).toBe("directory");
    if (invocation.kind !== "directory") {
      return;
    }
    expect(invocation.inputs.ignoredPatterns?.[0]).toBeInstanceOf(RegExp);
    expect(invocation.inputs.ignoredPatterns?.[0].test("trace.log")).toBe(true);
  });

  test("transforms ISO-8601 strings to Date for cleanup mtime / now", () => {
    const parsed = ContractProbeSuiteSchema.parse({
      schema_version: 1,
      probes: [
        {
          kind: "cleanup",
          inputs: {
            entries: [{ path: "stale.lock", mtime: "2026-05-21T11:00:00Z" }],
            now: "2026-05-21T12:00:00Z",
            maxLockfileAgeMs: 5 * 60 * 1000,
          },
        },
      ],
    });
    const invocation = parsed.probes[0];
    expect(invocation.kind).toBe("cleanup");
    if (invocation.kind !== "cleanup") {
      return;
    }
    expect(invocation.inputs.now).toBeInstanceOf(Date);
    expect(invocation.inputs.entries[0].mtime).toBeInstanceOf(Date);
  });

  test("rejects malformed ISO-8601 strings", () => {
    expect(() =>
      ContractProbeSuiteSchema.parse({
        schema_version: 1,
        probes: [
          {
            kind: "cleanup",
            inputs: {
              entries: [{ path: "x.lock", mtime: "not-a-date" }],
            },
          },
        ],
      }),
    ).toThrow(/invalid ISO-8601 date/);
  });
});

describe("runContractProbeSuite", () => {
  test("an empty suite passes", () => {
    const result = runContractProbeSuite({ schema_version: 1, probes: [] });
    expect(result.passed).toBe(true);
    expect(result.results).toEqual([]);
  });

  test("dispatches every probe kind through the matching probe (all pass)", () => {
    const suite: ContractProbeSuite = ContractProbeSuiteSchema.parse({
      schema_version: 1,
      probes: [
        {
          kind: "directory",
          label: "final-workdir",
          inputs: {
            presentFiles: ["solution.txt"],
            requiredFiles: ["solution.txt"],
            allowedFiles: ["solution.txt"],
          },
        },
        {
          kind: "terminal",
          inputs: { exitCode: 0, stdout: "ok", stderr: "", expectedExitCode: 0 },
        },
        {
          kind: "service",
          inputs: {
            observed: [{ host: "127.0.0.1", port: 8080, protocol: "tcp" }],
            required: [{ host: "127.0.0.1", port: 8080, protocol: "tcp" }],
          },
        },
        {
          kind: "artifact",
          inputs: {
            path: "config.txt",
            content: "key=value\n",
            expectedLineEnding: "lf",
            requiredSubstrings: ["key=value"],
          },
        },
        {
          kind: "cleanup",
          inputs: { entries: [{ path: "solution.txt" }] },
        },
        {
          kind: "media",
          inputs: { path: "rendered.png" },
        },
        {
          kind: "distributed",
          inputs: {
            ranks: [{ rank: 0, steps: 10, observations: { loss: "0.1" } }],
            worldSize: 1,
            expectedWorldSize: 1,
            expectedSteps: 10,
            mustMatchAcrossRanks: ["loss"],
          },
        },
      ],
    });
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(true);
    expect(result.results.map((r) => r.kind)).toEqual([
      "directory",
      "terminal",
      "service",
      "artifact",
      "cleanup",
      "media",
      "distributed",
    ]);
    expect(result.results[0].label).toBe("final-workdir");
    expect(result.results.every((r) => r.passed)).toBe(true);
  });

  test("suite passed is the AND of per-probe passes", () => {
    const suite = ContractProbeSuiteSchema.parse({
      schema_version: 1,
      probes: [
        {
          kind: "terminal",
          label: "ok",
          inputs: { exitCode: 0, stdout: "", stderr: "" },
        },
        {
          kind: "terminal",
          label: "bad",
          inputs: { exitCode: 1, stdout: "", stderr: "" },
        },
      ],
    });
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(false);
    expect(result.results[0].passed).toBe(true);
    expect(result.results[1].passed).toBe(false);
    expect(result.results[1].failures[0].kind).toBe("unexpected-exit-code");
  });

  test("failure entries carry through the kind + label so callers can attribute the report", () => {
    const suite = ContractProbeSuiteSchema.parse({
      schema_version: 1,
      probes: [
        {
          kind: "cleanup",
          label: "after-build",
          inputs: { entries: [{ path: ".DS_Store" }] },
        },
      ],
    });
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(false);
    expect(result.results[0].kind).toBe("cleanup");
    expect(result.results[0].label).toBe("after-build");
    expect(result.results[0].failures[0].kind).toBe("stray-sidecar");
  });
});

describe("loadContractProbeSuite", () => {
  test("reads + parses a JSON file from disk", () => {
    const dir = mkdtempSync(join(tmpdir(), "probe-suite-"));
    const path = join(dir, "suite.json");
    writeFileSync(
      path,
      JSON.stringify({
        schema_version: 1,
        probes: [
          {
            kind: "directory",
            label: "final",
            inputs: {
              presentFiles: ["a.txt"],
              requiredFiles: ["a.txt"],
              allowedFiles: ["a.txt"],
            },
          },
        ],
      }),
      "utf-8",
    );
    const suite = loadContractProbeSuite(path);
    expect(suite.probes).toHaveLength(1);
    expect(suite.probes[0].kind).toBe("directory");
    const result = runContractProbeSuite(suite);
    expect(result.passed).toBe(true);
  });

  test("throws when the file does not exist", () => {
    expect(() => loadContractProbeSuite("/no/such/file.json")).toThrow();
  });

  test("throws when the file is malformed JSON", () => {
    const dir = mkdtempSync(join(tmpdir(), "probe-suite-"));
    const path = join(dir, "bad.json");
    writeFileSync(path, "{not valid", "utf-8");
    expect(() => loadContractProbeSuite(path)).toThrow();
  });
});
