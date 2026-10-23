# Design: corrections and finding review

Status: **proposed; dogfood fixture added, not implemented** (2026-10-23)
Repos: `mechlens-sdk` (correction declaration and run schema), `mechlens-cloud`
(validation, impact tracking, review and publication UI)
North-star step: **runs → checks → finding**. This keeps a durable finding
attached to its evidence when later evidence changes what it supports.

## Problem

MechLens keeps runs immutable. Recording the same condition again makes the
latest run current and leaves earlier runs visible as superseded. It does not
yet say which exact run was corrected or why, distinguish a correction from an
ordinary rerun, or flag findings that relied on corrected evidence.

The motivating case is a shuffled baseline that accidentally sampled outside
the subset under study. The incorrect result must remain inspectable, the
corrected run must become current, and every conclusion that relied on the old
run must be brought back to the researcher's attention.

## Goal

Let research code explicitly say, “this run corrects that exact run, for this
reason.” Cloud traces the old run to saved and published findings, marks those
findings as needing review, and records the researcher's judgment. It never
decides the scientific consequence automatically.

> corrected run → replaced run + reason → affected finding → human review →
> still supported / narrowed / unsupported

## Non-goals

- A general artifact registry or file-storage system.
- Arbitrary renderer → dataset → checkpoint dependency graphs. The data model
  can leave room for these later, but this milestone starts with run corrections.
- Automatically revoking a publication or rewriting its immutable snapshot.
- Automatically deciding whether a claim remains true.
- Treating every repeated condition as a correction. Ordinary reruns keep
  today's behavior and carry no correction semantics.

## SDK API

```python
import mechlens

exp = mechlens.experiment(
    id="shuffled-control-correction",
    question="Is the selected direction stronger than a subset-matched shuffle?",
    claim="The selected direction is stronger than the reference and control.",
    model=model,
    dataset=dataset,
)

with exp.control(
    "shuffled-subset-control",
    intervention={"type": "shuffled_direction", "candidate_pool": "studied subset"},
    correction=mechlens.Correction(
        supersedes="f9ad0f0a-6a67-4d2e-b879-2a0f94260ec8",
        reason="The original control sampled outside the studied subset.",
    ),
) as run:
    record(run)
```

`Correction` is a frozen dataclass exported from `mechlens`:

```python
@dataclass(frozen=True)
class Correction:
    supersedes: str
    reason: str
```

`correction=` is accepted by `reference()`, `intervention()` and `control()`.
It is a named condition argument, not a `start_run` override. That keeps it
separate from experimental configuration and comparison differences.

### SDK validation

- `supersedes` and `reason` must be non-empty strings after trimming.
- A run cannot supersede its own generated ID.
- The SDK cannot validate the target's ownership or condition because it
  remains local-first and does not read Cloud before recording.
- A corrected run uses schema version 4. Uncorrected experiment runs remain
  schema version 3, so existing scripts and saved files do not change.
- `Correction.to_json()` returns a defensive JSON copy like `Paper.to_json()`.

### Run schema v4

```json
{
  "schema_version": 4,
  "id": "new-run-id",
  "experiment": {
    "id": "shuffled-control-correction",
    "condition": {
      "name": "shuffled-subset-control",
      "kind": "control"
    }
  },
  "correction": {
    "supersedes": "old-run-id",
    "reason": "The original control sampled outside the studied subset."
  }
}
```

The correction is top-level because it describes a relationship between two
run records, not the experimental condition itself.

## Cloud ingest

Uploading a schema-v4 correction is one transaction:

1. Validate and insert the new immutable run as usual.
2. Load `correction.supersedes` in the same workspace.
3. Require the target to have the same project, experiment ID and condition
   name as the new run.
4. Require the target to be the condition's current run. If it is stale,
   return `409` with the current run ID so concurrent corrections cannot form
   an ambiguous chain.
5. Insert an explicit correction edge with the reason.
6. Make the corrected run current through the existing latest-run behavior.
7. Create impact records for saved findings and publications whose evidence
   dependencies include the replaced run.

If validation fails, neither the run nor the edge is committed. Re-uploading
the same run ID remains idempotent.

Suggested table:

```text
run_corrections
  workspace_id
  corrected_run_id       unique, FK experiment_runs.id
  superseded_run_id      unique, FK experiment_runs.id
  reason
  created_at
```

The uniqueness constraints make the first accepted correction canonical. A
later correction supersedes the current corrected run, forming a linear chain.

## Binding findings to evidence

Impact detection needs normalized dependencies rather than searching JSON.
When a finding is saved, resolve its cited contrasts to their current run IDs.
When a publication is created, insert the run IDs already captured in its
immutable snapshot.

```text
evidence_dependencies
  workspace_id
  subject_type            finding | publication
  subject_id              stable finding key or publication ID
  run_id                  FK experiment_runs.id
  payload_sha256

finding_impacts
  workspace_id
  subject_type            finding | publication
  subject_id
  superseded_run_id
  corrected_run_id
  state                   needs_review | still_supported | narrowed | unsupported
  review_note             nullable
  created_at
  reviewed_at             nullable
```

A saved editable finding is bound to the evidence the researcher last
reviewed, even though its experiment page starts showing the newest run.
Saving after review refreshes its dependency rows. A publication snapshot
never changes; its impact state is mutable metadata displayed alongside it.

## Product behavior

The experiment page shows the corrected condition as current, the old run and
correction reason, old-versus-corrected metrics and examples, and a “Finding
needs review” banner where appropriate. The generic “condition re-recorded”
note remains for ordinary reruns.

The researcher chooses one review state and may add a note:

- **Still supported** — the correction does not change the conclusion.
- **Narrowed** — part of the conclusion or its limits must change.
- **Unsupported** — the cited evidence no longer supports the conclusion.

Cloud shows evidence differences but does not suggest a state. Reviewing an
editable finding does not silently republish it.

A published page remains an immutable account of what was released. Mutable
metadata above it says that cited evidence was corrected and shows the review
state and any replacement publication. Snapshot content is never rewritten.

## Dogfood

- `dogfood/exp04_correction_original.py` records a reference, selected
  direction and flawed shuffled control. Upload it, write the obvious
  specificity conclusion and publish it.
- `dogfood/exp04_correction_fixed.py` records the corrected control with
  `Correction(supersedes=..., reason=...)`. It intentionally requires this
  proposed SDK API and will fail until implementation begins.

Acceptance criteria:

1. The original control and publication remain accessible.
2. The corrected control becomes current and names the exact old run and reason.
3. The saved finding and publication are marked `needs_review`.
4. The UI shows that the original control appeared inert while the corrected
   subset-matched control has high activation.
5. MechLens does not choose the review outcome.
6. Selecting `narrowed` or `unsupported` records the decision and note.
7. Republishing creates version 2; version 1 is never rewritten.

## Later extension: artifact dependencies

If dogfood shows run-level correction is insufficient, the same dependency
mechanism can accept immutable artifact references and edges such as renderer
→ dataset → checkpoint → run. That needs its own SDK design; it is not part of
this proposal or the current milestone commitment.

## Implementation order

1. SDK `Correction`, serialization, validation and tests.
2. Cloud schema-v4 validation and `run_corrections` transaction tests.
3. Evidence dependency rows for saved findings and publications.
4. Impact creation and review API.
5. Experiment and publication notices.
6. Run the two-stage fixture and record missing workflow in `dogfood/GAPS.md`
   before considering artifact dependencies.
