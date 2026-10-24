# Quickstart

This walkthrough takes you from an empty environment to a reference run, an
intervention and a control side by side in MechLens Cloud.

## 1. Install the SDK

```bash
pip install mechlens
```

The SDK needs Python 3.10 or later.

## 2. Connect to your workspace

In MechLens Cloud, open **Experiments → New experiment** and click
**Generate API key**, or create one under **Account → API keys**. The full key
is shown only once.

```bash
export MECHLENS_API_KEY="ml_your_key_here"
```

Runs upload to MechLens Cloud. To use another deployment, such as a local
Cloud during development, also set `MECHLENS_API_URL`:

```bash
export MECHLENS_API_URL="http://localhost:5175"
```

!!! warning
    Anyone with the key can upload runs to your workspace. Keep it out of
    notebooks and commits. Revoke it from **Account → API keys** if it leaks.

## 3. Declare the experiment

Describe the experiment once. Everything shared by the conditions goes here,
so they are comparable by construction. Here `generate`, `is_refusal` and
`prompts` stand in for your own code and data.

```python
import mechlens

exp = mechlens.experiment(
    question="Does negatively steering SAE feature 4521 reduce refusals on benign prompts?",
    claim="Steering feature 4521 at -4.0 lowers the refusal rate on borderline-benign prompts; a random feature does not.",
    deviations=["Refusals scored by substring matching, not human review"],
    model={"id": "google/gemma-2-2b-it", "revision": "main"},
    dataset={"id": "borderline-benign-prompts", "revision": "v1", "split": "test"},
    sae={
        "release": "gemma-scope-2b-pt-res-canonical",
        "sae_id": "layer_12/width_16k/canonical",
        "hook_point": "blocks.12.hook_resid_post",
    },
    generation={"max_new_tokens": 128, "temperature": 0.0, "do_sample": False},
    metric_definitions={
        "refusal_rate": {
            "description": "Share of prompts whose response declines to help.",
            "example_field": "refused",
        },
    },
    config={"seed": 42},
)
```

`deviations` lists every way the experiment knowingly falls short of the ideal
protocol. Each one becomes a candidate limitation when you write the finding.

`example_field` says which per-example field a metric averages. Cloud uses it
to put a confidence interval on every difference in that metric. Without it,
you get the difference alone; `finish()` warns when a metric looks like the
mean of an example field you haven't linked.

## 4. Record the conditions

Run the same examples, with the same IDs, through every condition. The
reference changes nothing; every other condition describes what it changes.

- An **intervention** changes the model in the way your claim is about.
- A **control** is one your claim predicts should *not* have the effect, such
  as steering a random feature instead.

Declare what you expect each condition to do, relative to the reference,
before you see the results. If the claim depends on a comparison between two
non-reference conditions, such as the intervention against its control,
declare that too with `compare_to`.

```python
def record(run, answer_fn):
    refusals = 0
    for example in prompts:
        answer = answer_fn(example["prompt"])
        refused = is_refusal(answer)
        refusals += refused
        run.log_example(id=example["id"], input=example["prompt"], output=answer, refused=refused)
    run.log_metrics({"refusal_rate": refusals / len(prompts)})


with exp.reference() as run:
    record(run, generate)

with exp.intervention(
    "steer-4521",
    intervention={"type": "sae_feature_steering", "feature_id": 4521, "steering_strength": -4.0},
    expect={"refusal_rate": "decrease"},
    compare_to=["steer-random-feature"],
) as run:
    record(run, lambda prompt: generate_with_steering(prompt, feature_id=4521, strength=-4.0))

with exp.control(
    "steer-random-feature",
    intervention={"type": "sae_feature_steering", "feature_id": 9113, "steering_strength": -4.0},
    expect={"refusal_rate": "no_effect"},
) as run:
    record(run, lambda prompt: generate_with_steering(prompt, feature_id=9113, strength=-4.0))

print(exp.url)
```

Leaving each `with` block saves the run locally and uploads it. The project
and experiment are chosen for you and printed when the first run starts; pass
`project=` and `id=` to `experiment()` to choose your own.

### Sweeps

For a dose-response, record one condition per level of the same `series`. The
name defaults to `<series>@<level>`, and Cloud plots the series as a curve:

```python
for strength in (-1.0, -2.0, -4.0, -8.0):
    with exp.intervention(
        series="steering_strength",
        level=strength,
        intervention={"type": "sae_feature_steering", "feature_id": 4521, "steering_strength": strength},
        expect={"refusal_rate": "decrease"},
    ) as run:
        record(run, lambda prompt: generate_with_steering(prompt, feature_id=4521, strength=strength))
```

### Conditions in separate jobs

Conditions don't have to run in one process. Run the same declaration in each
job, a job array or a restarted notebook, and record only that job's
condition; they all join one experiment, because its ID is derived from the
project, question and claim. Changing the claim starts a new experiment.

Recording a condition name again in a later process counts as a rerun: Cloud
uses the latest run and lists the earlier ones as superseded, so reruns stay
visible. Within one process, an experiment records each condition name once.

### Correcting a run

!!! note "Not yet released"
    `Correction` is in the repository but not in a published version of the
    package. It arrives with the next release.

A rerun doesn't say why it replaced the earlier run. When the earlier run was
wrong, say so with a [`Correction`][mechlens.Correction] naming that run's ID:
the `run_id` on its upload receipt, or its file in `.mechlens/runs/`.

```python
with exp.control(
    "steer-random-feature",
    intervention={"type": "sae_feature_steering", "feature_id": 9113, "steering_strength": -4.0},
    correction=mechlens.Correction(
        supersedes="f9ad0f0a-6a67-4d2e-b879-2a0f94260ec8",
        reason="The original control sampled features outside the SAE's width.",
    ),
) as run:
    record(run, lambda prompt: generate_with_steering(prompt, feature_id=9113, strength=-4.0))
```

Cloud keeps the earlier run, makes the corrected one current, and flags
findings that relied on the earlier run so you can review them. It rejects a
correction when the earlier run is no longer the condition's current run, when
the project, experiment declaration or condition name differ, or when the
corrected run finishes before the one it replaces. The reason becomes public
if an affected finding was published, so leave out secrets.

## 5. Review the draft and write the finding

Open `exp.url`. Cloud compares every condition with the reference, and shows:

- whether each condition evaluated the same model, dataset, and examples as
  the reference
- each metric's value per condition, its difference from the reference with a
  confidence interval, and your declared expectation beside it
- the examples whose recorded behavior changed, side by side
- a field-by-field table of [comparison checks](integrity-checks.md)
- a **draft finding**: your claim, the protocol, and candidate limitations
  from your declared deviations and from every check Cloud couldn't settle

Add the limitations that apply, write the conclusion in your own words, and
publish when you are ready to share. Cloud never writes the conclusion for you.

### Reproducing a paper

Add the paper and the values it reports. Use the metric names you log and the
condition names you record, so Cloud can show the paper's numbers beside
yours:

```python
exp = mechlens.experiment(
    question="Does ablating a single refusal direction remove refusals?",
    claim="Ablating one difference-in-means direction drops refusal from 0.95 to 0.01.",
    reproduces=mechlens.Paper(
        arxiv="2406.11717",
        version="v3",
        reported={"refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}},
        where="Table 10",
    ),
    deviations=["Llama-3.1 8B Instruct instead of Llama-3 8B Instruct"],
    model=...,
)
```

Cloud creates the reproduction for you, fills in its protocol from the runs,
and adds a paper-vs-observed table to the draft. Deciding whether the result
reproduced is still your call.

### Recording runs one at a time

`mechlens.start_run()` records a single run with every argument given
explicitly. It still works, and Cloud compares two such runs the same way, but
it can't draft a finding because nothing declares the claim or the conditions.

## Try it without a model

The repository includes `examples/steering_demo.py`. It uploads a synthetic
baseline and steered run so you can check your key and connection before
wiring in real code:

```bash
python examples/steering_demo.py
```

Its outputs are hand-written and marked `[synthetic]`.

## If an upload fails

`finish()` writes the run to `.mechlens/runs/<run-id>.json` **before**
uploading, so nothing is lost. A failed upload raises
[`MechLensUploadError`][mechlens.MechLensUploadError], whose message includes
Cloud's explanation and what to do next.

- If `error.retryable` is true (Cloud was unreachable or had a server error),
  retry in the same process with `run.retry_upload()`.
- If it is false, retrying the same run won't help. A `401` means the API key
  is wrong or revoked; a `422` means Cloud rejected the run's contents; a
  `409` means Cloud already holds a different run with that ID, or a
  correction's target is no longer current. Fix the cause and record the run
  again.

```python
try:
    receipt = run.finish()
except mechlens.MechLensUploadError as error:
    if not error.retryable:
        raise
    print(f"Saved locally at {error.local_path}; retrying")
    receipt = run.retry_upload()
```

Retries never create duplicate runs: each upload is sent with the run ID as its
idempotency key.
