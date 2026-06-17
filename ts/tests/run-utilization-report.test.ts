import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  buildRunUtilizationReport,
  parseRunUtilizationReport,
  type RunUtilizationEventInput,
  type RunUtilizationReport,
  type RunUtilizationRoleUsageInput,
} from "../src/analytics/run-utilization-report.js";

const reportSchema = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "..", "docs", "run-utilization-report.json"), "utf-8"),
) as { required?: string[] };

const fixture = JSON.parse(
  readFileSync(
    join(import.meta.dirname, "..", "..", "docs", "run-utilization-report-parity-fixture.json"),
    "utf-8",
  ),
) as {
  cases: Array<{
    name: string;
    run_id: string;
    generated_at: string;
    events: RunUtilizationEventInput[];
    role_usage: RunUtilizationRoleUsageInput[];
    expected_report: RunUtilizationReport;
  }>;
};

describe("run utilization report", () => {
  it("matches the shared Python/TypeScript parity fixture", () => {
    for (const item of fixture.cases) {
      expect(
        buildRunUtilizationReport({
          runId: item.run_id,
          generatedAt: item.generated_at,
          events: item.events,
          roleUsage: item.role_usage,
        }),
      ).toEqual(item.expected_report);
    }
  });

  it("parses durable report JSON and rejects extra fields", () => {
    const report = fixture.cases[1]!.expected_report;

    expect(parseRunUtilizationReport(report)).toEqual(report);
    expect(reportSchema.required).toContain("token_utilization");
    expect(reportSchema.required).toContain("evaluation_utilization");
    expect(() => parseRunUtilizationReport({ ...report, surprise: true })).toThrow(/unexpected field/);
    expect(() => parseRunUtilizationReport({ ...report, run_id: "" })).toThrow(/run_id/);
  });
});
