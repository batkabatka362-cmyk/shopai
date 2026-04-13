"""Tax Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the tax engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class AddressInfo(TypedDict, total=False):
    """Address for origin or destination."""
    city: str
    province: str
    zip: str
    country_code: str


class TransactionItem(TypedDict, total=False):
    """Single line item in a transaction."""
    id: str
    product_id: str
    title: str
    quantity: int
    unit_price: float
    product_category: str


class CustomerInfo(TypedDict, total=False):
    """Customer details relevant to tax."""
    id: str
    tax_exempt: bool
    exemption_certificate: str | None
    exemption_type: str | None


class TransactionInfo(TypedDict, total=False):
    """Transaction details."""
    id: str
    order_id: str
    date: str
    currency: str
    line_items: list[TransactionItem]


class TaxInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    transaction: TransactionInfo
    origin_address: AddressInfo
    destination_address: AddressInfo
    customer: CustomerInfo
    tax_type: str
    tax_included: bool


class TaxInput(TypedDict, total=False):
    """Full engine input payload."""
    status: str
    data: TaxInputData
    meta: dict[str, Any]
    error: str | None


# ---------------------------------------------------------------------------
# Intermediate types — jurisdiction resolution
# ---------------------------------------------------------------------------

class JurisdictionInfo(TypedDict, total=False):
    """Single jurisdiction entry."""
    name: str
    type: str
    code: str


class JurisdictionResult(TypedDict):
    """Result from jurisdiction_resolver."""
    status: str
    country: str
    tax_type: str
    jurisdictions: list[JurisdictionInfo]
    is_nexus: bool


# ---------------------------------------------------------------------------
# Intermediate types — rate lookup
# ---------------------------------------------------------------------------

class TaxRate(TypedDict, total=False):
    """Single tax rate entry."""
    jurisdiction: str
    type: str
    rate: float
    category_adjustments: dict[str, float]


class RateLookupResult(TypedDict):
    """Result from rate_lookup."""
    status: str
    rates: list[TaxRate]


# ---------------------------------------------------------------------------
# Intermediate types — tax calculation
# ---------------------------------------------------------------------------

class JurisdictionTaxDetail(TypedDict):
    """Tax detail per jurisdiction on a line item."""
    name: str
    rate: float
    amount: float


class TaxLineItem(TypedDict):
    """Computed tax for a single line item."""
    line_item_id: str
    taxable_amount: float
    tax_amount: float
    jurisdictions: list[JurisdictionTaxDetail]


class TaxCalculationResult(TypedDict):
    """Result from tax_calculator."""
    status: str
    tax_lines: list[TaxLineItem]
    total_tax: float


# ---------------------------------------------------------------------------
# Intermediate types — exemption checking
# ---------------------------------------------------------------------------

class ExemptionResult(TypedDict, total=False):
    """Single exemption check result."""
    line_item_id: str
    exempt: bool
    reason: str


class ExemptionCheckResult(TypedDict):
    """Result from exemption_checker."""
    status: str
    exemptions: list[ExemptionResult]
    fully_exempt: bool


# ---------------------------------------------------------------------------
# Intermediate types — tax report
# ---------------------------------------------------------------------------

class JurisdictionBreakdown(TypedDict):
    """Tax breakdown for a single jurisdiction."""
    name: str
    taxable: float
    collected: float


class TaxReport(TypedDict, total=False):
    """Tax report details."""
    filing_jurisdiction: str
    period: str
    total_taxable: float
    total_tax: float
    jurisdiction_breakdown: list[JurisdictionBreakdown]


class TaxReportResult(TypedDict):
    """Result from tax_reporter."""
    status: str
    report: TaxReport


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class TaxOutputData(TypedDict, total=False):
    """The 'data' block of engine output."""
    transaction_id: str
    currency: str
    tax_type: str
    tax_included: bool
    tax_lines: list[TaxLineItem]
    total_tax: float
    total_taxable: float
    exemptions: list[ExemptionResult]
    report: TaxReport


class TaxMeta(TypedDict, total=False):
    """The 'meta' block of engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class TaxOutput(TypedDict, total=False):
    """Final output of the tax engine."""
    status: str
    data: TaxOutputData | None
    meta: TaxMeta
    error: str | None
