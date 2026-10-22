# Recording a comparable pair

A comparison is only as good as the two records behind it. If the runs used
different prompts, model weights or decoding settings, a change in a metric
might not come from your intervention. Cloud can only catch this when both runs
record those details.

## The rule

> Record the same fields in both runs. Keep everything identical except the
> intervention.

Cloud compares the baseline and intervention runs field by field. When a
field is missing from either run, Cloud reports it as **unknown**; it is never
assumed to match. See [What the checks mean](integrity-checks.md).

## What to record

| Argument | Record | Why it matters |
| --- | --- | --- |
| `project` | The same string for both runs | Only runs in the same project can be compared. |
| roles | `exp.baseline()` and `exp.intervention()` | Cloud pairs runs by their declared role. With plain `start_run`, a name starting with `baseline` or `control` marks the baseline. |
| `model` | `id` **and** `revision` | Without `revision`, Cloud can't confirm both runs used the same weights. |
| `dataset` | `id`, `revision`, `split` | These three keys are always checked, and reported as unknown if missing. |
| `generation` | Decoding settings: `temperature`, `max_new_tokens`, `do_sample` | A sampling change can shift outputs as much as an intervention. |
| `config` | Any other settings, including `seed` | Every key is compared. |
| `intervention` | Only on the intervention run | Should be the one difference between the runs. |
| `sae` | The SAE release, ID, and hook point, if you use one | A one-sided SAE is reported as a difference. |
| `metric_definitions` | How each metric is calculated | Cloud checks that both runs define each metric the same way. |
| `code_commit` | Usually automatic | Detected with `git rev-parse HEAD` when you run inside a repository. |

## Example IDs

Examples are matched across runs by `id`, not by position or prompt text.

- **Use IDs that stay the same** across runs, such as dataset row IDs or
  hashes. Avoid loop counters if the order can change.
- **Log the same set of IDs** in both runs. Examples logged in only one run
  are left out of the side-by-side view, and the coverage check reports the
  mismatch.
- **Keep `input` identical** for each ID. If the same ID has different
  inputs, Cloud flags it as an input mismatch.

## Per-example fields

Any extra keyword passed to `log_example` is stored with the example:

```python
run.log_example(
    id="lockout-001",
    input=prompt,
    output=answer,
    refused=False,
    helpfulness=4,
)
```

Cloud marks an example as **behavior changed** when these extra fields differ
between the two runs, and **output changed** when the text differs. Log the
measurement your conclusion depends on here, such as a refusal label, a score,
or a probability, so a reviewer can see which examples moved.

## Seeds

Cloud looks for `seed` or `random_seed` in `generation` first, then in
`config`, and compares the first one it finds in each run. Put the seed in the
same place in both runs.

## Metric definitions

```python
metric_definitions={
    "refusal_rate": {
        "description": "Share of prompts whose response declines to help.",
        "direction": "lower_is_better",
    },
}
```

Each description appears on the comparison page beneath the metric. If two runs
report the same metric name with different definitions, the check reports a
difference, so you know the numbers are not measuring the same thing.

## A checklist before you compare

- [ ] Same `project` in both runs
- [ ] `model` includes `revision`
- [ ] `dataset` includes `id`, `revision` and `split`
- [ ] Same `generation` settings and seed
- [ ] Same example IDs with identical inputs
- [ ] `intervention` recorded only on the intervention run
- [ ] `metric_definitions` for every metric you log
