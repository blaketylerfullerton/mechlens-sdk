# MechLens Python SDK

The lightweight client for recording an experiment in existing Python code and
sending it to MechLens Cloud. Model execution and metric calculation stay in the
researcher's code.

This package is intentionally separate from the GPU application and has no
Torch, TransformerLens, or SAE dependencies.

## Try the complete upload flow

The included demo sends a synthetic baseline and steered run with the same four
prompt IDs. It exercises local saving, API-key authentication, validation, and
Cloud ingestion without downloading a model.

Create an API key from **MechLens → Account → API keys**. Put it in
`examples/.env` (the demo loads this file automatically):

```dotenv
MECHLENS_API_KEY="ml_your_key_here"
# Omit this line to upload to MechLens Cloud. For a local Cloud:
MECHLENS_API_URL="http://localhost:5175"
```

Then run:

```bash
cd /path/to/mechlens-sdk
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python examples/steering_demo.py
```

Variables exported in your shell take priority over values in `examples/.env`.

The script prints both saved-run URLs and keeps local JSON copies under
`.mechlens/runs/`. Its outputs are clearly marked synthetic and are only for
testing the integration.

## Use it in an experiment

```python
import mechlens

run = mechlens.start_run(
    project="refusal-steering",
    name="strength-2",
    model={"id": "google/gemma-2-2b", "revision": "exact-revision"},
    config={"feature_id": 1234, "steering_strength": 2.0, "seed": 42},
    question="Does steering this feature reduce refusals?",
    dataset={"id": "refusal-prompts", "revision": "v1"},
)

for example in dataset:
    answer = generate_with_steering(example["prompt"], strength=2.0)
    run.log_example(id=example["id"], input=example["prompt"], output=answer)

run.log_metrics({"refusal_rate": measured_refusal_rate})
receipt = run.finish()
print(receipt.url)
```

Set `MECHLENS_API_KEY` to the account key. Runs upload to MechLens Cloud
(`https://mechlens-cloud-fgstc.ondigitalocean.app`); set `MECHLENS_API_URL` for another deployment, such as
`http://localhost:5175` during local development.
Finished runs are written atomically to `.mechlens/runs/<run-id>.json` before
upload. Set `MECHLENS_DIR` to choose another local directory.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest
```

## Documentation

The user docs live in `docs/` and build with Material for MkDocs. The API
reference is generated from the docstrings in `src/mechlens`, so update those
when the public API changes.

```bash
pip install -e '.[docs]'
mkdocs serve          # preview at http://127.0.0.1:8000
mkdocs build          # static site in site/ (strict: broken links fail)
```

## Cloud contract

The SDK sends `POST /api/sdk/runs` with an `Authorization: Bearer ...`
header and an `Idempotency-Key` equal to the run ID. Cloud returns:

```json
{"run_id": "...", "url": "https://.../app/projects/.../runs/..."}
```

If an upload fails, `finish()` preserves the completed local run and raises
`MechLensUploadError`. Call `run.retry_upload()` to retry during the same
process.
