import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
  CHECK_HELP_TEXT,
  runCheck,
  runProbesCommand,
} from "../../../src/control-plane/contract-probes/cli/index.js";

function writeSuite(spec: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "probes-cli-"));
  const path = join(dir, "suite.json");
  writeFileSync(path, JSON.stringify(spec), "utf-8");
  return path;
}

describe("runProbesCommand", () => {
  test("no subcommand prints top-level help and exits 0", async () => {
    const result = await runProbesCommand([]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("autoctx probes");
    expect(result.stdout).toContain("check");
  });

  test("--help prints top-level help and exits 0", async () => {
    const result = await runProbesCommand(["--help"]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("Subcommands:");
  });

  test("unknown subcommand exits 1 with the top-level help on stderr", async () => {
    const result = await runProbesCommand(["nonsense"]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("unknown subcommand");
  });

  test("dispatches check to runCheck", async () => {
    const path = writeSuite({ schema_version: 1, probes: [] });
    const result = await runProbesCommand(["check", "--suite", path]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toMatch(/PASS/);
  });
});

describe("runCheck", () => {
  test("--help prints subcommand help and exits 0", async () => {
    const result = await runCheck(["--help"]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toBe(CHECK_HELP_TEXT);
  });

  test("missing --suite exits 1 with a helpful message", async () => {
    const result = await runCheck([]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("--suite <path> is required");
  });

  test("non-existent suite path exits 1", async () => {
    const result = await runCheck(["--suite", "/no/such/file.json"]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("failed to load suite");
  });

  test("malformed JSON suite exits 1", async () => {
    const dir = mkdtempSync(join(tmpdir(), "probes-cli-"));
    const path = join(dir, "bad.json");
    writeFileSync(path, "{not valid", "utf-8");
    const result = await runCheck(["--suite", path]);
    expect(result.exitCode).toBe(1);
  });

  test("schema-invalid suite exits 1 and renders Zod issues on stderr", async () => {
    // Typo: requiredStdoutPattern (missing trailing s) is rejected by strict
    // schemas. The CLI should surface every Zod issue rather than crash.
    const path = writeSuite({
      schema_version: 1,
      probes: [
        {
          kind: "terminal",
          inputs: {
            exitCode: 0,
            stdout: "",
            stderr: "",
            requiredStdoutPattern: ["expected"],
          },
        },
      ],
    });
    const result = await runCheck(["--suite", path]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("validation failed");
  });

  test("passing suite returns exit 0 with a text PASS report by default", async () => {
    const path = writeSuite({
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
      ],
    });
    const result = await runCheck(["--suite", path]);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("probes check: PASS");
    expect(result.stdout).toContain("directory [final-workdir]: pass");
  });

  test("failing suite returns exit 1 with per-probe FAIL detail", async () => {
    const path = writeSuite({
      schema_version: 1,
      probes: [
        {
          kind: "terminal",
          label: "after-build",
          inputs: { exitCode: 1, stdout: "", stderr: "boom" },
        },
      ],
    });
    const result = await runCheck(["--suite", path]);
    expect(result.exitCode).toBe(1);
    expect(result.stdout).toContain("probes check: FAIL");
    expect(result.stdout).toContain("terminal [after-build]: fail");
    expect(result.stdout).toContain("unexpected-exit-code");
  });

  test("--json emits a structured ContractProbeSuiteResult payload", async () => {
    const path = writeSuite({
      schema_version: 1,
      probes: [
        {
          kind: "cleanup",
          label: "after-build",
          inputs: { entries: [{ path: ".DS_Store" }] },
        },
      ],
    });
    const result = await runCheck(["--suite", path, "--json"]);
    expect(result.exitCode).toBe(1);
    const payload = JSON.parse(result.stdout) as {
      passed: boolean;
      results: { kind: string; label?: string; passed: boolean; failures: { kind: string }[] }[];
    };
    expect(payload.passed).toBe(false);
    expect(payload.results).toHaveLength(1);
    expect(payload.results[0].kind).toBe("cleanup");
    expect(payload.results[0].label).toBe("after-build");
    expect(payload.results[0].failures[0].kind).toBe("stray-sidecar");
  });

  // PR #992 review (P3): the help text advertises
  // `autoctx probes extract | autoctx probes check --suite -`, but the
  // previous version of check.ts called `readFileSync(path)` and treated
  // `-` as a literal filename (ENOENT). The pipe form now reads from
  // stdin via `readFileSync(0, "utf-8")`, which works cross-platform
  // (unlike `/dev/stdin`, which is unix-only).
  test("the help text documents the --suite - stdin form", () => {
    expect(CHECK_HELP_TEXT).toContain("--suite -");
    expect(CHECK_HELP_TEXT).toMatch(/stdin/);
  });

  test("--suite - reads the suite from stdin end-to-end via a spawned CLI", async () => {
    // Verify the actual `extract | check` pipe works by spawning the real
    // TypeScript CLI source. We use tsx via bun's node compat so this
    // does not require a prior build step. The test is gated on bun
    // being available in PATH (it always is in this repo's CI).
    const { spawnSync } = await import("node:child_process");
    const { resolve } = await import("node:path");
    const cliEntry = resolve(import.meta.dirname, "..", "..", "..", "src", "cli", "index.ts");
    const suite = JSON.stringify({
      schema_version: 1,
      probes: [
        {
          kind: "terminal",
          inputs: { exitCode: 0, stdout: "ok", stderr: "" },
        },
      ],
    });
    const result = spawnSync("bun", [cliEntry, "probes", "check", "--suite", "-"], {
      input: suite,
      encoding: "utf-8",
    });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("probes check: PASS");
  });
});
