import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { parseGoalRunReport, type GoalRunReport } from "../analytics/goal-run-report.js";

export function goalRunReportPath(knowledgeRoot: string, goalId: string, goalRunId: string): string {
  return join(
    knowledgeRoot,
    "goal_runs",
    pathSegment(goalId, "goalId"),
    `${pathSegment(goalRunId, "goalRunId")}.json`,
  );
}

function pathSegment(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} is required`);
  if (
    normalized === "." ||
    normalized === ".." ||
    normalized.includes("/") ||
    normalized.includes("\\") ||
    basename(normalized) !== normalized
  ) {
    throw new Error(`${label} must be a single path segment`);
  }
  return normalized;
}

export function writeGoalRunReport(
  knowledgeRoot: string,
  goalId: string,
  goalRunId: string,
  report: GoalRunReport,
): string {
  const path = goalRunReportPath(knowledgeRoot, goalId, goalRunId);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(report, null, 2) + "\n", "utf-8");
  return path;
}

export function readGoalRunReport(knowledgeRoot: string, goalId: string, goalRunId: string): GoalRunReport | null {
  const path = goalRunReportPath(knowledgeRoot, goalId, goalRunId);
  return existsSync(path) ? parseGoalRunReport(JSON.parse(readFileSync(path, "utf-8")) as unknown) : null;
}
