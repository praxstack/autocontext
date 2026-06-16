#!/usr/bin/env node
/** Bundle-size budget check for `autoctx/integrations/openai`. */
import { NODE_BUILTINS_WITH_ASYNC, runEsbuildBundleCheck } from "./bundle-size-check.mjs";

await runEsbuildBundleCheck({
  entry: "src/integrations/openai/index.ts",
  budgetBytes: 40_960,
  tmpPrefix: "autoctx-integrations-openai-bundle-",
  consoleHeader: "autoctx/integrations/openai",
  reportTitle: "autoctx/integrations/openai bundle report",
  reportSeparator: "------------------------------------------",
  reportFile: "bundle-integrations-openai-report.txt",
  external: [
    ...NODE_BUILTINS_WITH_ASYNC,
    "openai",
    "ajv",
    "ajv/dist/2020.js",
    "ajv-formats",
    "ulid",
  ],
  failureDetail:
    "\n  Re-run with --report to see the top contributors, or bump BUDGET_BYTES in\n" +
    "  scripts/check-integrations-openai-bundle-size.mjs if the addition is\n" +
    "  intentional and justified in the PR description.",
});
