#!/usr/bin/env node
/** Bundle-size budget check for `autoctx/production-traces`. */
import { NODE_BUILTINS, runEsbuildBundleCheck } from "./bundle-size-check.mjs";

await runEsbuildBundleCheck({
  entry: "src/production-traces/sdk/index.ts",
  budgetBytes: 102_400,
  tmpPrefix: "autoctx-sdk-bundle-",
  reportTitle: "autoctx/production-traces bundle report",
  reportSeparator: "---------------------------------------",
  reportFile: "bundle-report.txt",
  external: NODE_BUILTINS,
  failureDetail:
    "\n  Re-run with --report to see the top contributors, or bump BUDGET_BYTES in\n" +
    "  scripts/check-production-traces-sdk-bundle-size.mjs if the addition is\n" +
    "  intentional and justified in the PR description.",
});
