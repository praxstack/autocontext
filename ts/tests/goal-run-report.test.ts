import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  buildGoalRunReport,
  parseGoalRunReport,
  type BuildGoalRunReportInput,
  type GoalRunReport,
} from "../src/analytics/goal-run-report.js";
import {
  readGoalRunReport,
  writeGoalRunReport,
} from "../src/knowledge/goal-run-report-store.js";

const fixture = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "..", "docs", "goal-run-report-parity-fixture.json"), "utf-8"),
) as {
  cases: Array<
    BuildGoalRunReportInput & {
      name: string;
      expected_report: GoalRunReport;
    }
  >;
};

describe("goal run report", () => {
  it("matches the shared Python/TypeScript parity fixture", () => {
    for (const item of fixture.cases) {
      expect(buildGoalRunReport(item)).toEqual(item.expected_report);
    }
  });

  it("parses durable report JSON and rejects schema-invalid data", () => {
    const report = fixture.cases[0]!.expected_report;
    const { max_iterations: _maxIterations, ...missingBudgetField } = report.budget;

    expect(parseGoalRunReport(report)).toEqual(report);
    expect(() => parseGoalRunReport({ ...report, surprise: true })).toThrow(/unexpected field/);
    expect(() => parseGoalRunReport({ ...report, goal_id: "" })).toThrow(/goal_id/);
    expect(() => parseGoalRunReport({ ...report, budget: missingBudgetField })).toThrow(/missing field/);
    expect(() =>
      parseGoalRunReport({ ...report, usage: { ...report.usage, iterations: -1 } }),
    ).toThrow(/iterations/);
    expect(() =>
      parseGoalRunReport({ ...report, actions: [{ ...report.actions[0]!, action_kind: "unknown" }] }),
    ).toThrow(/action_kind/);
    expect(() => parseGoalRunReport({ ...report, status: "active" })).toThrow(/status/);
  });

  it("covers terminal and continued statuses", () => {
    expect(new Set(fixture.cases.map((item) => item.expected_report.status))).toEqual(
      new Set([
        "continued",
        "verified_complete",
        "blocked",
        "budget_exhausted",
        "verifier_failed",
        "no_progress",
        "canceled",
      ]),
    );
  });

  it("persists goal run reports for resume", () => {
    const root = mkdtempSync(join(tmpdir(), "goal-run-"));
    try {
      const report = parseGoalRunReport(fixture.cases[0]!.expected_report);
      const knowledgeRoot = join(root, "knowledge");

      writeGoalRunReport(knowledgeRoot, report.goal_id, report.goal_run_id, report);

      expect(readGoalRunReport(knowledgeRoot, report.goal_id, report.goal_run_id)).toEqual(report);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects path traversal through file helper identifiers", () => {
    const root = mkdtempSync(join(tmpdir(), "goal-run-"));
    try {
      const report = parseGoalRunReport(fixture.cases[0]!.expected_report);
      const knowledgeRoot = join(root, "knowledge");

      expect(() => writeGoalRunReport(knowledgeRoot, "../../../outside", report.goal_run_id, report)).toThrow(
        /goalId/,
      );
      expect(() => writeGoalRunReport(knowledgeRoot, report.goal_id, "../../../outside", report)).toThrow(
        /goalRunId/,
      );
      expect(existsSync(join(root, "outside.json"))).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
