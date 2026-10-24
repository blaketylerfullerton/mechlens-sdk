# Recording comparable conditions

A comparison is only as good as the two records behind it. If a condition used
different prompts, model weights or decoding settings from the reference, a
change in a metric might not come from your intervention. Cloud can only catch
this when every run records those details.

## The rule

> Record the same fields in every condition. Keep everything identical except
> the intervention.

Cloud compares each condition with the reference, field by field, and with any
other condition it declares in `compare_to`. When a field is missing from
either side, Cloud reports it as **unknown**; it is never assumed to match.
Declaring the experiment once with `mechlens.experiment()` shares these fields
across conditions for you. See [What the checks mean](integrity-checks.md).

## What to record

| Argument | Record | Why it matters |
| --- | --- | --- |
| `project` | The same string for every condition | Only runs in the same project can be compared. |
| conditions | `exp.reference()`, `exp.intervention()` and `exp.control()` | Cloud groups the runs into one experiment and compares each with the reference. With plain `start_run`, a name with `baseline` or `control` as a whole word, such as `baseline` or `my-baseline-v2`, is chosen as the default baseline. |
| `model` | `id` **and** `revision` | Without `revision`, Cloud can't confirm both runs used the same weights. |
| `dataset` | `id`, `revision`, `split` | These three keys are always checked, and reported as unknown if missing. |
| `generation` | Decoding settings: `temperature`, `max_new_tokens`, `do_sample` | A sampling change can shift outputs as much as an intervention. |
| `config` | Any other settings, including `seed` | Every key is compared. |
| `intervention` | On every condition except the reference | Should be the one difference from the reference. |
| `sae` | The SAE release, ID, and hook point, if you use one | A one-sided SAE is reported as a difference. |
| `metric_definitions` | How each metric is calculated, and its `example_field` | Cloud checks that both runs define each metric the same way, and computes intervals from the linked field. |
| `code_commit` | Usually automatic | Detected with `git rev-parse HEAD` when you run inside a repository. |

## Example IDs

Examples are matched across runs by `id`, not by position or prompt text.

- **Use IDs that stay the same** across runs, such as dataset row IDs or
  hashes. Avoid loop counters if the order can change.
- **Log the same set of IDs** in every condition. Examples logged in only one run
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
between two runs, and **output changed** when the text differs. Log the
measurement your conclusion depends on here, such as a refusal label, a score,
or a probability, so a reviewer can see which examples moved.

## Seeds

Cloud looks for `seed` or `random_seed` in `generation` first, then in
`config`, and compares the first one it finds in each run. Put the seed in the
same place in every condition.

## Metric definitions

```python
metric_definitions={
    "refusal_rate": {"description": "Share of prompts whose response declines to help."},
}
```

Each description appears on the comparison page beneath the metric. If two runs
report the same metric name with different definitions, the check reports a
difference, so you know the numbers are not measuring the same thing. Cloud
compares a definition as a whole, so any other key you add to it counts too.

When a metric is the mean of a per-example field, name that field:

```python
metric_definitions={
    "refusal_rate": {"description": "Share of prompts refused.", "example_field": "refused"},
}
```

Cloud then computes each difference in `refusal_rate` from `refused` over the
matched examples, with a 95% paired-bootstrap interval. A control that "has no
effect" needs that interval to show how close to zero it is. Without
`example_field`, Cloud shows the difference alone, and the draft finding lists
the missing interval as a candidate limitation.

## A checklist before you compare

- [ ] Same `project` in every condition
- [ ] `model` includes `revision`
- [ ] `dataset` includes `id`, `revision` and `split`
- [ ] Same `generation` settings and seed
- [ ] Same example IDs with identical inputs
- [ ] `intervention` recorded on every condition except the reference
- [ ] `metric_definitions` for every metric you log, with `example_field` where it applies
