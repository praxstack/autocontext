import { runDistGzipCheck } from "./bundle-size-check.mjs";

runDistGzipCheck({
  distFile: "dist/control-plane/instrument/detectors/anthropic-python/index.js",
  label: "detector-anthropic-python",
  budgetKb: 15,
});
