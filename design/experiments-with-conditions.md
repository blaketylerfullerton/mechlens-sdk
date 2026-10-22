# Design: experiments with N conditions

Status: **accepted**, not yet implemented (2026-10-21). SDK API revised the
same day (decisions 5–9): stable experiment IDs, kind-named methods, declared
comparisons.
Repos: `mechlens-sdk` (API, run schema v3), `mechlens-cloud` (experiment record,
contrasts, uncertainty, findings)
Builds on: [Declare the experiment once](declare-experiment-once.md), shipped
in SDK 0.2.0.
North-star step: **runs → checks → evidence → finding**. Serves the milestone
items *"MechLens clearly distinguishes a valid comparison from a misleading
one"* and *"The comparison shows metric definitions, deltas, per-example
evidence, provenance, and limitations"*. From the inbox item "Generalise the
unit from a pair to an experiment with N conditions".

## Problem

All three dogfood experiments needed more than one baseline/intervention pair:

| | What the claim needed | What MechLens could hold |
|---|---|---|
| exp01 | baseline, steered, **random control**; the claim is "steered beats baseline *and* the control" | one pair per finding (gap 5) |
| exp02 | two claims, ablation and induction, on different datasets | two unrelated projects (gap 3) |
| exp03 | 11 conditions: 2 references, 3 ablations, 6 additions including a **dose-response** over 5 coefficients | 9 pair experiments, 7 duplicate baseline runs (gaps 1–6) |

The same gaps recur:

1. **Findings are tied to one pair.** Claims about a set ("only the refusal
   direction removes refusal") or a curve ("refusal rises with the
   coefficient") can't be written as one finding.
2. **Controls look like interventions.** There are only two roles, so a
   random-direction ablation the claim expects to do *nothing* is recorded
   exactly like the real intervention.
3. **No sweeps.** A dose-response is five pairwise deltas, not a curve.
4. **No uncertainty.** "No effect" needs an interval around zero. Every
   dogfood script computed paired-bootstrap intervals locally because Cloud
   shows point deltas only.

## Goal

An experiment is **one reference condition plus any number of other
conditions**, each tagged as an intervention or a control, optionally grouped
into a sweep. Cloud compares every condition with the reference, computes an
interval for each difference, and drafts one finding for the whole
experiment, which can cite as many of those contrasts as the claim needs.

The pair from SDK 0.2 becomes the simplest experiment: one reference, one
intervention. Its API keeps working.

### Principles (unchanged from the first design)

- **Draft the evidence, never the verdict.** Cloud may show "expected no
  effect; observed −0.01 [−0.03, +0.00]" side by side. It never says "control
  passed" or "reproduced".
- **The code is the source of truth.** Kinds, expectations and sweep levels are
  declared in the script, before the results exist.
- **Local-first.** Each condition is still one self-describing run file.

## Concepts

| Term | Meaning |
|---|---|
| **Experiment** | One question, one claim, one dataset, one reference. Identified by a stable `experiment.id`: given by the researcher, or derived from the declaration, so conditions recorded in separate processes join the same experiment. |
| **Condition** | One run of the experiment, identified by its name. Exactly one per experiment has kind `reference`. Others are `intervention` or `control`. |
| **Expectation** | Declared per condition and metric: `increase`, `decrease`, or `no_effect` relative to the reference. Controls usually expect `no_effect`. Optional. |
| **Series** | Conditions sharing a `series` name and differing in a numeric `level`, such as a steering coefficient. Cloud plots a series as a curve. |
| **Contrast** | A comparison of two conditions in the same experiment. Every condition is contrasted with the reference. A condition may also declare, in code, other conditions it should be compared with (`compare_to`), such as exp01's steered vs. control. A finding may cite further contrasts chosen in Cloud. |

**One dataset per experiment.** exp03's harmful and harmless halves become two
experiments, because they have different references. That's honest: their
conditions can't be compared with each other. Grouping experiments
(for example under one paper) is a display concern and out of scope.

### The dogfood experiments in this model

| | Experiment(s) | Conditions |
|---|---|---|
| exp01 | 1 | reference `baseline`; intervention `steer-feature-5608` (expects increase in mention rate); control `random-features` (expects no effect). The intervention declares `compare_to=["random-features"]`, so the finding cites steered vs. reference and steered vs. control by default. |
| exp02 | 2 | ablation: reference + intervention. Induction: reference + intervention. |
| exp03 | 2 | specificity: reference + 1 intervention + 2 controls (expect no effect). Dose-response: reference + series `addition` at levels 0.25–1.5 (expect increase) + 1 control. |

## SDK API

```python
exp = mechlens.experiment(
    id="refusal-direction-specificity",  # optional; see "Experiment identity"
    question="Is the refusal direction specific?",
    claim="Only ablating the refusal direction removes refusal on JailbreakBench.",
    deviations=[...],
    model=..., dataset=..., generation=..., config={"seed": 42},
)

with exp.reference() as run:
    record(run, generate)

with exp.intervention(
    "ablate-refusal-direction",
    intervention={"type": "directional_ablation", ...},
    expect={"refusal_rate": "decrease"},
    compare_to=["ablate-random-directions"],
) as run:
    record(run, ablated)

with exp.control(
    "ablate-random-directions",
    intervention={"type": "directional_ablation", "direction": "random, per prompt"},
    expect={"refusal_rate": "no_effect"},
) as run:
    record(run, random_ablated)

print(exp.url)  # the experiment page
```

The kind of a condition is the method that starts it: `reference()`,
`intervention()` or `control()`. There is no `kind=` string to mistype, and
editors autocomplete the three methods.

A sweep is a set of conditions with the same `series`. The name may be
omitted when `series` and `level` are given; it defaults to
`"<series>@<level>"` (here `addition@0.5`):

```python
for c in (0.25, 0.5, 0.75, 1.0, 1.5):
    with exp.intervention(
        series="addition",
        level=c,
        intervention={"type": "activation_addition", "coefficient": c},
        expect={"refusal_rate": "increase"},
    ) as run:
        record(run, lambda p: added(p, c))
```

### Experiment identity

All of an experiment's conditions need not run in one process. exp03's eleven
conditions might run as a job array across GPUs, a notebook kernel may restart
midway, or one failed condition may be rerun the next day. So the ID must be
stable across processes:

- `mechlens.experiment(id=...)` sets it explicitly: a slug, unique within the
  project.
- Without `id`, the SDK derives it from a hash of the project, question and
  claim. Running the same declaration again, in any process, joins the same
  experiment. Editing the claim starts a new experiment, which is correct: the
  old runs tested a different claim.
- Any other drift in the declaration (deviations, paper values) between
  processes is caught by the existing *experiment declaration differs* check.

**Rerunning a condition.** If a condition name is uploaded again for the same
experiment, the latest finished run becomes the condition's current run.
Earlier runs are kept (runs are immutable) and listed as superseded on the
experiment page; a draft finding notes "condition re-recorded" as a candidate
limitation, so silent best-of-N reruns stay visible.

### Behaviour

- `exp.reference()` replaces `exp.baseline()`; `baseline()` stays as an
  alias. `exp.intervention()` with no name and no series keeps its 0.2
  meaning: a condition named `intervention`.
- Within one `Experiment` object, condition names must be unique and a second
  `reference()` raises. Across processes, a repeated name is a rerun (see
  above).
- `compare_to` lists other condition names. It may not name the condition
  itself or the reference (always compared). The SDK can't check that the
  named conditions exist, since they may run elsewhere; Cloud shows a declared
  comparison with a missing condition as "not yet recorded", and the draft
  lists it as a candidate limitation.
- `expect` keys must be metric names; the SDK warns at `finish()` if an
  expected metric was never logged, as it already does for paper values.
- `level` must be a finite number, and requires `series`. A name is required
  unless both are given.
- `exp.url` is the experiment page; it is set as soon as this process has
  uploaded one condition, since the other conditions may upload elsewhere.
- Paper values are keyed by condition name:
  `reported={"refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}}`.
  The 0.2 keys `baseline` and `intervention` still work in pair experiments.

### Linking metrics to examples, for intervals

Cloud can only compute an interval from per-example values. A metric
definition may name the example field it averages:

```python
metric_definitions={"refusal_rate": {"description": "...", "example_field": "refused"}}
```

Cloud then shows the metric's difference with an interval computed from
`refused` over matched examples. Without `example_field`, the metric shows a
point difference, as today, and the draft lists "no interval: metric not
linked to an example field" as a candidate limitation.

Because intervals are the main gain here and `example_field` is easy to miss,
the SDK points at it: at `finish()`, for each logged metric without an
`example_field`, if its value equals the mean of a numeric or boolean field
present on every logged example, the SDK warns and names the field to link.
It never links one silently: the metric's definition stays the researcher's.

### Run schema v3

```json
{
  "schema_version": 3,
  "experiment": {
    "id": "refusal-direction-specificity",
    "claim": "...",
    "deviations": ["..."],
    "reproduces": {"arxiv": "2406.11717", "reported": {"refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}}},
    "condition": {
      "name": "add-x0.5",
      "kind": "intervention",
      "series": "addition",
      "level": 0.5,
      "expect": {"refusal_rate": "increase"},
      "compare_to": []
    }
  }
}
```

The declaration (everything but `condition`) is identical across an
experiment's runs. The *experiment declaration differs* check from 0.2 still
flags any mismatch.

`experiment.id` is what groups runs into an experiment. Today grouping uses
the project name, which can't tell two experiments in one project apart (exp03
had nine in two projects). It is scoped to the project, so Cloud groups on
`(project, experiment.id)`.

## Cloud

### Data

- **Runs** are unchanged: immutable, stored whole. Experiments are derived by
  grouping runs on `(project, experiment.id)`; no experiments table is
  needed. A condition's current run is the latest finished run with that
  name; earlier ones are superseded, not deleted.
- **New table `findings`:** keyed by `(workspace_id, project, experiment_id)`, with
  `conclusion`, `limitations`, `cited_contrasts` (a list of condition-name
  pairs) and `dismissed`. The existing `experiment_findings` table, keyed by
  one (run, baseline) pair, stays as it is for v1 and v2 pairs.
- **Publications** gain snapshot schema 3: every cited contrast with its
  checks, metric differences and intervals, the series data, and each
  condition's run hash. Existing publications are unchanged.

### Contrasts and intervals

- A contrast between conditions A and B reuses `compare_runs` exactly (the
  same checks, the same report) with A as the baseline side.
- **Intervals:** for each per-example numeric or boolean field present in both
  runs, Cloud computes the mean of (B − A) over matched examples with a paired
  bootstrap: 10,000 resamples, a fixed seed, and a 95% percentile interval.
  That's the method every dogfood script used locally. The method and its
  parameters go into the comparison report, so a published finding records
  how its intervals were computed.
- Contrasts are computed on request and cached by the two runs' payload
  hashes. Nothing new is stored per contrast.

### The experiment page

`/app/experiments/<project>/<experiment_id>` is an overview of the experiment that links
into the existing comparison page for detail. It shows:

1. **Conditions table:** one row per condition with its kind, series and
   level, number of examples, each key metric, the difference against the
   reference with its interval, and the declared expectation next to it. The
   expectation and the observed difference sit side by side, with no
   pass/fail column. Each row links to the existing comparison page for that
   contrast (checks, examples, provenance). Declared `compare_to` contrasts
   appear under the condition that declared them. Superseded runs are listed
   under their condition.
2. **Series chart:** for each series, each metric against level with interval
   bars, and the reference drawn as a band. ECharts is already a frontend
   dependency.
3. **Draft finding:** the claim; paper vs. observed per condition when
   reported values exist; candidate limitations drawn from every contrast and
   de-duplicated; a picker for which contrasts the finding cites (by default,
   every contrast with a declared expectation plus every declared
   `compare_to` contrast); then conclusion, outcome and publish, as today.
   The published finding marks which cited contrasts were declared in code
   and which were added in Cloud.

**Surface check.** The north star says not to add product surfaces. This page
is a new route, but not a new destination: it replaces the finding section of
the comparison page for N-condition experiments, and the comparison page stays
as the per-contrast drill-down. Pair experiments keep today's page unchanged.
Accepted on that basis (decision 1).

### Reproductions

A run declaring a paper still creates or updates the reproduction, now keyed
by experiment. Reported values per condition become paper-vs-observed rows on
the experiment page.

## Not in this design

- Findings that span experiments (exp02's two claims stay two findings).
- Multiple seeds as a first-class concept. A seed sweep can be a series today;
  pooling seeds into one interval is a separate design.
- Multiple-comparison correction across many contrasts. The draft states how
  many contrasts were run, as a candidate limitation.
- Sensitive-output controls for publication (exp02 gap 1), and attaching
  mechanistic artifacts (exp02 gap 4).

## Rollout

1. **Cloud, phase 1:** accept schema v3; group runs into experiments, with
   superseded reruns; compute
   contrasts and intervals; add the experiment page with the conditions
   table; add experiment findings with cited contrasts; add publication
   snapshot v3.
2. **SDK 0.3.0:** `experiment(id=...)` and derived IDs, `reference()`,
   `intervention(name, ...)`, `control(name, ...)`, `expect`, `compare_to`,
   `series`, `level`, `example_field` and its `finish()` hint, schema v3. A 0.3 SDK uploading to an older Cloud
   gets the existing clear, non-retryable 422 error, as with 0.2.
3. **Cloud, phase 2:** the series chart, and paper-vs-observed per condition.
4. **Dogfood:** port exp03 to `reference()`, `intervention()` and `control()`, upload it, and write one finding
   per experiment. Then do the same for exp01's three conditions.

Rough size: SDK 1–2 days. Cloud phase 1 about 4–5 days (grouping, intervals,
experiment page, findings table, publication v3); phase 2 about 1–2 days.

## Decisions (2026-10-21)

1. **The overview is a new experiment page**, `/app/experiments/<project>/<id>`. It
   holds the finding; each condition links to the existing comparison page
   for detail. Accepted as replacing the comparison page's finding section
   for N-condition experiments, not as a new product destination.
2. **The draft cites the contrasts with declared expectations**, and the
   declared `compare_to` contrasts, by default. The researcher can remove
   those or add others; added ones are marked as chosen in Cloud.
3. **Pair experiments from 0.2 stay on today's comparison page,** with their
   existing findings. No migration.
4. **Intervals only for metrics linked to an example field**
   (`example_field`). Unlinked metrics show a point difference, and the draft
   offers "no interval: metric not linked to an example field" as a
   candidate limitation.

SDK API revision, same day:

5. **Experiment IDs are stable across processes.** Set with `id=`, or derived
   from project, question and claim. Conditions may run in separate jobs or
   sessions. Rejected: an SDK-generated random ID, which would split any
   experiment not recorded in a single script execution.
6. **A repeated condition name is a rerun.** The latest finished run is
   current; earlier runs are kept, shown as superseded, and noted as a
   candidate limitation.
7. **The kind is the method:** `reference()`, `intervention()`, `control()`.
   Rejected: `condition(kind="...")`, which gave three ways to start a
   condition and a string that fails only at runtime.
8. **Comparisons beyond the reference are declared in code** with
   `compare_to`, so the contrast a claim depends on is fixed before the
   results exist. Cloud may still add contrasts, marked as such.
9. **The SDK hints at `example_field`, but never links it silently.** Sweep
   conditions may omit the name (`<series>@<level>`).

## Decision filter

1. *Which loop step?* runs → checks → evidence → finding.
2. *Observed problem?* All three dogfood experiments needed more than a pair;
   gaps exp01-5/6, exp02-3/5, and exp03-1 to 6.
3. *Stronger evidence package this milestone?* Yes: controls, sweeps and
   intervals in the finding itself, rather than in local `summary.json`
   files.
4. *Can an existing surface handle it?* The comparison page handles each
   contrast. The overview is the one addition (decision 1).
5. *What is postponed?* Cross-experiment findings, seed pooling,
   multiple-comparison correction, publication redaction, artifact
   attachment.
