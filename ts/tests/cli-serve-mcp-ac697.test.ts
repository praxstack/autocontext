/**
 * AC-697 slice 6: TS `autoctx serve mcp` canonical path.
 *
 * Slice 1 (PR #981) pinned the canonical contract: `serve mcp` is
 * the canonical path for the MCP server; `mcp-serve` stays as a
 * top-level alias. This slice adds sub-arg dispatch in `cmdServeHttp`:
 * when invoked as `autoctx serve mcp`, it rewrites argv and routes
 * to the existing `cmdMcpServe` handler, so the MCP server logic
 * stays single-sourced.
 *
 * Same delegation pattern as slice 4's `cmdScenario` -> `cmdNewScenario`.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

import { visibleSupportedCommandNames } from "../src/cli/command-registry.js";

describe("AC-697 slice 6: TS `serve mcp` is canonical, `mcp-serve` is alias", () => {
  test("contract: TS `serve.mcp` is `yes`", () => {
    const path = resolve(import.meta.dirname, "..", "..", "docs", "cli-contract.json");
    const contract = JSON.parse(readFileSync(path, "utf-8")) as {
      commands: { id: string; runtime_support: { typescript: { status: string } } }[];
    };
    const serveMcp = contract.commands.find((c) => c.id === "serve.mcp");
    expect(serveMcp).toBeDefined();
    expect(serveMcp!.runtime_support.typescript.status).toBe("yes");
  });

  test("contract: `mcp-serve` is preserved as the slice-1 alias", () => {
    const path = resolve(import.meta.dirname, "..", "..", "docs", "cli-contract.json");
    const contract = JSON.parse(readFileSync(path, "utf-8")) as {
      commands: { id: string; aliases: string[] }[];
    };
    const serveMcp = contract.commands.find((c) => c.id === "serve.mcp");
    expect(serveMcp).toBeDefined();
    expect(serveMcp!.aliases).toContain("mcp-serve");
  });

  test("`serve` and `mcp-serve` are both registered in command-registry", () => {
    const registered = new Set(visibleSupportedCommandNames());
    // Canonical path: `serve` is the top-level command; `serve mcp` is
    // sub-arg dispatch inside cmdServeHttp.
    expect(registered.has("serve")).toBe(true);
    // Legacy alias kept for backward compat with existing Claude
    // Code MCP configurations.
    expect(registered.has("mcp-serve")).toBe(true);
  });
});
