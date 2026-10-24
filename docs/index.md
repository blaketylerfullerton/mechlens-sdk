# MechLens SDK

The MechLens SDK records model experiments from the Python code you already have
and sends them to MechLens Cloud, where you compare a reference run against
interventions and controls, review the evidence, and publish a finding.

Your code still loads the model, runs the intervention, and calculates the
metrics. The SDK adds only a few calls:

```python
import mechlens

exp = mechlens.experiment(
    question="Does steering this feature reduce refusals?",
    model={"id": "google/gemma-2-2b-it", "revision": "main"},
    config={"seed": 42},
)

with exp.reference() as run:
    run.log_example(id="lockout-001", input=prompt, output=answer, refused=True)
    run.log_metrics({"refusal_rate": 1.0})

with exp.intervention("steer-4521", intervention={"feature_id": 4521, "steering_strength": -4.0}) as run:
    run.log_example(id="lockout-001", input=prompt, output=steered_answer, refused=False)
    run.log_metrics({"refusal_rate": 0.0})

print(exp.url)
```

The SDK depends only on `httpx` and `python-dotenv`. It does not need Torch,
TransformerLens, or any SAE library.

## How it fits together

1. **Record the conditions** over the same examples: a reference, and the
   interventions and controls compared with it.
2. **Cloud compares each with the reference** field by field: model, dataset,
   seed, config, metric definitions, and which examples match.
3. **You review the evidence**: metric changes with their intervals, beside
   what you expected, and the examples whose behavior changed.
4. **You write a finding**, with a conclusion and its limitations, and
   publish it as a page anyone with the link can view.

## Where to go next

- New here? Start with the [Quickstart](quickstart.md).
- Getting a warning on the comparison page? Read
  [Recording comparable conditions](comparable-runs.md).
- Wondering what "unknown" or "differs" means? See
  [What the checks mean](integrity-checks.md).
- Looking up an argument? See the [API reference](reference.md).
