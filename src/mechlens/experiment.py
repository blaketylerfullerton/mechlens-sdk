from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .client import CloudClient
from .run import Run, _json_copy, start_run

EXPECTATIONS = ("increase", "decrease", "no_effect")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


@dataclass(frozen=True)
class Paper:
    """The paper an experiment reproduces, and the values it reports.

    Attributes:
        arxiv: The arXiv ID, such as `"2406.11717"`.
        version: The arXiv version the reported values come from, such as `"v3"`.
        reported: Metric names mapped to the paper's value for each condition, e.g.
            `{"refusal_rate": {"reference": 0.95, "ablate-refusal-direction": 0.01}}`.
            Use the same metric names you pass to `log_metrics` and the same
            condition names you record, so Cloud can put the paper's numbers
            beside yours.
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
            if not isinstance(values, Mapping) or not all(isinstance(name, str) and name for name in values):
                raise ValueError(f"reported[{metric!r}] must map condition names to numbers")
            for name, value in values.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"reported[{metric!r}][{name!r}] must be a finite number")
            reported[metric] = {name: float(value) for name, value in values.items()}
        return {"arxiv": self.arxiv.strip(), "version": self.version, "reported": reported, "where": self.where}


@dataclass(frozen=True)
class Correction:
    """Declare that a run corrects one exact earlier run.

    Pass it as the `correction` of the condition that replaces the earlier run.
    Cloud keeps the earlier run, makes the corrected one current, and flags
    findings that relied on the earlier run so you can review them. Cloud
    rejects a correction unless the earlier run is the condition's current run,
    in the same project and experiment with the same declaration, and the
    corrected run finishes at or after it. A condition recorded again without a
    correction is an ordinary rerun.

    The reason becomes public evidence metadata if an affected finding was
    published. Do not include secrets or sensitive participant information.

    Attributes:
        supersedes: The ID of the run being corrected, as in its local
            `.mechlens/runs/<run-id>.json` file or its upload receipt's `run_id`.
        reason: Why the earlier run was wrong.
    """

    supersedes: str
    reason: str

    def to_json(self) -> dict[str, str]:
        if not isinstance(self.supersedes, str) or not self.supersedes.strip():
            raise ValueError("Correction.supersedes must be a non-empty run ID")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Correction.reason must be a non-empty explanation")
        return {"supersedes": self.supersedes.strip(), "reason": self.reason.strip()}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "experiment"


def _derived_id(project: str, question: str, claim: str | None) -> str:
    digest = hashlib.sha256(json.dumps([project, question, claim]).encode()).hexdigest()[:8]
    return f"{_slug(question)[:40].strip('-')}-{digest}"


def _level_label(level: float) -> str:
    return f"{level:g}"


class Experiment:
    """One reference run and the conditions compared with it, declared once.

    Create it with [`experiment`][mechlens.experiment]. Record the reference with
    [`reference`][mechlens.Experiment.reference], then any number of
    [`intervention`][mechlens.Experiment.intervention] and
    [`control`][mechlens.Experiment.control] conditions. Conditions may be
    recorded in separate processes: every process that declares the same
    experiment joins it.

    Attributes:
        id: Groups this experiment's runs in Cloud, within its project.
        project: The project the runs are recorded to.
        runs: Condition names mapped to the runs recorded by this process.
    """

    def __init__(self, *, id: str, declaration: dict[str, Any], shared: dict[str, Any]) -> None:
        self.id = id
        self.declaration = declaration
        self.shared = shared
        self.project: str = shared["project"]
        self.runs: dict[str, Run] = {}
        self._reference: str | None = None
        self._announced = False

    def reference(self, name: str = "reference", *, correction: Correction | None = None, **overrides: Any) -> Run:
        """Start the reference run, which every other condition is compared with.

        Args:
            name: The condition's name. Use the name your paper values are keyed by.
            correction: Declares that this run corrects one exact earlier run. See
                [`Correction`][mechlens.Correction].
            **overrides: Any [`start_run`][mechlens.start_run] argument, replacing
                the shared value for this run only. Cloud's comparison checks
                report any shared field you change.

        Returns:
            An open run, usable as a context manager.

        Raises:
            ValueError: A reference was already started by this experiment.
            TypeError: `correction` is not a [`Correction`][mechlens.Correction].
        """
        if self._reference is not None:
            raise ValueError(f"this experiment already has a reference, {self._reference!r}")
        run = self._start(name, {"kind": "reference"}, correction, overrides)
        self._reference = run.data["name"]
        return run

    def baseline(self, **overrides: Any) -> Run:
        """Start the reference run, named `baseline` unless `name=` says otherwise. Kept from SDK 0.2."""
        return self.reference(overrides.pop("name", "baseline"), **overrides)

    def intervention(
        self,
        name: str | None = None,
        *,
        expect: Mapping[str, str] | None = None,
        compare_to: Sequence[str] = (),
        series: str | None = None,
        level: float | None = None,
        correction: Correction | None = None,
        **overrides: Any,
    ) -> Run:
        """Start a condition that changes the model in the way the claim is about.

        Pass `intervention={...}` to describe what it changes.

        Args:
            name: The condition's name, unique within the experiment. Defaults to
                `"<series>@<level>"` in a sweep, otherwise `"intervention"`.
            expect: Metric names mapped to the change you expect relative to the
                reference: `"increase"`, `"decrease"` or `"no_effect"`. Declare it
                before you see the results; Cloud shows it beside what was observed.
            compare_to: Names of other conditions this one should also be compared
                with, such as a control. The reference is always compared.
            series: Groups conditions that differ only in `level`, such as a
                steering-coefficient sweep. Cloud plots a series as a curve.
            level: This condition's position in the series.
            correction: Declares that this run corrects one exact earlier run. See
                [`Correction`][mechlens.Correction].
            **overrides: Any [`start_run`][mechlens.start_run] argument, replacing
                the shared value for this run only.

        Returns:
            An open run, usable as a context manager.

        Raises:
            ValueError: The name is blank or already recorded by this experiment,
                `series` and `level` are not given together, `expect` or
                `compare_to` is malformed, or a condition is compared with itself.
            TypeError: `correction` is not a [`Correction`][mechlens.Correction].
        """
        if name is None and series is None:
            name = "intervention"
        return self._condition("intervention", name, expect, compare_to, series, level, correction, overrides)

    def control(
        self,
        name: str | None = None,
        *,
        expect: Mapping[str, str] | None = None,
        compare_to: Sequence[str] = (),
        series: str | None = None,
        level: float | None = None,
        correction: Correction | None = None,
        **overrides: Any,
    ) -> Run:
        """Start a condition the claim predicts should not have the intervention's effect.

        A control usually expects `"no_effect"`, such as ablating a random
        direction instead of the one under test. Takes the same arguments as
        [`intervention`][mechlens.Experiment.intervention], except that `name` is
        required outside a sweep.

        Returns:
            An open run, usable as a context manager.
        """
        if name is None and series is None:
            raise ValueError("control() needs a name, such as 'random-direction'")
        return self._condition("control", name, expect, compare_to, series, level, correction, overrides)

    @property
    def url(self) -> str | None:
        """The experiment page, once this process has uploaded a condition; otherwise `None`.

        Also `None` with a custom client that has no `base_url`.
        """
        for run in self.runs.values():
            base_url = getattr(run.client, "base_url", None)
            if run._receipt is not None and base_url:
                return f"{base_url}/app/experiments/{quote(self.project, safe='')}/{quote(self.id, safe='')}"
        return None

    def _condition(
        self,
        kind: str,
        name: str | None,
        expect: Mapping[str, str] | None,
        compare_to: Sequence[str],
        series: str | None,
        level: float | None,
        correction: Correction | None,
        overrides: dict[str, Any],
    ) -> Run:
        if (series is None) != (level is None):
            raise ValueError("series and level go together: pass both or neither")
        condition: dict[str, Any] = {"kind": kind}
        if series is not None:
            if not isinstance(series, str) or not series.strip():
                raise ValueError("series must be a non-empty string")
            if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level):
                raise ValueError("level must be a finite number")
            condition["series"] = series.strip()
            condition["level"] = float(level)
            if name is None:
                name = f"{condition['series']}@{_level_label(level)}"
        if expect is not None:
            if not isinstance(expect, Mapping) or not all(isinstance(metric, str) and metric for metric in expect):
                raise ValueError("expect must map metric names to an expected change")
            for metric, change in expect.items():
                if change not in EXPECTATIONS:
                    raise ValueError(f"expect[{metric!r}] must be one of {', '.join(map(repr, EXPECTATIONS))}")
            condition["expect"] = dict(expect)
        if isinstance(compare_to, str) or any(not isinstance(other, str) or not other.strip() for other in compare_to):
            raise ValueError("compare_to must be a list of condition names")
        others = list(dict.fromkeys(other.strip() for other in compare_to))
        if name is not None and name.strip() in others:
            raise ValueError("a condition cannot be compared with itself")
        if self._reference is not None and self._reference in others:
            raise ValueError(f"{self._reference!r} is the reference, which every condition is compared with already")
        condition["compare_to"] = others
        return self._start(name, condition, correction, overrides)

    def _start(self, name: str | None, condition: dict[str, Any], correction: Correction | None, overrides: dict[str, Any]) -> Run:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("condition name must be a non-empty string")
        name = name.strip()
        if name in self.runs:
            raise ValueError(f"condition {name!r} was already recorded by this experiment")
        if "project" in overrides:
            raise ValueError("project is shared by the experiment's runs; pass it to mechlens.experiment()")
        if not self._announced:
            print(f"mechlens: recording experiment '{self.id}' to project '{self.project}'", file=sys.stderr)
            self._announced = True
        if correction is not None and not isinstance(correction, Correction):
            raise TypeError("correction must be a mechlens.Correction")
        correction_json = correction.to_json() if correction is not None else None
        run = start_run(**{**self.shared, **overrides, "name": name})
        if correction_json is not None and correction_json["supersedes"] == str(run.data["id"]):
            raise ValueError("a run cannot supersede itself")
        run.data["schema_version"] = 4 if correction_json is not None else 3
        run.data["experiment"] = {"id": self.id, **self.declaration, "condition": {"name": name, **condition}}
        if correction_json is not None:
            run.data["correction"] = correction_json
        self.runs[name] = run
        return run


def experiment(
    *,
    question: str,
    model: Mapping[str, Any],
    id: str | None = None,
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
    """Declare an experiment once, then record its reference and other conditions.

    Everything Cloud needs to draft the finding lives here: the question, the
    claim, the deviations from any paper you reproduce, and the paper's
    reported values. The shared arguments apply to every condition, so the
    conditions are comparable by construction. No network call is made until
    a run finishes.

    Args:
        question: The research question the experiment helps answer.
        model: Shared by every condition. Must include `id`; include `revision`.
        id: Identifies the experiment within its project, so conditions recorded
            in separate processes join it: lowercase letters, digits, `.`, `_`
            and `-`. Defaults to an ID derived from the project, question and
            claim, so running the same declaration again joins the same
            experiment and editing the claim starts a new one.
        claim: The specific, checkable claim under test.
        reproduces: The paper this experiment reproduces, with its reported values.
        deviations: Every way this experiment knowingly differs from the paper
            or the intended protocol. Each becomes a candidate limitation in Cloud.
        project: Groups the experiment's runs. Defaults to `reproduce-<arxiv-id>`
            when `reproduces` is set, otherwise a slug of `question`.
        config: Shared settings, such as `seed`. Defaults to `{}`.
        dataset: Shared dataset, ideally with `id`, `revision` and `split`.
        sae: Shared SAE details, if any.
        generation: Shared decoding settings.
        metric_definitions: Shared metric definitions. Give a metric an
            `example_field` naming the per-example field it averages, such as
            `{"refusal_rate": {"description": "...", "example_field": "refused"}}`,
            and Cloud shows its differences with confidence intervals.
        code_commit: Overrides the automatically detected commit.
        api_key: Overrides `MECHLENS_API_KEY`.
        base_url: Overrides `MECHLENS_API_URL`.
        local_dir: Overrides `MECHLENS_DIR`.
        client: A preconfigured [`CloudClient`][mechlens.CloudClient], mainly for tests.

    Returns:
        An experiment. Record the reference with `with exp.reference() as run:`,
        each other condition with `exp.intervention(...)` or `exp.control(...)`,
        then open `exp.url`.

    Raises:
        ValueError: The question or ID is invalid, a deviation is blank, a metric's
            `example_field` is not a field name, or the paper's reported values are
            malformed.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if isinstance(deviations, str) or any(not isinstance(d, str) or not d.strip() for d in deviations):
        raise ValueError("deviations must be a list of non-empty strings")
    if reproduces is not None and not isinstance(reproduces, Paper):
        raise TypeError("reproduces must be a mechlens.Paper")
    if id is not None and (not isinstance(id, str) or not _ID.match(id)):
        raise ValueError("id must be 1-100 lowercase letters, digits, '.', '_' or '-', starting with a letter or digit")
    for metric, definition in (metric_definitions or {}).items():
        example_field = definition.get("example_field") if isinstance(definition, Mapping) else None
        if example_field is not None and (not isinstance(example_field, str) or not example_field):
            raise ValueError(f"metric_definitions[{metric!r}]['example_field'] must name a per-example field")

    claim = claim.strip() if claim and claim.strip() else None
    declaration = {
        "claim": claim,
        "deviations": [d.strip() for d in deviations],
        "reproduces": reproduces.to_json() if reproduces else None,
    }
    _json_copy(declaration, label="experiment declaration")
    default_project = f"reproduce-{_slug(reproduces.arxiv)}" if reproduces else _slug(question)
    project = (project or default_project).strip()
    shared = {
        "project": project,
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
    return Experiment(id=id or _derived_id(project, question.strip(), claim), declaration=declaration, shared=shared)
