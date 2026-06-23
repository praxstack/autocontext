import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { AppSettingsSchema } from "../src/config/index.js";
import { buildCompetitorPrompt } from "../src/loop/generation-prompts.js";
import { evaluateLevyScout, renderLevyScoutGuidance } from "../src/loop/index.js";

type Fixture = {
  alpha: number;
  scale: number;
  cases: Array<{
    seed_base: number;
    generation: number;
    attempt: number;
    random_value: number;
    step_size: number;
    intensity: string;
  }>;
};

const FIXTURES = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "..", "docs", "levy-scout-parity-fixtures.json"), "utf-8"),
) as Fixture;

describe("Levy scout mutation", () => {
  it("matches shared fixtures", () => {
    for (const item of FIXTURES.cases) {
      const outcome = evaluateLevyScout({
        enabled: true,
        alpha: FIXTURES.alpha,
        scale: FIXTURES.scale,
        seedBase: item.seed_base,
        generation: item.generation,
        attempt: item.attempt,
      });

      expect(Math.abs(outcome.randomValue - item.random_value)).toBeLessThan(1e-15);
      expect(Math.abs(outcome.stepSize - item.step_size)).toBeLessThan(1e-15);
      expect(outcome.intensity).toBe(item.intensity);
    }
  });

  it("is default off and visible only in competitor prompts", () => {
    expect(AppSettingsSchema.parse({}).experimentalLevyScoutEnabled).toBe(false);
    expect(renderLevyScoutGuidance({ enabled: false, seedBase: 0, generation: 1 })).toBe("");

    const guidance = renderLevyScoutGuidance({ enabled: true, seedBase: 0, generation: 10 });
    const prompt = buildCompetitorPrompt({
      scenarioName: "grid_ctf",
      scenarioRules: "rules",
      strategyInterface: '{"aggression": number}',
      evaluationCriteria: "score",
      playbook: "playbook",
      operatorHint: guidance,
    });

    expect(prompt).toContain("Lévy scout mutation guidance");
    expect(prompt).toContain("jump");
  });
});
