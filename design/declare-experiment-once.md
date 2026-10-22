# Design: declare the experiment once

Status: **accepted**, in implementation (2026-10-21)
Repos: `mechlens-sdk` (API, run schema v2), `mechlens-cloud` (ingest, draft finding)
North-star step: **runs → checks → evidence → finding**. Serves the milestone item
*"A researcher can turn the comparison into a finding without re-entering the
same context"* and the open question *"Can reproductions become a template on
the same experiment workflow?"*

## Problem

Dogfood experiment 02 (reproducing Arditi et al. 2024) recorded a clean,
reproduced result in about 12 minutes. Turning it into a finding then took a
series of manual Cloud steps, each re-entering something the script already
knew:

| Cloud step | Already known to the script |
|---|---|
| Create a reproduction, enter the arXiv ID | `PAPER["arxiv_id"]` |
| Type the claim and research question | the module docstring and `question=` |
| Fill in the protocol (model, dataset, seeds, intervention, metrics, expected result) | `model=`, `dataset=`, `config["seed"]`, `intervention=`, `metric_definitions=`, `PAPER["table_10_refusal_score"]` |
| Make the project name match the reproduction's default (`reproduce-2406-11717`) | a naming convention the researcher has to know |
| Name runs so their first word is `baseline` / `intervention` | a naming convention the researcher has to know |
| Write limitations | the declared deviations, and every check Cloud reports as unknown or differs |

Related gaps from `dogfood/GAPS.md`: exp02 gaps 2 (paper's numbers have no
slot), 3 (two claims, two projects), 6 (roles inferred from names), and
"Found while using Cloud" 1.

The researcher's real work (judging whether the result holds and writing
that down) is buried under data entry and naming conventions.

## Goal

The researcher declares the experiment once, in the code that runs it. Cloud
turns that declaration plus the two runs into a comparison with a **draft
finding** already assembled. What remains for the researcher is judgment:

1. Review the comparison and the paper-vs-observed table.
2. Accept, edit, or add limitations.
3. Write the conclusion and pick the outcome.
4. Publish.

### Principles

- **Draft the evidence, never the verdict.** Cloud fills in facts (claim,
  numbers, protocol, check results). It never writes the conclusion, never
  picks "reproduced", and never marks a limitation as accepted on the
  researcher's behalf. This keeps the north star's "honestly bounded" promise
  and avoids automatic truth scoring.
- **The code is the source of truth.** Anything typed into Cloud that the code
  could have declared is a bug in this design.
- **No new required steps.** `start_run` keeps working unchanged. The new API
  is a convenience layer that produces ordinary runs with one extra block.
- **Local-first stays intact.** The declaration travels inside each run's JSON,
  so a saved run is still a complete, self-describing record.

## Non-goals

- Findings that span more than two runs (exp01's "steered > baseline *and* >
  random control"). That needs multi-comparison findings: a separate design.
- Uncertainty on deltas (exp01 gap 6). The draft shows point values only, as
  today.
- Holding back sensitive example outputs from publication (exp02 gap 1).
  Important, but it's a publication control, not part of drafting.
- Attaching mechanistic artifacts such as the direction vector (exp02 gap 4).

## SDK API

```python
import mechlens

exp = mechlens.experiment(
    question="Does ablating a single refusal direction remove Llama-3.1-8B-Instruct's refusals?",
    claim="Ablating one difference-in-means direction drops JailbreakBench refusal from 0.95 to 0.01.",
    reproduces=mechlens.Paper(
        arxiv="2406.11717",
        version="v3",
        reported={"refusal_rate": {"baseline": 0.95, "intervention": 0.01}},
        where="Table 10 (Llama-3 8B Instruct)",
    ),
    deviations=[
        "Llama-3.1 8B Instruct instead of Llama-3 8B Instruct",
        "Refusal score only; no LlamaGuard 2 safety score",
        "Curly apostrophes normalised before refusal matching",
    ],
    # Shared by both runs, so they are comparable by construction.
    model=llama.info,
    dataset=dataset,
    generation=GENERATION,
    metric_definitions=METRIC_DEFINITIONS,
    config=shared_config,
)

with exp.baseline() as run:
    ...  # log_example / log_metrics as today

with exp.intervention(intervention={"type": "directional_ablation", ...}) as run:
    ...

print(exp.url)  # the comparison page, with the draft finding
```

### Behaviour

- `mechlens.experiment(...)` validates and stores the declaration. It makes no
  network call.
- `exp.baseline(**overrides)` and `exp.intervention(**overrides)` each return
  an ordinary `Run`, built from the shared fields plus any per-run overrides.
  An override that changes a shared field (say, a different `dataset`) is
  allowed; Cloud's checks report it as usual.
- `project` defaults to a slug of the question, or `reproduce-<arxiv-id>` when
  `reproduces` is set. It can be passed explicitly.
- `name` defaults to the role (`baseline`, `intervention`). It's now just a
  label: roles come from the declaration, not from the name.
- `exp.url` is the intervention run's comparison URL once both runs have
  finished, otherwise `None`.
- `reproduces` is optional. Without it you get an ordinary experiment with a
  claim, deviations, and a draft finding, minus the paper-vs-observed table.
- `reported` values are keyed by metric name, so the SDK checks at `finish()`
  that each reported metric was actually logged, and warns if it wasn't.

### Run schema v2

A run created through `experiment()` carries one new top-level block and
`schema_version: 2`. Runs from plain `start_run` stay at version 1.

```json
{
  "schema_version": 2,
  "experiment": {
    "role": "baseline",
    "claim": "Ablating one difference-in-means direction drops ...",
    "deviations": ["Llama-3.1 8B Instruct instead of ...", "..."],
    "reproduces": {
      "arxiv": "2406.11717",
      "version": "v3",
      "reported": {"refusal_rate": {"baseline": 0.95, "intervention": 0.01}},
      "where": "Table 10 (Llama-3 8B Instruct)"
    }
  },
  "...": "all version 1 fields, unchanged"
}
```

Both runs carry the same declaration except `role`. Putting it in every run,
instead of sending it separately, keeps upload a single idempotent endpoint and
keeps each local JSON file self-describing.

## Cloud behaviour

### On upload of a version 2 run

1. **Validate** the `experiment` block (role is `baseline` or `intervention`;
   `reported` values are finite numbers).
2. **Assign the role slot** from `experiment.role`. Explicit roles take
   precedence over today's name-based inference.
3. **If `reproduces` is set, create or update the reproduction** for this
   workspace and project. Fill `arxiv_id`, `arxiv_version`, `claim` and
   `research_question` from the declaration, and derive `protocol_json` from
   the run (model, dataset, seed, generation, intervention, metric
   definitions, reported values as the expected result).
   - Paper metadata (title, authors, abstract) comes from the existing arXiv
     lookup, but **after** the upload is stored. A slow or failed arXiv call
     must never fail an upload. Until it resolves, the title shows as
     `arXiv:2406.11717`.
   - A field the researcher already edited in Cloud is never overwritten by a
     later upload.

The run itself stays immutable, and the declaration is stored in
`payload_json` like every other field. **No database migration is needed for
storage.**

### The draft finding

When a comparison has both roles, the comparison page opens with a draft
assembled from the two runs. It is computed when the page loads and is never
stored. Only what the researcher saves is persisted, in the existing
`conclusion` and `limitations` fields.

The draft has four parts:

1. **Claim and question**, from the declaration.
2. **Paper vs. observed**, for each metric in `reported`:

   | Metric | Reported baseline | Reported intervention | Observed baseline | Observed intervention |
   |---|---|---|---|---|
   | refusal rate | 0.95 | 0.01 | 0.98 | 0.00 |

   Shown side by side with no verdict. Deciding whether this counts as a
   reproduction is the researcher's job.
3. **Protocol summary**, from the run fields: model and revision, dataset and
   split, seed, generation settings, intervention.
4. **Candidate limitations**, each with *Add* and *Dismiss* buttons. Nothing is
   added until the researcher chooses to:
   - every declared deviation, verbatim;
   - every check whose status is **unknown** ("Neither run records
     dataset.split, so the runs can't be compared on it");
   - every **identity difference** (model, dataset, examples);
   - the sample size ("100 matched examples per run").

The conclusion field starts empty, with a prompt to write it. Publishing still
requires a saved, non-empty conclusion, as it does today.

### Experiments with more than one claim

Exp02 tests two claims of one paper: ablation on harmful prompts, and
induction on harmless prompts. With this design that's two `experiment()`
declarations with the same `reproduces.arxiv`. Each gets its own project,
comparison and draft finding. The Reproductions page groups them under the
paper by arXiv ID, which is display only. This fixes exp02 gap 3 without
needing multi-comparison findings.

## Exp02 before and after

Before, the researcher had to:
- know the project naming convention (`reproduce-2406-11717`);
- know that run names must start with `baseline` or `intervention`;
- keep the paper's numbers in `config["paper"]`, where Cloud only shows them as raw config;
- create the reproduction in Cloud and type in the protocol;
- write the limitations by hand.

After, the script declares the paper, the claim, the reported values and the
deviations once. The researcher opens the printed URL, reads the paper-vs-observed
table, adds the candidate limitations that apply, writes two sentences of
conclusion, picks "reproduced", and publishes.

## Rollout

1. **Cloud first:** accept `schema_version` 1 and 2, add role assignment and
   the reproduction create-or-update, add the draft finding UI. Plain version 1
   runs behave exactly as today.
2. **SDK 0.2.0:** `experiment()`, `Paper`, run schema v2, and docs
   (Quickstart, "Recording a comparable pair", and the reference). Version 2
   is only sent when `experiment()` is used.
3. If a 0.2.0 SDK uploads a version 2 run to an older Cloud, the upload fails
   with a 422 ("only schema_version 1 is supported"). Since 0.1.0, that error
   is reported clearly and marked non-retryable, and the run is already saved
   locally. Document this in the 0.2.0 release notes.
4. **Dogfood:** port exp02 to `experiment()`, finish its finding, and log
   anything still typed by hand in `GAPS.md`.

Rough size: SDK about a day including tests and docs. Cloud about two to
three days: ingest and reproduction create-or-update, then the draft UI.

## Decisions (2026-10-21)

1. **Declarations that disagree:** build the draft from the intervention
   run's declaration, and add a comparison check, *experiment declaration
   differs*, so the mismatch is visible.
2. **Dismissed limitations stay dismissed:** store the IDs of dismissed
   candidates alongside the finding. The draft itself is still computed on
   each load.
3. **Project name:** generated by default (`reproduce-<arxiv-id>`, or a slug
   of the question) and printed when the first run starts. `project=` still
   overrides it.
4. **A reported metric that was never logged:** warn at `finish()` and upload
   anyway. The paper-vs-observed row shows "not logged".

## Implementation status (2026-10-21)

Built, not yet deployed or released:

- **Cloud:** schema v2 ingest (`app/experiments.py`); declared roles take
  priority (`run_role`); declared papers adopted with fill-blanks-only
  protocol and arXiv metadata fetched after the upload (`app/reproductions.py`);
  *experiment declaration differs* check, checker v2 (`app/comparison.py`);
  draft finding and dismissals (`app/drafts.py`, migration `0023`); draft
  panel on the comparison page (`findings/draft-finding.tsx`).
- **SDK:** `experiment()`, `Experiment`, `Paper`, `MechLensWarning`
  (`src/mechlens/experiment.py`); Quickstart and reference updated.
- **Dogfood:** exp02 ported to `experiment()`.

Deferred:

- Grouping reproductions of the same paper on the Reproductions page.
- Switching the Cloud "New experiment" dialog, agent prompt and reproduction
  workbench snippets to `experiment()`. Do this only once SDK 0.2.0 is on
  PyPI, or `pip install mechlens` gives users an SDK without it.



1. *Which loop step?* runs → finding, and comparison → reproduction.
2. *Observed problem?* Exp02: every Cloud step re-entered what the script
   knew; roles and projects depended on naming conventions.
3. *Stronger evidence package this milestone?* Yes. The claim, the paper's
   numbers, the deviations and the unknown checks end up in the finding
   instead of being skipped.
4. *Can an existing surface handle it?* Yes: the comparison page and the
   existing finding fields. No new destination.
5. *What is postponed?* Multi-comparison findings, delta uncertainty, and
   publication redaction (non-goals above).
