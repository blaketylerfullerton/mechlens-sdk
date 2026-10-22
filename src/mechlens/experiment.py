from __future__ import annotations

import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import CloudClient
from .run import Run, _json_copy, start_run

ROLES = ("baseline", "intervention")


@dataclass(frozen=True)
class Paper:
    """The paper an experiment reproduces, and the values it reports.

    Attributes:
        arxiv: The arXiv ID, such as `"2406.11717"`.
        version: The arXiv version the reported values come from, such as `"v3"`.
        reported: Metric names mapped to the paper's value for each role, e.g.
            `{"refusal_rate": {"baseline": 0.95, "intervention": 0.01}}`. Use the
            same metric names you pass to `log_metrics`, so Cloud can put the
            paper's numbers beside yours.
        where: Where in the paper the values appear, such as `"Table 10"`.
    """

    arxiv: str
    version: str | None = None
    reported: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    where: str | None = None

    def to_json(self) -> dict[str, Any]:
        if not isinstance(self.arxiv, str) or not self.arxiv.strip():
            raise ValueError("Paper.arxiv must be a non-empty arXiv ID")
        reported: dict[str, dict[str, float]] = {}
        for metric, values in self.reported.items():
            if not isinstance(values, Mapping) or not set(values) <= set(ROLES):
                raise ValueError(f"reported[{metric!r}] must map 'baseline' and/or 'intervention' to a number")
            for role, value in values.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"reported[{metric!r}][{role!r}] must be a finite number")
            reported[metric] = {role: float(value) for role, value in values.items()}
        return {"arxiv": self.arxiv.strip(), "version": self.version, "reported": reported, "where": self.where}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "experiment"


class Experiment:
    """A baseline and an intervention run declared once. Create it with [`experiment`][mechlens.experiment]."""

    def __init__(self, *, declaration: dict[str, Any], shared: dict[str, Any]) -> None:
        self.declaration = declaration
        self.shared = shared
        self.project: str = shared["project"]
        self.runs: dict[str, Run] = {}
        self._announced = False

    def baseline(self, **overrides: Any) -> Run:
        """Start the baseline run.

        Args:
            **overrides: Any [`start_run`][mechlens.start_run] argument, replacing
                the shared value for this run only. Cloud's comparison checks
                report any shared field you change.

        Returns:
            An open run, usable as a context manager.
        """
        return self._start("baseline", overrides)

    def intervention(self, **overrides: Any) -> Run:
        """Start the intervention run. Pass `intervention={...}` to describe what it changes.

        Args:
            **overrides: Any [`start_run`][mechlens.start_run] argument, replacing
                the shared value for this run only.

        Returns:
            An open run, usable as a context manager.
        """
        return self._start("intervention", overrides)

    @property
    def url(self) -> str | None:
        """The comparison page, once both runs have finished and uploaded; otherwise `None`."""
        baseline, intervention = self.runs.get("baseline"), self.runs.get("intervention")
        if not (baseline and intervention and baseline._receipt and intervention._receipt):
            return None
        separator = "&" if "?" in intervention._receipt.url else "?"
        return f"{intervention._receipt.url}{separator}baseline_id={baseline._receipt.run_id}"

    def _start(self, role: str, overrides: dict[str, Any]) -> Run:
        if "project" in overrides:
            raise ValueError("project is shared by the experiment's runs; pass it to mechlens.experiment()")
        if not self._announced:
            print(f"mechlens: recording to project '{self.project}'", file=sys.stderr)
            self._announced = True
        run = start_run(**{"name": role, **self.shared, **overrides})
        run.data["schema_version"] = 2
        run.data["experiment"] = {"role": role, **self.declaration}
        self.runs[role] = run
        return run


def experiment(
    *,
    question: str,
    model: Mapping[str, Any],
    claim: str | None = None,
    reproduces: Paper | None = None,
    deviations: Sequence[str] = (),
    project: str | None = None,
    config: Mapping[str, Any] | None = None,
    dataset: Mapping[str, Any] | None = None,
    sae: Mapping[str, Any] | None = None,
    generation: Mapping[str, Any] | None = None,
    metric_definitions: Mapping[str, Any] | None = None,
    code_commit: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    local_dir: str | Path | None = None,
    client: CloudClient | None = None,
) -> Experiment:
    """Declare a baseline-versus-intervention experiment once, then record its two runs.

    Everything Cloud needs to draft the finding lives here: the question, the
    claim, the deviations from any paper you reproduce, and the paper's
    reported values. The shared arguments apply to both runs, so the runs are
    comparable by construction. No network call is made until a run finishes.

    Args:
        question: The research question both runs help answer.
        model: Shared by both runs. Must include `id`; include `revision`.
        claim: The specific, checkable claim under test.
        reproduces: The paper this experiment reproduces, with its reported values.
        deviations: Every way this experiment knowingly differs from the paper
            or the intended protocol. Each becomes a candidate limitation in Cloud.
        project: Groups the two runs. Defaults to `reproduce-<arxiv-id>` when
            `reproduces` is set, otherwise a slug of `question`.
        config: Shared settings, such as `seed`. Defaults to `{}`.
        dataset: Shared dataset, ideally with `id`, `revision` and `split`.
        sae: Shared SAE details, if any.
        generation: Shared decoding settings.
        metric_definitions: Shared metric definitions.
        code_commit: Overrides the automatically detected commit.
        api_key: Overrides `MECHLENS_API_KEY`.
        base_url: Overrides `MECHLENS_API_URL`.
        local_dir: Overrides `MECHLENS_DIR`.
        client: A preconfigured [`CloudClient`][mechlens.CloudClient], mainly for tests.

    Returns:
        An experiment. Record each run with `with exp.baseline() as run:` and
        `with exp.intervention(intervention={...}) as run:`, then open `exp.url`.

    Raises:
        ValueError: The question is empty, a deviation is blank, or the paper's
            reported values are malformed.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if isinstance(deviations, str) or any(not isinstance(d, str) or not d.strip() for d in deviations):
        raise ValueError("deviations must be a list of non-empty strings")
    if reproduces is not None and not isinstance(reproduces, Paper):
        raise TypeError("reproduces must be a mechlens.Paper")

    declaration = {
        "claim": claim.strip() if claim and claim.strip() else None,
        "deviations": [d.strip() for d in deviations],
        "reproduces": reproduces.to_json() if reproduces else None,
    }
    _json_copy(declaration, label="experiment declaration")
    default_project = f"reproduce-{_slug(reproduces.arxiv)}" if reproduces else _slug(question)
    shared = {
        "project": (project or default_project).strip(),
        "question": question,
        "model": model,
        "config": config if config is not None else {},
        "dataset": dataset,
        "sae": sae,
        "generation": generation,
        "metric_definitions": metric_definitions,
        "code_commit": code_commit,
        "api_key": api_key,
        "base_url": base_url,
        "local_dir": local_dir,
        "client": client,
    }
    return Experiment(declaration=declaration, shared=shared)
