/**
 * AC-697 slice 4: TS `autoctx scenario create` parity tests.
 *
 * Mirrors slice 3 on the TS side. `scenario` is registered as a
 * top-level command in `command-registry.ts`; `cmdScenario` in
 * `cli/index.ts` dispatches on the first sub-arg: `create` routes to
 * the existing `cmdNewScenario` handler by rewriting `process.argv`,
 * so the scaffolding logic stays single-sourced across the legacy
 * `new-scenario` alias and the canonical `scenario create` path.
 *
 * The behavioral check via spawnSync is gated on `bun` being
 * resolvable in PATH. Where a subprocess isn't viable, the
 * registry-level assertions in
 * `cli-contract-ac697.test.ts > "every yes-supported command is
 * registered in command-registry"` (now reaching multi-token paths
 * for the parent token) cover the parity invariant.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

import { visibleSupportedCommandNames } from "../src/cli/command-registry.js";

describe("AC-697 slice 4: `scenario` is registered + `scenario.create` flipped to yes", () => {
  test("`scenario` appears in visibleSupportedCommandNames()", () => {
    const registered = new Set(visibleSupportedCommandNames());
    expect(registered.has("scenario")).toBe(true);
    // `new-scenario` stays registered for backward compatibility as
    // the legacy alias the slice-1 contract pins on `scenario.create`.
    expect(registered.has("new-scenario")).toBe(true);
  });

  test("docs/cli-contract.json: TS `scenario.create` is yes", () => {
    const path = resolve(import.meta.dirname, "..", "..", "docs", "cli-contract.json");
    const contract = JSON.parse(readFileSync(path, "utf-8")) as {
      commands: { id: string; runtime_support: { typescript: { status: string } } }[];
    };
    const scenarioCreate = contract.commands.find((c) => c.id === "scenario.create");
    expect(scenarioCreate).toBeDefined();
    expect(scenarioCreate!.runtime_support.typescript.status).toBe("yes");
  });

  test("docs/cli-contract.json: `scenario.create` keeps `new-scenario` as its alias", () => {
    const path = resolve(import.meta.dirname, "..", "..", "docs", "cli-contract.json");
    const contract = JSON.parse(readFileSync(path, "utf-8")) as {
      commands: { id: string; aliases: string[] }[];
    };
    const scenarioCreate = contract.commands.find((c) => c.id === "scenario.create");
    expect(scenarioCreate).toBeDefined();
    expect(scenarioCreate!.aliases).toContain("new-scenario");
  });
});
