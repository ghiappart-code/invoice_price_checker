from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class InvoiceLine:
    supplier_article_code: str
    description: str
    unit_price: float
    quantity: float | None = None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedInvoice:
    supplier_code: str
    invoice_number: str | None
    invoice_date: date | None
    lines: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchConfig:
    supplier_code: str
    borne_inf: float = -0.10
    borne_sup: float = 0.05
    abnormal_ratio: float = 0.30
    allow_description_fallback: bool = True
