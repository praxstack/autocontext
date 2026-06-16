import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

export const NODE_BUILTINS = [
  "node:crypto",
  "node:fs",
  "node:fs/promises",
  "node:path",
  "node:url",
  "node:os",
  "node:zlib",
  "node:child_process",
  "node:stream",
  "node:util",
];

export const NODE_BUILTINS_WITH_ASYNC = ["node:async_hooks", ...NODE_BUILTINS];

export function runDistGzipCheck({ distFile, label, budgetKb }) {
  const file = join(ROOT, distFile);
  if (!existsSync(file)) {
    console.log("SKIP — dist not built yet. Run `npm run build` first.");
    process.exit(0);
  }

  const gz = gzipSync(readFileSync(file));
  const kb = (gz.length / 1024).toFixed(1);

  if (gz.length / 1024 > budgetKb) {
    console.error(`FAIL — ${label}: ${kb} KB gzipped exceeds budget of ${budgetKb} KB.`);
    process.exit(1);
  }

  console.log(`OK — ${label}: ${kb} KB gzipped (under ${budgetKb} KB budget).`);
}

export async function runEsbuildBundleCheck({
  entry,
  budgetBytes,
  tmpPrefix,
  consoleHeader = "",
  reportTitle,
  reportSeparator,
  reportFile,
  external = [],
  failureDetail = "",
}) {
  const args = new Set(process.argv.slice(2));
  const wantReport = args.has("--report");
  const wantJson = args.has("--json");

  const tmp = mkdtempSync(join(tmpdir(), tmpPrefix));
  const outFile = join(tmp, "bundle.js");
  let metafile;

  try {
    const { build } = await import("esbuild");
    const result = await build({
      entryPoints: [join(ROOT, entry)],
      bundle: true,
      platform: "neutral",
      target: "es2022",
      format: "esm",
      minify: true,
      treeShaking: true,
      outfile: outFile,
      metafile: true,
      logLevel: "silent",
      external,
      mainFields: ["module", "main"],
      conditions: ["import", "default"],
    });
    metafile = result.metafile;
  } catch (err) {
    console.error("[bundle-size] esbuild failed:", err);
    process.exit(2);
  }

  const raw = readFileSync(outFile);
  const gzipped = gzipSync(raw);
  rmSync(tmp, { recursive: true, force: true });

  const rawBytes = raw.byteLength;
  const gzipBytes = gzipped.byteLength;
  const headroom = budgetBytes - gzipBytes;
  const overBudget = gzipBytes > budgetBytes;

  if (wantJson) {
    process.stdout.write(
      JSON.stringify({ budgetBytes, rawBytes, gzipBytes, headroom, overBudget }) + "\n",
    );
  } else {
    if (consoleHeader) console.log(`[bundle-size] ${consoleHeader}`);
    console.log(`[bundle-size] raw:      ${rawBytes.toLocaleString()} bytes`);
    console.log(`[bundle-size] gzipped:  ${gzipBytes.toLocaleString()} bytes`);
    console.log(`[bundle-size] budget:   ${budgetBytes.toLocaleString()} bytes`);
    console.log(`[bundle-size] headroom: ${headroom.toLocaleString()} bytes`);
  }

  if (wantReport) {
    const topModules = Object.entries(metafile.inputs)
      .map(([path, info]) => ({ path, bytes: info.bytes }))
      .sort((a, b) => b.bytes - a.bytes)
      .slice(0, 20);
    const lines = [
      reportTitle,
      reportSeparator,
      `raw:      ${rawBytes.toLocaleString()} bytes`,
      `gzipped:  ${gzipBytes.toLocaleString()} bytes`,
      `budget:   ${budgetBytes.toLocaleString()} bytes`,
      `headroom: ${headroom.toLocaleString()} bytes`,
      "",
      "top module contributors (raw):",
      ...topModules.map((m) => `  ${String(m.bytes).padStart(8)}  ${m.path}`),
      "",
    ].join("\n");
    writeFileSync(join(ROOT, reportFile), lines, "utf-8");
    console.log(`[bundle-size] wrote ${reportFile}`);
  }

  if (overBudget) {
    console.error(
      `[bundle-size] FAIL — ${gzipBytes - budgetBytes} bytes over the ${budgetBytes}-byte budget.${failureDetail}`,
    );
    process.exit(1);
  }

  if (!wantJson) console.log("[bundle-size] OK — within budget.");
}
