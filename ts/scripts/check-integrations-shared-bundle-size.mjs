#!/usr/bin/env node
/** Bundle-size budget check for `autoctx/integrations/_shared`. */
import { NODE_BUILTINS_WITH_ASYNC, runEsbuildBundleCheck } from "./bundle-size-check.mjs";

await runEsbuildBundleCheck({
  entry: "src/integrations/_shared/index.ts",
  budgetBytes: 15_360,
  tmpPrefix: "autoctx-integrations-shared-bundle-",
  consoleHeader: "autoctx/integrations/_shared",
  reportTitle: "autoctx/integrations/_shared bundle report",
  reportSeparator: "------------------------------------------",
  reportFile: "bundle-integrations-shared-report.txt",
  external: NODE_BUILTINS_WITH_ASYNC,
});
