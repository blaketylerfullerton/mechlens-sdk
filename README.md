# MechLens Python SDK

Record mechanistic-interpretability experiments from the Python code you
already have, and compare a reference run against interventions and controls in
[MechLens Cloud](https://mechlens.dev).

Your code still loads the model, runs the intervention, and calculates the
metrics. The SDK records what you ran so Cloud can check the runs are
comparable, show which examples changed, and help you publish a finding with
its evidence and limitations attached.

It depends only on `httpx` and `python-dotenv`: no Torch, TransformerLens, or
SAE libraries.

## Install

```bash
pip install mechlens
```

Requires Python 3.10 or later.

## Connect to your workspace

In MechLens Cloud, open **Experiments → New experiment** and generate an API
key, or create one under **Account → API keys**.

```bash
export MECHLENS_API_KEY="ml_your_key_here"
```

## Record an experiment

Declare the experiment once, then record a reference run and the
interventions and controls compared with it, over the same examples:

```python
import mechlens

exp = mechlens.experiment(
    question="Does steering SAE feature 4521 reduce refusals on benign prompts?",
    claim="Steering feature 4521 at -4.0 lowers the refusal rate; a random feature does not.",
    deviations=["Refusals scored by substring matching"],
    model={"id": "google/gemma-2-2b-it", "revision": "main"},
    dataset={"id": "borderline-benign-prompts", "revision": "v1", "split": "test"},
    generation={"temperature": 0.0, "max_new_tokens": 128},
    metric_definitions={"refusal_rate": {"description": "Share of prompts refused.", "example_field": "refused"}},
    config={"seed": 42},
)


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
    record(run, steered_generate)

with exp.control(
    "steer-random-feature",
    intervention={"type": "sae_feature_steering", "feature_id": "random", "steering_strength": -4.0},
    expect={"refusal_rate": "no_effect"},
) as run:
    record(run, random_steered_generate)

print(exp.url)
```

Open `exp.url` to see the experiment: every condition against the reference,
with checks that they evaluated the same model, data and examples, each
metric's difference with a confidence interval, and what you expected beside
what happened. A draft finding is built from your declaration: the claim, the
protocol, and candidate limitations. You write the conclusion.

- **Sweeps:** pass `series="steering"` and `level=-4.0` instead of a name, and
  Cloud plots the series as a curve.
- **Separate jobs:** each condition can run in its own process. Every process
  that declares the same experiment joins it.
- **Reproducing a paper?** Add
  `reproduces=mechlens.Paper(arxiv="2406.11717", reported={"refusal_rate": {"reference": 0.95, "ablate-direction": 0.01}})`,
  keyed by your condition names, and Cloud shows the paper's numbers beside
  yours.

`mechlens.start_run()` still records single runs with every argument given
explicitly.

## Good to know

- **Nothing is lost if an upload fails.** `finish()` saves the run to
  `.mechlens/runs/<run-id>.json` before uploading. A failed upload raises
  `MechLensUploadError`, whose message says what went wrong. If
  `error.retryable` is true, call `run.retry_upload()`.
- **Record the same fields in every condition.** Cloud reports a field missing
  from either side of a comparison as *unknown*, never as a match. Include `model.revision` and the
  dataset's `id`, `revision`, and `split`.
- **Configuration:** `MECHLENS_API_KEY` (required), `MECHLENS_API_URL` (another
  Cloud deployment, such as `http://localhost:5175` for local development), and
  `MECHLENS_DIR` (where runs are saved locally).

## Documentation

Full docs: **https://blaketylerfullerton.github.io/mechlens-sdk/**

- [Quickstart](https://blaketylerfullerton.github.io/mechlens-sdk/quickstart/)
- [Recording comparable conditions](https://blaketylerfullerton.github.io/mechlens-sdk/comparable-runs/)
- [What the comparison checks mean](https://blaketylerfullerton.github.io/mechlens-sdk/integrity-checks/)
- [API reference](https://blaketylerfullerton.github.io/mechlens-sdk/reference/)

Using a coding agent? Point it at [`llms-full.txt`](https://blaketylerfullerton.github.io/mechlens-sdk/llms-full.txt), every
page as one Markdown file.

## Development

```bash
git clone https://github.com/blaketylerfullerton/mechlens-sdk.git
cd mechlens-sdk
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test,docs]'
pytest
```

**Demo without a model.** `examples/steering_demo.py` uploads a synthetic
baseline and steered run, to check your key and connection. Put
`MECHLENS_API_KEY` (and optionally `MECHLENS_API_URL`) in `examples/.env`, then
run `python examples/steering_demo.py`. Its outputs are marked `[synthetic]`.

**Docs.** The docs in `docs/` build with Material for MkDocs, and the API
reference is generated from the docstrings in `src/mechlens`. Run
`mkdocs serve` to preview at http://127.0.0.1:8000; `mkdocs build` is strict,
so broken links fail.

**Releasing.** Bump `__version__` in `src/mechlens/_version.py`, commit, and
push a matching tag (`v0.1.1`). The release workflow tests, builds, and
publishes to PyPI with Trusted Publishing.

**Cloud contract.** The SDK sends `POST /api/sdk/runs` with
`Authorization: Bearer <key>` and an `Idempotency-Key` equal to the run ID.
Cloud returns `{"run_id": "...", "url": "..."}`.

## License

Apache-2.0
