import { describe, expect, it } from "vitest";

type Protocol = Record<string, (...args: any[]) => any>;

async function protocol(): Promise<Protocol> {
  const path = "../src/research/opd-grpo-mixture-protocol.js";
  return (await import(path)) as Protocol;
}

describe("OPD/GKD + GRPO mixture protocol", () => {
  it("builds a matched-compute matrix", async () => {
    const { buildExperimentMatrix } = await protocol();
    const matrix = buildExperimentMatrix({
      scenario: "gsm8k",
      seeds: [0, 1],
      steps: [1000],
      prompts: 384,
    });

    expect(new Set(matrix.runs.map((run: { arm: string }) => run.arm))).toEqual(
      new Set(["grpo", "full_opd", "positive_opd", "mixed_positive_opd_grpo"]),
    );
    expect(new Set(matrix.runs.map((run: { maxSteps: number }) => run.maxSteps))).toEqual(
      new Set([1000]),
    );
    expect(new Set(matrix.runs.map((run: { nPrompts: number }) => run.nPrompts))).toEqual(
      new Set([384]),
    );
    expect(matrix.seedNotes).toBe("2 seeds: 0, 1");
  });

  it("keeps mixed mode as a recipe rather than a default", async () => {
    const { buildExperimentMatrix } = await protocol();
    const matrix = buildExperimentMatrix({ scenario: "gsm8k", seeds: [0], steps: [1000] });
    const mixed = matrix.runs.find((run: { arm: string }) => run.arm === "mixed_positive_opd_grpo");

    expect(mixed?.trainingMixture).toBe("positive_opd=0.5,grpo=0.5");
    expect(mixed?.command).toContain("autocontext.training.autoresearch.train");
    expect(mixed?.command).toContain("--backend trl");
    expect(mixed?.command).toContain("--n-prompts 384");
    expect(mixed?.command).not.toContain("--positive-pressure");
    expect(mixed?.command).not.toContain("--training-mixture");
    expect(mixed?.command).not.toContain("trl_backend");
    expect(matrix.promotionPolicy).toContain("Do not promote mixed mode");
  });

  it("only promotes mixed mode when held-out lift has no collapse", async () => {
    const { summarizeMixtureResults } = await protocol();
    const collapsed = summarizeMixtureResults([
      { arm: "grpo", seed: 0, heldoutScore: 0.64, entropy: 4, diversity: 0.4 },
      { arm: "mixed_positive_opd_grpo", seed: 0, heldoutScore: 0.7, entropy: 0.1, diversity: 0.01 },
    ]);
    const healthy = summarizeMixtureResults([
      { arm: "grpo", seed: 0, heldoutScore: 0.64, entropy: 4, diversity: 0.4 },
      { arm: "mixed_positive_opd_grpo", seed: 0, heldoutScore: 0.7, entropy: 3, diversity: 0.3 },
    ]);

    expect(collapsed.promotion).toMatchObject({ promoteMixed: false, reason: "collapse_detected" });
    expect(healthy.promotion).toMatchObject({
      promoteMixed: true,
      reason: "heldout_improved_without_collapse",
    });
  });

  it("requires held-out comparison metrics before promotion", async () => {
    const { summarizeMixtureResults } = await protocol();
    const missingBaseline = summarizeMixtureResults([
      { arm: "grpo", seed: 0, entropy: 4, diversity: 0.4 },
      { arm: "mixed_positive_opd_grpo", seed: 0, heldoutScore: 0.02, entropy: 3, diversity: 0.3 },
    ]);
    const missingMixed = summarizeMixtureResults([
      { arm: "grpo", seed: 0, heldoutScore: 0.64, entropy: 4, diversity: 0.4 },
      { arm: "mixed_positive_opd_grpo", seed: 0, entropy: 3, diversity: 0.3 },
    ]);
    const nonfiniteBaseline = summarizeMixtureResults([
      { arm: "grpo", seed: 0, heldoutScore: Number.NaN, entropy: 4, diversity: 0.4 },
      { arm: "mixed_positive_opd_grpo", seed: 0, heldoutScore: 0.02, entropy: 3, diversity: 0.3 },
    ]);

    expect(missingBaseline.promotion).toEqual({
      promoteMixed: false,
      reason: "missing_comparison",
    });
    expect(missingMixed.promotion).toEqual({ promoteMixed: false, reason: "missing_comparison" });
    expect(nonfiniteBaseline.promotion).toEqual({
      promoteMixed: false,
      reason: "missing_comparison",
    });
  });

  it("renders required diagnostics", async () => {
    const { buildExperimentMatrix, renderProtocolReport } = await protocol();
    const report = renderProtocolReport(
      buildExperimentMatrix({ scenario: "gsm8k", seeds: [0], steps: [1000] }),
    );

    for (const field of [
      "heldout_score",
      "response_length",
      "diversity",
      "entropy",
      "kl",
      "token_pressure",
      "cost_time",
    ]) {
      expect(report).toContain(field);
    }
    expect(report).toContain("AC-787/AC-789");
  });
});
