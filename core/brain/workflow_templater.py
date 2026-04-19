"""Workflow templater — reusable DAG patterns.

workflow_dag (v17-D7) lets anyone wire tasks into a graph. But the
same shapes recur constantly: daily kill sweeps, weekly digests,
product launches, anomaly triage. Every engineer who needs one
assembles the DAG from scratch, slightly differently each time.

workflow_templater turns those patterns into named, parameterised
builders:

    reg = default_registry()
    dag = reg.instantiate(
        "daily_kill_sweep",
        fetch_metrics=my_metrics_fn,
        decide_kill=my_kill_fn,
        execute_kill=my_execute_fn,
        notify=my_notify_fn,
    )
    report = dag.execute()

Built-in templates:
  • daily_kill_sweep     — metrics → decide → execute ∥ notify
  • weekly_digest        — collect ∥ → format → send
  • new_product_launch   — ingest → enrich → publish → ads
  • anomaly_monitor      — scan → triage → alert (conditional)
  • retention_cycle      — segment → predict_churn → act

Callers can register their own templates too. All builders return a
fresh WorkflowDAG instance — templates are stateless.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.system.workflow_dag import WorkflowDAG


TaskFn = Callable[[dict[str, Any], dict[str, Any]], Any]
BuilderFn = Callable[..., WorkflowDAG]


@dataclass
class Template:
    name: str
    builder: BuilderFn
    required_params: tuple[str, ...] = ()
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required_params": list(self.required_params),
            "description": self.description,
        }


class TemplateRegistry:
    """Named workflow templates → configured WorkflowDAG instances."""

    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(
        self,
        name: str,
        builder: BuilderFn,
        required_params: tuple[str, ...] = (),
        description: str = "",
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("template name required")
        if name in self._templates:
            raise ValueError(f"template {name!r} already registered")
        self._templates[name] = Template(
            name=name, builder=builder,
            required_params=tuple(required_params),
            description=description,
        )

    def unregister(self, name: str) -> bool:
        return self._templates.pop(name, None) is not None

    def list_templates(self) -> list[Template]:
        return sorted(self._templates.values(), key=lambda t: t.name)

    def get(self, name: str) -> Template | None:
        return self._templates.get(name)

    def instantiate(self, name: str, **params: Any) -> WorkflowDAG:
        tpl = self._templates.get(name)
        if tpl is None:
            raise KeyError(f"unknown template {name!r}")
        missing = [p for p in tpl.required_params if p not in params]
        if missing:
            raise ValueError(
                f"template {name!r} missing params: {missing}",
            )
        return tpl.builder(**params)


# ── Built-in templates ─────────────────────────────────────

def _build_daily_kill_sweep(
    fetch_metrics: TaskFn,
    decide_kill: TaskFn,
    execute_kill: TaskFn,
    notify: TaskFn,
    retries: int = 2,
) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add("fetch_metrics", fetch_metrics, retries=retries)
    dag.add("decide_kill", decide_kill, deps=("fetch_metrics",))
    dag.add(
        "execute_kill", execute_kill,
        deps=("decide_kill",), retries=retries,
        on_fail="abort",  # must not leave money bleeding
    )
    dag.add(
        "notify", notify,
        deps=("execute_kill",), optional=True,
    )
    return dag


def _build_weekly_digest(
    collect_kpis: TaskFn,
    collect_events: TaskFn,
    format_report: TaskFn,
    send: TaskFn,
) -> WorkflowDAG:
    dag = WorkflowDAG()
    # Two independent collectors run in parallel waves
    dag.add("collect_kpis", collect_kpis, retries=1)
    dag.add("collect_events", collect_events, retries=1)
    dag.add(
        "format_report", format_report,
        deps=("collect_kpis", "collect_events"),
    )
    dag.add("send", send, deps=("format_report",), retries=2)
    return dag


def _build_new_product_launch(
    ingest: TaskFn,
    enrich: TaskFn,
    publish: TaskFn,
    ads_launch: TaskFn,
    notify: TaskFn | None = None,
) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add("ingest", ingest, retries=2)
    dag.add("enrich", enrich, deps=("ingest",), retries=1)
    dag.add(
        "publish", publish,
        deps=("enrich",), retries=2, on_fail="abort",
    )
    dag.add(
        "ads_launch", ads_launch,
        deps=("publish",), retries=2,
    )
    if notify is not None:
        dag.add(
            "notify", notify,
            deps=("ads_launch",), optional=True,
        )
    return dag


def _build_anomaly_monitor(
    scan: TaskFn,
    triage: TaskFn,
    alert: TaskFn,
) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add("scan", scan, retries=2)
    dag.add("triage", triage, deps=("scan",))
    dag.add("alert", alert, deps=("triage",), optional=True, retries=1)
    return dag


def _build_retention_cycle(
    segment: TaskFn,
    predict_churn: TaskFn,
    act: TaskFn,
    measure: TaskFn | None = None,
) -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add("segment", segment, retries=1)
    dag.add("predict_churn", predict_churn, deps=("segment",))
    dag.add("act", act, deps=("predict_churn",), retries=2)
    if measure is not None:
        dag.add("measure", measure, deps=("act",), optional=True)
    return dag


def default_registry() -> TemplateRegistry:
    """Fresh registry preloaded with the standard ShopAI templates."""
    reg = TemplateRegistry()
    reg.register(
        "daily_kill_sweep", _build_daily_kill_sweep,
        required_params=(
            "fetch_metrics", "decide_kill",
            "execute_kill", "notify",
        ),
        description=(
            "Pull ad metrics → apply kill rules → execute kills → "
            "notify owner. Kill step aborts on failure to stop bleed."
        ),
    )
    reg.register(
        "weekly_digest", _build_weekly_digest,
        required_params=(
            "collect_kpis", "collect_events",
            "format_report", "send",
        ),
        description=(
            "Parallel collectors → combined report → send. "
            "Collectors run independently before format."
        ),
    )
    reg.register(
        "new_product_launch", _build_new_product_launch,
        required_params=(
            "ingest", "enrich", "publish", "ads_launch",
        ),
        description=(
            "Ingest → enrich → publish → ads. Publish aborts on "
            "failure so ads never launch for a missing product."
        ),
    )
    reg.register(
        "anomaly_monitor", _build_anomaly_monitor,
        required_params=("scan", "triage", "alert"),
        description=(
            "Scan signals → triage severity → alert if needed. "
            "Alert is optional (failing to alert does not abort)."
        ),
    )
    reg.register(
        "retention_cycle", _build_retention_cycle,
        required_params=("segment", "predict_churn", "act"),
        description=(
            "Segment customers → predict churn → act "
            "(email, discount, re-engage). Measure is optional."
        ),
    )
    return reg


# ── Global singleton ───────────────────────────────────────

_GLOBAL: TemplateRegistry | None = None


def registry() -> TemplateRegistry:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = default_registry()
    return _GLOBAL


def reset_registry() -> None:
    """Drop the global registry. Next ``registry()`` call rebuilds it."""
    global _GLOBAL
    _GLOBAL = None
