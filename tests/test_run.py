import json

import httpx
import pytest

import mechlens


def client(handler):
    return mechlens.CloudClient(
        api_key="test-key",
        base_url="https://cloud.example",
        transport=httpx.MockTransport(handler),
    )


def test_finish_saves_before_upload_and_returns_receipt(tmp_path):
    observed = {}

    def accept(request):
        observed["authorization"] = request.headers["authorization"]
        observed["idempotency_key"] = request.headers["idempotency-key"]
        observed["body"] = json.loads(request.content)
        assert run.local_path.exists()
        return httpx.Response(201, json={"run_id": observed["body"]["id"], "url": "https://cloud.example/run/1"})

    run = mechlens.start_run(
        project="refusal-steering",
        name="strength-2",
        model={"id": "google/gemma-2-2b", "revision": "abc"},
        config={"steering_strength": 2.0},
        question="Does steering reduce refusals?",
        dataset={"id": "prompts", "revision": "v1"},
        code_commit="deadbeef",
        client=client(accept),
        local_dir=tmp_path,
    )
    run.log_example(id="001", input="Hello", output="Hi")
    run.log_metrics({"refusal_rate": 0.25})

    receipt = run.finish()

    assert receipt.url == "https://cloud.example/run/1"
    assert observed["authorization"] == "Bearer test-key"
    assert observed["idempotency_key"] == observed["body"]["id"]
    saved = json.loads(run.local_path.read_text())
    assert saved["examples"][0]["id"] == "001"
    assert saved["metrics"] == {"refusal_rate": 0.25}
    assert saved["sae"] is None
    assert saved["intervention"] is None
    assert saved["finished_at"].endswith("Z")


def test_failed_upload_keeps_local_copy_and_can_be_retried(tmp_path):
    attempts = 0

    def flaky(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="unavailable")
        body = json.loads(request.content)
        return httpx.Response(200, json={"run_id": body["id"], "url": "https://cloud.example/run/recovered"})

    run = mechlens.start_run(
        project="p",
        name="baseline",
        model={"id": "model"},
        config={},
        question="q",
        code_commit="abc",
        client=client(flaky),
        local_dir=tmp_path,
    )

    with pytest.raises(mechlens.MechLensUploadError) as caught:
        run.finish()
    assert caught.value.local_path == run.local_path
    assert run.local_path.exists()

    assert run.retry_upload().url.endswith("/recovered")
    assert attempts == 2


def test_duplicate_example_ids_and_changes_after_finish_are_rejected(tmp_path):
    def accept(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"run_id": body["id"], "url": "https://cloud.example/run/1"})

    run = mechlens.start_run(
        project="p",
        name="n",
        model={"id": "m"},
        config={},
        question="q",
        code_commit="abc",
        client=client(accept),
        local_dir=tmp_path,
    )
    run.log_example(id="same", input="one", output="one")
    with pytest.raises(ValueError, match="already logged"):
        run.log_example(id="same", input="two", output="two")

    run.finish()
    with pytest.raises(RuntimeError, match="finished"):
        run.log_metrics({"late": 1})


def test_missing_api_key_fails_at_start(tmp_path, monkeypatch):
    monkeypatch.delenv("MECHLENS_API_KEY", raising=False)
    with pytest.raises(mechlens.MechLensConfigurationError):
        mechlens.start_run(
            project="p",
            name="n",
            model={"id": "m"},
            config={},
            question="q",
            code_commit="abc",
            local_dir=tmp_path,
        )


def finished_upload_error(tmp_path, handler):
    run = mechlens.start_run(
        project="p",
        name="n",
        model={"id": "m"},
        config={},
        question="q",
        code_commit="abc",
        client=client(handler),
        local_dir=tmp_path,
    )
    with pytest.raises(mechlens.MechLensUploadError) as caught:
        run.finish()
    return caught.value


@pytest.mark.parametrize(
    ("response", "status", "retryable", "expected"),
    [
        (
            httpx.Response(401, json={"detail": "Invalid or revoked MechLens API key"}),
            401,
            False,
            ["Invalid or revoked MechLens API key", "Check MECHLENS_API_KEY"],
        ),
        (
            httpx.Response(422, json={"detail": [{"loc": ["body", "model", "id"], "msg": "Field required"}]}),
            422,
            False,
            ["body.model.id: Field required", "record it again"],
        ),
        (
            httpx.Response(413, text="Run exceeds the 32 MiB upload limit"),
            413,
            False,
            ["32 MiB"],
        ),
        (httpx.Response(503, text="unavailable"), 503, True, ["unavailable", "retry_upload()"]),
    ],
)
def test_rejected_upload_explains_cause_and_whether_to_retry(tmp_path, response, status, retryable, expected):
    error = finished_upload_error(tmp_path, lambda request: response)
    assert error.status_code == status
    assert error.retryable is retryable
    for text in expected:
        assert text in str(error)


def test_unreachable_cloud_names_the_url(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    error = finished_upload_error(tmp_path, refuse)
    assert error.status_code is None
    assert error.retryable
    assert "https://cloud.example" in str(error)
    assert "MECHLENS_API_URL" in str(error)


def recording_client(uploads):
    def accept(request):
        body = json.loads(request.content)
        uploads.append(body)
        return httpx.Response(201, json={"run_id": body["id"], "url": f"https://cloud.example/app/projects/p/runs/{body['id']}"})

    return client(accept)


def declared_experiment(tmp_path, uploads, **changes):
    arguments = {
        "question": "Does ablating the refusal direction remove refusals?",
        "claim": "Ablation drops refusal from 0.95 to 0.01.",
        "reproduces": mechlens.Paper(
            arxiv="2406.11717", version="v3", reported={"refusal_rate": {"baseline": 0.95, "intervention": 0.01}}, where="Table 10"
        ),
        "deviations": ["Llama-3.1 instead of Llama-3"],
        "model": {"id": "meta-llama/Llama-3.1-8B-Instruct", "revision": "abc"},
        "dataset": {"id": "jailbreakbench", "revision": "v1", "split": "test"},
        "config": {"seed": 42},
        "code_commit": "abc",
        "client": recording_client(uploads),
        "local_dir": tmp_path,
    }
    arguments.update(changes)
    return mechlens.experiment(**arguments)


def test_0_2_pair_api_records_a_two_condition_experiment(tmp_path, capsys):
    uploads = []
    exp = declared_experiment(tmp_path, uploads)
    assert exp.project == "reproduce-2406-11717"
    assert exp.url is None  # not until a condition has uploaded
    with exp.baseline() as run:
        run.log_metrics({"refusal_rate": 0.98})
    with exp.intervention(intervention={"type": "directional_ablation"}) as run:
        run.log_metrics({"refusal_rate": 0.0})

    baseline, intervention = uploads
    assert capsys.readouterr().err.count(f"recording experiment '{exp.id}' to project 'reproduce-2406-11717'") == 1
    assert [baseline["schema_version"], intervention["schema_version"]] == [3, 3]
    assert [baseline["name"], intervention["name"]] == ["baseline", "intervention"]
    assert baseline["experiment"] == {
        "id": exp.id,
        "claim": "Ablation drops refusal from 0.95 to 0.01.",
        "deviations": ["Llama-3.1 instead of Llama-3"],
        "reproduces": {
            "arxiv": "2406.11717",
            "version": "v3",
            "reported": {"refusal_rate": {"baseline": 0.95, "intervention": 0.01}},
            "where": "Table 10",
        },
        "condition": {"name": "baseline", "kind": "reference"},
    }
    assert intervention["experiment"]["condition"] == {"name": "intervention", "kind": "intervention", "compare_to": []}
    assert baseline["intervention"] is None and intervention["intervention"] == {"type": "directional_ablation"}
    assert baseline["dataset"] == intervention["dataset"] and baseline["config"] == intervention["config"]
    assert exp.url == f"https://cloud.example/app/experiments/reproduce-2406-11717/{exp.id}"


def test_unlogged_reported_metric_warns_but_still_uploads(tmp_path):
    uploads = []
    exp = declared_experiment(tmp_path, uploads)
    with pytest.warns(mechlens.MechLensWarning, match="refusal_rate"), exp.baseline() as run:
        run.log_metrics({"refusal_score": 0.98})
    assert len(uploads) == 1


def test_plain_runs_stay_schema_version_1_and_experiment_inputs_are_validated(tmp_path):
    uploads = []
    run = mechlens.start_run(
        project="p", name="n", model={"id": "m"}, config={}, question="q", code_commit="abc",
        client=recording_client(uploads), local_dir=tmp_path,
    )
    run.finish()
    assert uploads[0]["schema_version"] == 1 and "experiment" not in uploads[0]

    assert declared_experiment(tmp_path, [], reproduces=None).project == "does-ablating-the-refusal-direction-remove-refusals"
    assert declared_experiment(tmp_path, [], project="mine").project == "mine"
    with pytest.raises(ValueError, match="deviations"):
        declared_experiment(tmp_path, [], deviations=["ok", " "])
    with pytest.raises(ValueError, match="finite number"):
        declared_experiment(tmp_path, [], reproduces=mechlens.Paper(arxiv="2406.11717", reported={"x": {"baseline": float("nan")}}))
    with pytest.raises(ValueError, match="project is shared"):
        declared_experiment(tmp_path, []).baseline(project="other")
