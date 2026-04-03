"""Cash Flow Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the cash flow engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CashInflow(TypedDict, total=False):
    """Single cash inflow record."""
    id: str
    source: str
    amount: float
    date: str
    category: str
    recurring: bool


class CashOutflow(TypedDict, total=False):
    """Single cash outflow record."""
    id: str
    destination: str
    amount: float
    date: str
    category: str
    recurring: bool


class Receivable(TypedDict, total=False):
    """Single accounts receivable record."""
    id: str
    customer: str
    amount: float
    due_date: str
    issued_date: str
    status: str


class Payable(TypedDict, total=False):
    """Single accounts payable record."""
    id: str
    vendor: str
    amount: float
    due_date: str
    issued_date: str
    status: str


class CashFlowInput(TypedDict, total=False):
    """The 'data' block of engine input."""
    current_balance: float
    inflows: list[CashInflow]
    outflows: list[CashOutflow]
    receivables: list[Receivable]
    payables: list[Payable]
    monthly_fixed_costs: float
    avg_monthly_revenue: float
    period: dict[str, str]


# ---------------------------------------------------------------------------
# Intermediate types — cash position
# ---------------------------------------------------------------------------

class CashPosition(TypedDict):
    """Cash position tracking result."""
    current_balance: float
    period_inflows: float
    period_outflows: float
    net_change: float
    projected_end_balance: float


# ---------------------------------------------------------------------------
# Intermediate types — runway
# ---------------------------------------------------------------------------

class RunwayCalc(TypedDict):
    """Runway calculation result."""
    monthly_burn_rate: float
    net_monthly_burn: float
    months_of_runway: float
    runway_risk: str
    zero_cash_date: str | None


# ---------------------------------------------------------------------------
# Intermediate types — forecast
# ---------------------------------------------------------------------------

class ForecastPeriod(TypedDict):
    """Forecast for a single horizon period."""
    projected_balance: float
    confidence: float


class CashForecast(TypedDict):
    """Cash flow forecast result."""
    day_30: ForecastPeriod
    day_60: ForecastPeriod
    day_90: ForecastPeriod
    trend: str


# ---------------------------------------------------------------------------
# Intermediate types — alerts
# ---------------------------------------------------------------------------

class CashAlert(TypedDict):
    """Single cash flow alert."""
    alert_type: str
    severity: str
    message: str
    recommended_action: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class CashFlowData(TypedDict):
    """The 'data' block of the engine output."""
    cash_position: CashPosition
    payment_terms: dict[str, Any]
    runway: RunwayCalc
    forecast: CashForecast
    alerts: list[CashAlert]


class CashFlowMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class CashFlowOutput(TypedDict):
    """Final output of the cash flow engine."""
    status: str
    data: CashFlowData | None
    meta: CashFlowMeta
    error: str | None
