import { runDistGzipCheck } from "./bundle-size-check.mjs";

runDistGzipCheck({
  distFile: "dist/control-plane/instrument/detectors/anthropic-ts/index.js",
  label: "detector-anthropic-ts",
  budgetKb: 15,
});
