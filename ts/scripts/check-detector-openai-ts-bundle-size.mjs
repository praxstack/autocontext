import { runDistGzipCheck } from "./bundle-size-check.mjs";

runDistGzipCheck({
  distFile: "dist/control-plane/instrument/detectors/openai-ts/index.js",
  label: "detector-openai-ts",
  budgetKb: 15,
});
