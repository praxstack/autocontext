#!/usr/bin/env node
/** Bundle-size budget check for `autoctx/integrations/anthropic`. */
import { NODE_BUILTINS_WITH_ASYNC, runEsbuildBundleCheck } from "./bundle-size-check.mjs";

await runEsbuildBundleCheck({
  entry: "src/integrations/anthropic/index.ts",
  budgetBytes: 40_960,
  tmpPrefix: "autoctx-integrations-anthropic-bundle-",
  consoleHeader: "autoctx/integrations/anthropic",
  reportTitle: "autoctx/integrations/anthropic bundle report",
  reportSeparator: "---------------------------------------------",
  reportFile: "bundle-integrations-anthropic-report.txt",
  external: [
    ...NODE_BUILTINS_WITH_ASYNC,
    "@anthropic-ai/sdk",
    "ajv",
    "ajv/dist/2020.js",
    "ajv-formats",
    "ulid",
  ],
  failureDetail:
    "\n  Re-run with --report to see the top contributors, or bump BUDGET_BYTES in\n" +
    "  scripts/check-integrations-anthropic-bundle-size.mjs if the addition is\n" +
    "  intentional and justified in the PR description.",
});
