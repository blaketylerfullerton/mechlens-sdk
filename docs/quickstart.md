# Quickstart

This walkthrough takes you from an empty environment to a baseline and an
intervention run side by side in MechLens Cloud.

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

Describe the experiment once. Everything shared by the two runs goes here, so
they are comparable by construction. Here `generate`, `is_refusal` and
`prompts` stand in for your own code and data.

```python
import mechlens

exp = mechlens.experiment(
    question="Does negatively steering SAE feature 4521 reduce refusals on benign prompts?",
    claim="Steering feature 4521 at -4.0 lowers the refusal rate on borderline-benign prompts.",
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
        "refusal_rate": {"description": "Share of prompts whose response declines to help."},
    },
    config={"seed": 42},
)
```

`deviations` lists every way the experiment knowingly falls short of the ideal
protocol. Each one becomes a candidate limitation when you write the finding.

## 4. Record both runs

Run the same examples, with the same IDs, through both conditions. Only the
intervention run describes what it changes.

```python
def record(run, answer_fn):
    refusals = 0
    for example in prompts:
        answer = answer_fn(example["prompt"])
        refused = is_refusal(answer)
        refusals += refused
        run.log_example(id=example["id"], input=example["prompt"], output=answer, refused=refused)
    run.log_metrics({"refusal_rate": refusals / len(prompts)})


with exp.baseline() as run:
    record(run, generate)

with exp.intervention(
    intervention={"type": "sae_feature_steering", "feature_id": 4521, "steering_strength": -4.0},
) as run:
    record(run, lambda prompt: generate_with_steering(prompt, feature_id=4521, strength=-4.0))

print(exp.url)
```

Leaving each `with` block saves the run locally and uploads it. The project
name is chosen for you and printed when the first run starts; pass
`project=` to `experiment()` to choose your own.

## 5. Review the draft and write the finding

Open `exp.url`. Cloud pairs the two runs by their declared roles and shows:

- whether the two runs evaluated the same model, dataset, and examples
- each metric's baseline value, intervention value, and change
- the examples whose recorded behavior changed, side by side
- a field-by-field table of [comparison checks](integrity-checks.md)
- a **draft finding**: your claim, the protocol, and candidate limitations
  from your declared deviations and from every check Cloud couldn't settle

Add the limitations that apply, write the conclusion in your own words, and
publish when you are ready to share. Cloud never writes the conclusion for you.

### Reproducing a paper

Add the paper and the values it reports. Use the metric names you log, so Cloud
can show the paper's numbers beside yours:

```python
exp = mechlens.experiment(
    question="Does ablating a single refusal direction remove refusals?",
    claim="Ablating one difference-in-means direction drops refusal from 0.95 to 0.01.",
    reproduces=mechlens.Paper(
        arxiv="2406.11717",
        version="v3",
        reported={"refusal_rate": {"baseline": 0.95, "intervention": 0.01}},
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
it can't draft a finding because nothing declares the claim or the roles.

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
  is wrong or revoked; a `422` means Cloud rejected the run's contents. Fix the
  cause and record the run again.

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
