import { runDistGzipCheck } from "./bundle-size-check.mjs";

runDistGzipCheck({
  distFile: "dist/control-plane/instrument/detectors/openai-python/index.js",
  label: "detector-openai-python",
  budgetKb: 15,
});
