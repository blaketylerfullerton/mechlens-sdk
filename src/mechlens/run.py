from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
import warnings
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import CloudClient, UploadReceipt
from .errors import MechLensConfigurationError, MechLensWarning

if TYPE_CHECKING:
    from typing_extensions import Self

DEFAULT_API_URL = "https://mechlens-cloud-fgstc.ondigitalocean.app"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _json_copy(value: Any, *, label: str) -> Any:
    try:
        encoded = json.dumps(value, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain only finite JSON values") from exc


class Run:
    """One experiment run, recorded locally and uploaded when finished.

    Create runs with [`start_run`][mechlens.start_run] rather than directly. A run can
    also be used as a context manager: leaving the `with` block without an exception
    calls [`finish`][mechlens.Run.finish].

    Attributes:
        data: The run record that will be saved and uploaded.
        local_path: Where the finished run is written as JSON.
    """

    def __init__(self, data: dict[str, Any], *, client: CloudClient, local_dir: Path) -> None:
        self.data = data
        self.client = client
        self.local_path = local_dir / f"{data['id']}.json"
        self._example_ids: set[str] = set()
        self._sealed = False
        self._receipt: UploadReceipt | None = None

    def log_example(self, *, id: str, input: str, output: str, **fields: Any) -> None:
        """Record one input and the model's output for it.

        Use the same `id` for the same prompt in every run you want to compare;
        MechLens matches examples across runs by ID.

        Args:
            id: Stable identifier for this example, unique within the run.
            input: The prompt or input given to the model.
            output: What the model produced.
            **fields: Per-example measurements such as `refused=True` or
                `helpfulness=4`. Values must be JSON-serializable. Cloud reports an
                example as "behavior changed" when these fields differ between runs.

        Raises:
            ValueError: The ID is empty or already logged, or `fields` is not
                JSON-serializable.
            TypeError: `input` or `output` is not a string.
            RuntimeError: The run is already finished.
        """
        self._ensure_open()
        if not isinstance(id, str) or not id:
            raise ValueError("example id must be a non-empty string")
        if id in self._example_ids:
            raise ValueError(f"example id {id!r} was already logged")
        if not isinstance(input, str) or not isinstance(output, str):
            raise TypeError("example input and output must be strings")
        extra = _json_copy(fields, label="example fields")
        forbidden = {"id", "input", "output"}.intersection(extra)
        if forbidden:
            raise ValueError(f"example fields cannot replace {sorted(forbidden)}")
        self.data["examples"].append({"id": id, "input": input, "output": output, **extra})
        self._example_ids.add(id)

    def log_metrics(self, metrics: Mapping[str, Any]) -> None:
        """Record run-level metrics, merging with any logged earlier.

        Args:
            metrics: Metric names mapped to JSON-serializable values. Numbers must be
                finite. Names containing `rate` are shown as percentages in Cloud.

        Raises:
            ValueError: A key is empty, a value is not JSON-serializable, or a number
                is NaN or infinite.
            RuntimeError: The run is already finished.
        """
        self._ensure_open()
        if not isinstance(metrics, Mapping) or not all(isinstance(key, str) and key for key in metrics):
            raise ValueError("metrics must be a mapping with non-empty string keys")
        clean = _json_copy(dict(metrics), label="metrics")
        for key, value in clean.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
                raise ValueError(f"metric {key!r} must be finite")
        self.data["metrics"].update(clean)

    def finish(self) -> UploadReceipt:
        """Seal the run, save it to disk, then upload it.

        The run is written to [`local_path`][mechlens.Run] before any network call,
        so a failed upload never loses data. Calling `finish` again returns the same
        receipt without uploading twice.

        Returns:
            The uploaded run's ID and its Cloud URL.

        Raises:
            MechLensUploadError: The upload failed. The local copy is kept. If the
                error's `retryable` is true, call
                [`retry_upload`][mechlens.Run.retry_upload]; otherwise its message
                says what to fix.
        """
        if self._receipt is not None:
            return self._receipt
        if not self._sealed:
            self.data["finished_at"] = _now()
            self._sealed = True
            self._warn_unlogged_reported_metrics()
            self._warn_unlogged_expected_metrics()
            self._warn_unlinked_metrics()
            self._save_local()
        return self.retry_upload()

    def retry_upload(self) -> UploadReceipt:
        """Upload a finished run whose earlier upload failed.

        Uploads use the run ID as an idempotency key, so retrying never creates a
        duplicate run in Cloud.

        Returns:
            The uploaded run's ID and its Cloud URL.

        Raises:
            RuntimeError: The run has not been finished.
            MechLensUploadError: The upload failed again.
        """
        if not self._sealed:
            raise RuntimeError("finish the run before retrying its upload")
        if self._receipt is None:
            self._receipt = self.client.upload_run(self.data, local_path=self.local_path)
        return self._receipt

    def _save_local(self) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.local_path.parent, prefix=f".{self.local_path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(self.data, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, self.local_path)

    def _warn_unlogged_reported_metrics(self) -> None:
        paper = (self.data.get("experiment") or {}).get("reproduces") or {}
        missing = sorted(set(paper.get("reported") or {}) - set(self.data["metrics"]))
        if missing:
            warnings.warn(
                f"run {self.data['name']!r} reports paper values for {missing} but never logged them with "
                "log_metrics; Cloud will show them as 'not logged'",
                MechLensWarning,
                stacklevel=3,
            )

    def _warn_unlogged_expected_metrics(self) -> None:
        condition = (self.data.get("experiment") or {}).get("condition") or {}
        missing = sorted(set(condition.get("expect") or {}) - set(self.data["metrics"]))
        if missing:
            warnings.warn(
                f"condition {self.data['name']!r} declares expectations for {missing} but never logged them "
                "with log_metrics; Cloud will show them as 'not logged'",
                MechLensWarning,
                stacklevel=3,
            )

    def _warn_unlinked_metrics(self) -> None:
        """Point at the example field a metric seems to average, so Cloud can compute its interval."""
        if "experiment" not in self.data or not self.data["examples"]:
            return
        definitions = self.data.get("metric_definitions") or {}
        examples = self.data["examples"]
        means: dict[str, float] = {}
        for key in set(examples[0]) - {"id", "input", "output"}:
            values = [example.get(key) for example in examples]
            if all(isinstance(value, (bool, int, float)) for value in values):
                means[key] = sum(values) / len(values)
        for metric, value in sorted(self.data["metrics"].items()):
            definition = definitions.get(metric)
            linked = definition.get("example_field") if isinstance(definition, Mapping) else None
            if linked is not None:
                if linked not in means:
                    warnings.warn(
                        f"metric {metric!r} is linked to example field {linked!r}, but not every example in "
                        f"condition {self.data['name']!r} has a numeric {linked!r}; Cloud cannot compute its interval",
                        MechLensWarning,
                        stacklevel=3,
                    )
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            matches = sorted(key for key, mean in means.items() if math.isclose(mean, value, rel_tol=1e-9, abs_tol=1e-12))
            if matches:
                fields = " or ".join(repr(key) for key in matches)
                warnings.warn(
                    f"metric {metric!r} equals the mean of example field {fields}; add "
                    f"\"example_field\": {matches[0]!r} to its metric definition so Cloud can show its interval",
                    MechLensWarning,
                    stacklevel=3,
                )

    def _ensure_open(self) -> None:
        if self._sealed:
            raise RuntimeError("this run is finished and cannot be changed")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.finish()
        return False


def start_run(
    *,
    project: str,
    name: str,
    model: Mapping[str, Any],
    config: Mapping[str, Any],
    question: str,
    dataset: Mapping[str, Any] | None = None,
    sae: Mapping[str, Any] | None = None,
    intervention: Mapping[str, Any] | None = None,
    generation: Mapping[str, Any] | None = None,
    metric_definitions: Mapping[str, Any] | None = None,
    code_commit: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    local_dir: str | Path | None = None,
    client: CloudClient | None = None,
) -> Run:
    """Create a local-first experiment run ready to receive examples and metrics.

    Everything except `project`, `name`, `model`, `config` and `question` is optional,
    but Cloud can only check what you record: a field missing from either run is
    reported as unknown rather than assumed to match.

    Args:
        project: Groups runs that can be compared, such as a baseline and its
            intervention.
        name: This run's label within the project. A name containing `baseline` or
            `control` is chosen as the default baseline in Cloud.
        model: Must include `id`. Include `revision` so the comparison can confirm
            both runs used the same weights.
        config: Any other settings for this run, such as `seed` or
            `steering_strength`.
        question: The research question the run helps answer.
        dataset: Where the examples came from, ideally with `id`, `revision` and
            `split`.
        sae: The sparse autoencoder used, if any.
        intervention: What this run changes relative to the baseline. Leave it out of
            the baseline run.
        generation: Decoding settings such as `temperature` and `max_new_tokens`.
        metric_definitions: Metric names mapped to how each is calculated, e.g.
            `{"refusal_rate": {"description": "..."}}`.
        code_commit: Commit of the code that produced the run. Detected with
            `git rev-parse HEAD` when omitted.
        api_key: Overrides the `MECHLENS_API_KEY` environment variable.
        base_url: Overrides `MECHLENS_API_URL`. Defaults to MechLens Cloud,
            `https://mechlens-cloud-fgstc.ondigitalocean.app`.
        local_dir: Overrides `MECHLENS_DIR`, where finished runs are saved.
            Defaults to `.mechlens/runs`.
        client: A preconfigured [`CloudClient`][mechlens.CloudClient], mainly for
            tests. When given, `api_key` and `base_url` are ignored.

    Returns:
        An open run. Log examples and metrics, then call
        [`finish`][mechlens.Run.finish].

    Raises:
        ValueError: A required argument is empty or not JSON-serializable.
        TypeError: `config` is not a mapping.
        MechLensConfigurationError: No API key was passed or set in the environment.
    """
    for label, value in (("project", project), ("name", name), ("question", question)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")
    if not isinstance(model, Mapping) or not isinstance(model.get("id"), str) or not model["id"]:
        raise ValueError("model must include a non-empty string id")
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")

    if client is None:
        resolved_key = api_key or os.environ.get("MECHLENS_API_KEY")
        if not resolved_key:
            raise MechLensConfigurationError("Set MECHLENS_API_KEY or pass api_key to start_run")
        resolved_url = base_url or os.environ.get("MECHLENS_API_URL", DEFAULT_API_URL)
        client = CloudClient(api_key=resolved_key, base_url=resolved_url)

    root = Path(local_dir or os.environ.get("MECHLENS_DIR", ".mechlens/runs")).expanduser()
    data = {
        "schema_version": 1,
        "id": str(uuid.uuid4()),
        "project": project.strip(),
        "name": name.strip(),
        "question": question.strip(),
        "created_at": _now(),
        "finished_at": None,
        "model": _json_copy(dict(model), label="model"),
        "code_commit": code_commit if code_commit is not None else _git_commit(),
        "dataset": _json_copy(dict(dataset), label="dataset") if dataset is not None else None,
        "sae": _json_copy(dict(sae), label="sae") if sae is not None else None,
        "intervention": _json_copy(dict(intervention), label="intervention") if intervention is not None else None,
        "generation": _json_copy(dict(generation), label="generation") if generation is not None else None,
        "config": _json_copy(dict(config), label="config"),
        "metric_definitions": (
            _json_copy(dict(metric_definitions), label="metric_definitions")
            if metric_definitions is not None
            else None
        ),
        "metrics": {},
        "examples": [],
    }
    return Run(deepcopy(data), client=client, local_dir=root)

