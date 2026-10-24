# What the checks mean

When you open a comparison, MechLens Cloud checks two run records against each
other: each condition of an experiment against the reference, and any pair you
declared with `compare_to`. The checks answer one question: **do these records
show that the two runs are comparable?**

## What the checks do and don't tell you

The checks verify the **record**: whether the model, data, settings, and
examples you recorded are the same in both runs, and which fields can't be
compared because they weren't recorded.

They do **not** tell you whether your conclusion is true. Cloud does not rerun
your code, check that your recorded values are accurate, or judge whether a
metric measures what you say it does. The checks show where a reader should
trust the comparison and where they need to look more closely. There is
deliberately no overall validity score.

## Statuses

Each check has one of four statuses:

| Status | Meaning |
| --- | --- |
| **matches** | Both runs record this field with identical values. |
| **differs** | Both runs record it, with different values. For `sae` and `intervention`, also used when only one run records it. |
| **unknown** | One or both runs don't record it, so the runs can't be compared on it. |
| **not applicable** | The check doesn't apply. For example, input comparison when no example IDs match. |

**Unknown is not a pass.** A comparison where every field is unknown has not
been checked at all. To turn unknowns into results, record the field in both
runs (see [Recording comparable conditions](comparable-runs.md)).

## What is checked

| Category | Fields | Notes |
| --- | --- | --- |
| Model | `model.id`, `model.revision`, plus any other keys | `id` and `revision` are always reported. |
| Dataset | `dataset.id`, `dataset.revision`, `dataset.split`, plus any other keys | The three named keys are always reported. |
| SAE | Every key in `sae` | Recording it in only one run counts as a difference. |
| Intervention | Every key in `intervention` | Expected to differ: this is what you're testing. |
| Generation | Every key in `generation` except the seed | |
| Config | Every key in `config` except the seed | |
| Seed | `seed` or `random_seed` | Taken from `generation` first, then `config`. |
| Code | `code_commit` | |
| Metrics | `metric_definitions.<name>` for each logged metric | Checks the definitions, not the values. |
| Examples | Example IDs and inputs | See below. |

Nested objects are compared key by key. For example, a `generation` dict
produces separate checks for `generation.temperature` and
`generation.max_new_tokens`.

## Example coverage

Two checks cover the examples:

- **IDs.** *Matches* when every example ID appears in both runs. *Differs*
  when some IDs appear in only one run. *Unknown* when either run logs no
  examples.
- **Inputs.** For the IDs that do match, whether each input text is
  identical. Any mismatch is reported as a difference and highlighted in the
  example table.

## Differences in what was evaluated

Most differences describe **how** the runs were produced, such as a different
steering strength or temperature. Some of these are intended: the
intervention, at least.

A difference in **model**, **dataset**, or **examples** is more serious: the
runs did not evaluate the same thing. Cloud shows these at the top of the
comparison page:

> The runs differ in what was evaluated.

If you see this, the metric changes may come from the different model, data,
or prompts rather than from your intervention. Fix the recording before you
write a finding, or explain the difference in its limitations.

## Versions

Each comparison report records the version of the checker that produced it. A
published finding keeps the report it was published with, so later changes to
the checks won't change what an earlier finding says.
