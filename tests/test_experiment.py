import json
import warnings

import httpx
import pytest

import mechlens


def recording_client(uploads):
    def accept(request):
        body = json.loads(request.content)
        uploads.append(body)
        return httpx.Response(201, json={"run_id": body["id"], "url": f"https://cloud.example/app/runs/{body['id']}"})

    return mechlens.CloudClient(api_key="k", base_url="https://cloud.example", transport=httpx.MockTransport(accept))


def specificity(tmp_path, uploads, **changes):
    arguments = {
        "question": "Is the refusal direction specific?",
        "claim": "Only ablating the refusal direction removes refusal on JailbreakBench.",
        "model": {"id": "google/gemma-2-2b-it", "revision": "main"},
        "dataset": {"id": "jailbreakbench", "split": "harmful"},
        "metric_definitions": {"refusal_rate": {"description": "Share refused.", "example_field": "refused"}},
        "config": {"seed": 42},
        "code_commit": "abc",
        "client": recording_client(uploads),
        "local_dir": tmp_path,
    }
    arguments.update(changes)
    return mechlens.experiment(**arguments)


def log_refusals(run, refused):
    for i, value in enumerate(refused):
        run.log_example(id=f"p{i}", input="prompt", output="output", refused=value)
    run.log_metrics({"refusal_rate": sum(refused) / len(refused)})


def test_reference_intervention_and_control_record_their_kinds_and_declarations(tmp_path):
    uploads = []
    exp = specificity(tmp_path, uploads)
    with exp.reference() as run:
        log_refusals(run, [True, True, True, False])
    with exp.intervention(
        "ablate-refusal-direction",
        intervention={"type": "directional_ablation"},
        expect={"refusal_rate": "decrease"},
        compare_to=["ablate-random-directions"],
    ) as run:
        log_refusals(run, [False, False, False, False])
    with exp.control(
        "ablate-random-directions",
        intervention={"type": "directional_ablation", "direction": "random"},
        expect={"refusal_rate": "no_effect"},
    ) as run:
        log_refusals(run, [True, True, False, True])

    conditions = [upload["experiment"]["condition"] for upload in uploads]
    assert conditions == [
        {"name": "reference", "kind": "reference"},
        {
            "name": "ablate-refusal-direction",
            "kind": "intervention",
            "expect": {"refusal_rate": "decrease"},
            "compare_to": ["ablate-random-directions"],
        },
        {
            "name": "ablate-random-directions",
            "kind": "control",
            "expect": {"refusal_rate": "no_effect"},
            "compare_to": [],
        },
    ]
    assert {upload["schema_version"] for upload in uploads} == {3}
    assert {upload["experiment"]["id"] for upload in uploads} == {exp.id}
    assert [upload["name"] for upload in uploads] == [c["name"] for c in conditions]
    assert set(exp.runs) == {c["name"] for c in conditions}


def test_sweep_conditions_are_named_from_series_and_level(tmp_path):
    uploads = []
    exp = specificity(tmp_path, uploads)
    for coefficient in (0.25, 1.0):
        with exp.intervention(
            series="addition",
            level=coefficient,
            intervention={"type": "activation_addition", "coefficient": coefficient},
            expect={"refusal_rate": "increase"},
        ) as run:
            log_refusals(run, [True, False])

    assert [upload["name"] for upload in uploads] == ["addition@0.25", "addition@1"]
    assert uploads[1]["experiment"]["condition"]["series"] == "addition"
    assert uploads[1]["experiment"]["condition"]["level"] == 1.0


def test_experiment_id_is_stable_across_processes_and_follows_the_claim(tmp_path):
    first = specificity(tmp_path, [])
    second = specificity(tmp_path, [])  # the same script, run as another job
    assert first.id == second.id
    assert first.id.startswith("is-the-refusal-direction-specific-")
    assert specificity(tmp_path, [], claim="A different claim.").id != first.id
    assert specificity(tmp_path, [], project="elsewhere").id != first.id
    assert specificity(tmp_path, [], id="refusal-specificity").id == "refusal-specificity"


def test_url_names_the_experiment_page_once_a_condition_uploads(tmp_path):
    uploads = []
    exp = specificity(tmp_path, uploads, id="refusal-specificity", project="my project")
    assert exp.url is None
    with exp.control("random") as run:
        log_refusals(run, [True])
    assert exp.url == "https://cloud.example/app/experiments/my%20project/refusal-specificity"


def test_expected_metric_never_logged_warns_but_still_uploads(tmp_path):
    uploads = []
    exp = specificity(tmp_path, uploads)
    run = exp.intervention(expect={"refusal_rate": "decrease"})
    run.log_metrics({"refusal_score": 0.1})
    with pytest.warns(mechlens.MechLensWarning, match="declares expectations for \\['refusal_rate'\\]"):
        run.finish()
    assert len(uploads) == 1


def test_finish_points_at_the_example_field_a_metric_averages(tmp_path):
    run = specificity(tmp_path, [], metric_definitions=None).reference()
    log_refusals(run, [True, False, False, False])
    with pytest.warns(mechlens.MechLensWarning, match="example field 'refused'.*\"example_field\": 'refused'"):
        run.finish()

    linked = specificity(tmp_path, [])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with linked.reference() as run:
            log_refusals(run, [True, False, False, False])

    run = specificity(tmp_path, []).reference()
    run.log_example(id="p0", input="i", output="o")
    run.log_metrics({"refusal_rate": 0.0})
    with pytest.warns(mechlens.MechLensWarning, match="not every example .* has a numeric 'refused'"):
        run.finish()


def test_plain_runs_get_no_example_field_hint(tmp_path):
    run = mechlens.start_run(
        project="p", name="n", model={"id": "m"}, config={}, question="q", code_commit="abc",
        client=recording_client([]), local_dir=tmp_path,
    )
    run.log_example(id="a", input="i", output="o", refused=True)
    run.log_metrics({"refusal_rate": 1.0})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        run.finish()


def test_paper_values_are_keyed_by_condition_name(tmp_path):
    uploads = []
    paper = mechlens.Paper(arxiv="2406.11717", reported={"refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}})
    with specificity(tmp_path, uploads, reproduces=paper).reference() as run:
        log_refusals(run, [True])
    assert uploads[0]["experiment"]["reproduces"]["reported"] == {
        "refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}
    }
    with pytest.raises(ValueError, match="condition names to numbers"):
        mechlens.Paper(arxiv="1", reported={"refusal_rate": {"": 0.5}}).to_json()


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda exp: exp.control(), "control\\(\\) needs a name"),
        (lambda exp: exp.intervention("x", series="addition"), "series and level go together"),
        (lambda exp: exp.intervention("x", level=1.0), "series and level go together"),
        (lambda exp: exp.intervention(series="addition", level=float("inf")), "finite number"),
        (lambda exp: exp.intervention(series="addition", level=True), "finite number"),
        (lambda exp: exp.intervention("x", expect={"refusal_rate": "down"}), "must be one of"),
        (lambda exp: exp.intervention("x", compare_to="control"), "list of condition names"),
        (lambda exp: exp.intervention("x", compare_to=["x"]), "compared with itself"),
        (lambda exp: exp.intervention(" "), "non-empty string"),
    ],
)
def test_condition_arguments_are_validated_before_the_run_starts(tmp_path, call, message):
    with pytest.raises(ValueError, match=message):
        call(specificity(tmp_path, []))


def test_names_are_unique_and_there_is_one_reference(tmp_path):
    exp = specificity(tmp_path, [])
    exp.reference()
    with pytest.raises(ValueError, match="already has a reference"):
        exp.baseline()
    with pytest.raises(ValueError, match="already recorded"):
        exp.control("reference")
    with pytest.raises(ValueError, match="every condition is compared with already"):
        exp.intervention("x", compare_to=["reference"])
    exp.intervention("x")
    with pytest.raises(ValueError, match="already recorded"):
        exp.intervention("x")


def test_experiment_level_inputs_are_validated(tmp_path):
    with pytest.raises(ValueError, match="id must be"):
        specificity(tmp_path, [], id="Has Spaces")
    with pytest.raises(ValueError, match="example_field"):
        specificity(tmp_path, [], metric_definitions={"refusal_rate": {"example_field": 3}})
