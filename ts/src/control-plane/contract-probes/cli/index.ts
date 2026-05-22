/**
 * Public surface of the autocontext `probes` CLI namespace.
 *
 * Mirrors the production-traces / instrument CLI pattern:
 *   - In-process dispatch, no `process.exit` / `console` inside handlers.
 *   - Handlers return { stdout, stderr, exitCode }; the outer CLI adapter
 *     in ts/src/cli/index.ts prints and exits.
 *   - Tests consume the runner directly for speed (no subprocess spawn).
 *
 * Slice 6 ships the `check` subcommand. A follow-up slice adds
 * `extract <trace>` -- read a recorded trace and synthesize a probe suite
 * by extracting observations.
 */

import { CHECK_HELP_TEXT, runCheck } from "./check.js";
import type { ProbesCheckResult } from "./check.js";

export { CHECK_HELP_TEXT, runCheck };
export type { ProbesCheckResult };

const TOP_HELP = `autoctx probes -- run AC-728 contract probes against observed harness state.

Subcommands:
  check    Run a JSON-defined probe suite and report pass/fail per probe.

Run \`autoctx probes <subcommand> --help\` for details.

The probe library is in ts/src/control-plane/contract-probes/. Each probe
verifies a class of verifier-facing contract bug: terminal exit / output;
final directory allowlist; expected service endpoints; artifact path /
content / line endings / JSON fields; cleanup leftovers (symlinks,
sidecars, lockfiles, backups); media / tabular dimensions, encoding,
headers, and units; distributed / multi-rank parity.
`;

export async function runProbesCommand(args: readonly string[]): Promise<ProbesCheckResult> {
  const subcommand = args[0];
  const rest = args.slice(1);

  if (subcommand === undefined || subcommand === "--help" || subcommand === "-h") {
    return { stdout: TOP_HELP, stderr: "", exitCode: 0 };
  }

  switch (subcommand) {
    case "check":
      return runCheck(rest);
    default:
      return {
        stdout: "",
        stderr: `autoctx probes: unknown subcommand ${JSON.stringify(subcommand)}\n\n${TOP_HELP}`,
        exitCode: 1,
      };
  }
}
