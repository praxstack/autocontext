import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { ArtifactStore } from "../src/knowledge/artifact-store.js";
import { LessonStore, makeMeta } from "../src/knowledge/lessons.js";
import { buildKnowledgeApiRoutes } from "../src/server/knowledge-api.js";
import { StartRunCmdSchema } from "../src/server/protocol.js";

function root(): string {
  return mkdtempSync(join(tmpdir(), "playbook-approval-"));
}

function store(dir: string): ArtifactStore {
  return new ArtifactStore({ runsRoot: join(dir, "runs"), knowledgeRoot: join(dir, "knowledge") });
}

describe("playbook approval gate", () => {
  it("accepts playbook approval flag and deprecated lesson alias", () => {
    expect(
      StartRunCmdSchema.parse({
        type: "start_run",
        scenario: "grid_ctf",
        generations: 1,
        require_playbook_approval: true,
      }).require_playbook_approval,
    ).toBe(true);
    expect(
      StartRunCmdSchema.parse({
        type: "start_run",
        scenario: "grid_ctf",
        generations: 1,
        require_lesson_approval: true,
      }).require_lesson_approval,
    ).toBe(true);
  });

  it("defaults off and writes playbooks live", () => {
    const dir = root();
    try {
      const artifacts = store(dir);
      artifacts.writePlaybook("grid_ctf", "approved playbook");

      const result = artifacts.writeOrStagePlaybook("grid_ctf", "pending playbook", {
        requireApproval: false,
        sourceRunId: "run-approval",
        generation: 2,
        curatorDecision: "advance",
      });

      expect(result).toBe("live");
      expect(artifacts.readPlaybook("grid_ctf")).toBe("pending playbook\n");
      expect(artifacts.readPendingPlaybook("grid_ctf").hasPending).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("refuses to overwrite an unresolved pending playbook", () => {
    const dir = root();
    try {
      const artifacts = store(dir);
      artifacts.writePlaybook("grid_ctf", "approved playbook");
      artifacts.writeOrStagePlaybook("grid_ctf", "pending playbook", {
        requireApproval: true,
        sourceRunId: "run-approval",
        generation: 2,
        curatorDecision: "advance",
      });

      expect(() =>
        artifacts.writeOrStagePlaybook("grid_ctf", "new pending playbook", {
          requireApproval: true,
          sourceRunId: "run-approval",
          generation: 3,
          curatorDecision: "advance",
        }),
      ).toThrow(/pending playbook already exists/);
      expect(artifacts.readPendingPlaybook("grid_ctf").content).toBe("pending playbook\n");
      expect(artifacts.readPendingPlaybook("grid_ctf").provenance?.generation).toBe(2);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("stages pending playbooks without touching approved playbook", () => {
    const dir = root();
    try {
      const artifacts = store(dir);
      artifacts.writePlaybook("grid_ctf", "approved playbook");

      const result = artifacts.writeOrStagePlaybook("grid_ctf", "pending playbook", {
        requireApproval: true,
        sourceRunId: "run-approval",
        generation: 2,
        curatorDecision: "advance",
      });

      expect(result).toBe("pending");
      expect(artifacts.readPlaybook("grid_ctf")).toBe("approved playbook\n");
      const pending = artifacts.readPendingPlaybook("grid_ctf");
      expect(pending.hasPending).toBe(true);
      expect(pending.content).toBe("pending playbook\n");
      expect(pending.diff).toContain("-approved playbook");
      expect(pending.diff).toContain("+pending playbook");
      expect(pending.provenance?.source_run_id).toBe("run-approval");
      expect(pending.provenance?.generation).toBe(2);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("approves or rejects pending playbooks with same-generation lessons", () => {
    const dir = root();
    try {
      const artifacts = store(dir);
      const lessons = new LessonStore(join(dir, "knowledge"));
      artifacts.writePlaybook("grid_ctf", "approved playbook");
      lessons.addLesson(
        "grid_ctf",
        "held lesson",
        makeMeta({ generation: 2, bestScore: 0.7, approvalStatus: "pending" }),
      );
      artifacts.writeOrStagePlaybook("grid_ctf", "pending playbook", {
        requireApproval: true,
        sourceRunId: "run-approval",
        generation: 2,
        curatorDecision: "advance",
      });

      expect(artifacts.approvePendingPlaybook("grid_ctf", lessons)).toEqual({
        ok: true,
        status: "approved",
      });
      expect(artifacts.readPlaybook("grid_ctf")).toBe("pending playbook\n");
      expect(lessons.readLessons("grid_ctf")[0]!.meta.approvalStatus).toBe("active");

      artifacts.writeOrStagePlaybook("grid_ctf", "rejected playbook", {
        requireApproval: true,
        sourceRunId: "run-approval",
        generation: 3,
        curatorDecision: "advance",
      });
      lessons.addLesson(
        "grid_ctf",
        "rejected lesson",
        makeMeta({ generation: 3, bestScore: 0.8, approvalStatus: "pending" }),
      );

      expect(artifacts.rejectPendingPlaybook("grid_ctf", lessons)).toEqual({
        ok: true,
        status: "rejected",
      });
      expect(artifacts.readPlaybook("grid_ctf")).toBe("pending playbook\n");
      expect(lessons.readLessons("grid_ctf").map((lesson) => lesson.text)).toEqual(["held lesson"]);
      expect(existsSync(join(dir, "knowledge", "grid_ctf", "playbook.pending.md"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("skips curator consolidation live writes while approval gate is active", async () => {
    const { GenerationRunner } = await import("../src/loop/generation-runner.js");
    const { GridCtfScenario } = await import("../src/scenarios/grid-ctf.js");
    const { SQLiteStore } = await import("../src/storage/index.js");

    const dir = root();
    const artifacts = store(dir);
    const livePlaybook =
      "<!-- PLAYBOOK_START -->\n## Strategy Updates\n\n- keep current plan\n<!-- PLAYBOOK_END -->\n\n" +
      "<!-- LESSONS_START -->\n- existing lesson\n<!-- LESSONS_END -->\n\n" +
      "<!-- COMPETITOR_HINTS_START -->\n- hint\n<!-- COMPETITOR_HINTS_END -->";
    artifacts.writePlaybook("grid_ctf", livePlaybook);

    class ConsolidatingProvider {
      readonly name = "consolidating";
      defaultModel(): string {
        return "consolidating-model";
      }
      async complete(opts: { userPrompt: string }) {
        if (opts.userPrompt.startsWith("Describe your strategy")) {
          return { text: JSON.stringify({ aggression: 0.6, defense: 0.55, path_bias: 0.5 }), model: "m", usage: {} };
        }
        if (opts.userPrompt.startsWith("You are a curator consolidating")) {
          return {
            text: "<!-- CONSOLIDATED_LESSONS_START -->\n- consolidated leak\n<!-- CONSOLIDATED_LESSONS_END -->\n<!-- LESSONS_REMOVED: 0 -->",
            model: "m",
            usage: {},
          };
        }
        return { text: "No playbook update.", model: "m", usage: {} };
      }
    }

    try {
      const dbPath = join(dir, "test.db");
      const storeDb = new SQLiteStore(dbPath);
      storeDb.migrate(join(import.meta.dirname, "..", "migrations"));
      const runner = new GenerationRunner({
        provider: new ConsolidatingProvider(),
        scenario: new GridCtfScenario(),
        store: storeDb,
        runsRoot: join(dir, "runs"),
        knowledgeRoot: join(dir, "knowledge"),
        matchesPerGeneration: 1,
        maxRetries: 0,
        minDelta: 0,
        curatorEnabled: true,
        curatorConsolidateEveryNGens: 1,
        requirePlaybookApproval: true,
      });

      await runner.run("approval-consolidation", 1);
      storeDb.close();

      expect(readFileSync(join(dir, "knowledge", "grid_ctf", "playbook.md"), "utf-8")).not.toContain(
        "consolidated leak",
      );
      expect(artifacts.readPendingPlaybook("grid_ctf").hasPending).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("exposes pending playbook approve/reject routes", () => {
    const dir = root();
    try {
      const artifacts = store(dir);
      artifacts.writePlaybook("grid_ctf", "approved playbook");
      artifacts.writeOrStagePlaybook("grid_ctf", "pending playbook", {
        requireApproval: true,
        sourceRunId: "run-approval",
        generation: 2,
        curatorDecision: "advance",
      });
      const routes = buildKnowledgeApiRoutes({
        runsRoot: join(dir, "runs"),
        knowledgeRoot: join(dir, "knowledge"),
        skillsRoot: join(dir, "skills"),
        openStore: () => {
          throw new Error("store unused");
        },
        getSolveManager: () => ({
          submit: () => "job",
          getStatus: () => ({}),
          getResult: () => null,
        }),
      });

      expect(routes.pendingPlaybook("grid_ctf").status).toBe(200);
      expect((routes.pendingPlaybook("grid_ctf").body as { hasPending: boolean }).hasPending).toBe(
        true,
      );
      expect(routes.approvePendingPlaybook("grid_ctf")).toEqual({
        status: 200,
        body: { ok: true, status: "approved" },
      });
      expect(readFileSync(join(dir, "knowledge", "grid_ctf", "playbook.md"), "utf-8")).toBe(
        "pending playbook\n",
      );
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
