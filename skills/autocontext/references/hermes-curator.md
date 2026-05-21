# Hermes Curator + autocontext

Reference for Hermes agents using autocontext alongside Hermes Curator.
Use this when the user asks how the two systems cooperate, or when an
agent needs to decide which side to call for a given operation.

## Headline

- **Hermes Curator is the live skill-library maintainer.**
- **autocontext is the evaluation, trace, replay, export, and local-training layer.**
- autocontext does NOT replace Curator. It observes Curator's outputs,
  evaluates them, and turns them into durable artifacts.

## Who owns what

| Operation                                   | Owner       |
| ------------------------------------------- | ----------- |
| Mutate `~/.hermes/skills/` (add/patch/prune) | Curator     |
| Read-only inspection of Hermes state        | autocontext |
| Run trace / replay / export                 | autocontext |
| Curator decision dataset export             | autocontext |
| Local MLX/CUDA advisor training             | autocontext |
| Apply trained advisor recommendations       | Curator (when the advisor path is proven) |

## Read-only first rule

`autoctx hermes inspect` and `autoctx hermes ingest-curator` and
`autoctx hermes export-dataset` are all **read-only against
`~/.hermes`**. Until the trained-advisor path is shipped and proven
end-to-end, autocontext will not write to Hermes state on its own.
Recommendations from autocontext flow back to Curator as suggestions;
Curator stays the mutation owner.

## Command availability

`autoctx hermes inspect` and `autoctx hermes export-skill` ship in
the same release as these references. `autoctx hermes ingest-curator`
(AC-704) and `autoctx hermes export-dataset` (AC-705) ship on
follow-up PRs in the Hermes integration cluster; run `autoctx hermes
--help` to confirm what is installed locally before recommending one
of them to the user.

## What an agent should do

1. Ask the user what they want to learn from Hermes state.
2. Run `autoctx hermes inspect --home ~/.hermes --json` to see what's
   available.
3. If the user wants to analyze curator decisions: `autoctx hermes
   ingest-curator` (traces) or `autoctx hermes export-dataset --kind
   curator-decisions` (training rows).
4. Never propose direct edits to `~/.hermes/skills/` from autocontext.
   Surface findings as evidence and let Curator (or the user) apply
   changes.
