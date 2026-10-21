# Quickstart

This walkthrough takes you from an empty environment to a baseline and an
intervention run side by side in MechLens Cloud.

## 1. Install the SDK

```bash
pip install mechlens
```

!!! note "Not on PyPI yet"
    Until the package is published, install it from a checkout of the SDK
    repository:

    ```bash
    pip install -e path/to/mechlens-sdk
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

## 3. Record the baseline

Wrap the experiment you already have. Here `generate`, `is_refusal` and
`prompts` stand in for your own code and data.

```python
import mechlens

QUESTION = "Does negatively steering SAE feature 4521 reduce refusals on benign prompts?"
MODEL = {"id": "google/gemma-2-2b-it", "revision": "main"}
DATASET = {"id": "borderline-benign-prompts", "revision": "v1", "split": "test"}
SAE = {
    "release": "gemma-scope-2b-pt-res-canonical",
    "sae_id": "layer_12/width_16k/canonical",
    "hook_point": "blocks.12.hook_resid_post",
}
GENERATION = {"max_new_tokens": 128, "temperature": 0.0, "do_sample": False}
METRICS = {
    "refusal_rate": {"description": "Share of prompts whose response declines to help."},
}

run = mechlens.start_run(
    project="refusal-steering",
    name="baseline",
    model=MODEL,
    question=QUESTION,
    dataset=DATASET,
    sae=SAE,
    generation=GENERATION,
    metric_definitions=METRICS,
    config={"seed": 42},
)

refusals = 0
for example in prompts:
    answer = generate(example["prompt"])
    refused = is_refusal(answer)
    refusals += refused
    run.log_example(id=example["id"], input=example["prompt"], output=answer, refused=refused)

run.log_metrics({"refusal_rate": refusals / len(prompts)})
print(run.finish().url)
```

## 4. Record the intervention

Use the same `project`, the same examples with the same IDs, and the same
model, dataset and generation settings. Change only the thing you are testing,
and describe it in `intervention`.

```python
run = mechlens.start_run(
    project="refusal-steering",
    name="steered",
    model=MODEL,
    question=QUESTION,
    dataset=DATASET,
    sae=SAE,
    generation=GENERATION,
    metric_definitions=METRICS,
    intervention={
        "type": "sae_feature_steering",
        "feature_id": 4521,
        "steering_strength": -4.0,
    },
    config={"seed": 42},
)

refusals = 0
for example in prompts:
    answer = generate_with_steering(example["prompt"], feature_id=4521, strength=-4.0)
    refused = is_refusal(answer)
    refusals += refused
    run.log_example(id=example["id"], input=example["prompt"], output=answer, refused=refused)

run.log_metrics({"refusal_rate": refusals / len(prompts)})
print(run.finish().url)
```

## 5. Compare and write the finding

Open the URL printed by the intervention run. Because the other run's name is
`baseline`, Cloud selects it as the baseline automatically. The page shows:

- whether the two runs evaluated the same model, dataset, and examples
- each metric's baseline value, intervention value, and change
- the examples whose recorded behavior changed, side by side
- a field-by-field table of [comparison checks](integrity-checks.md)

Write a conclusion and its limitations, save them, and publish when you are
ready to share.

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
