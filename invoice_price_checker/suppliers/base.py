from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO

from invoice_price_checker.models import ParsedInvoice


class SupplierInvoiceParser(ABC):
    supplier_code: str
    display_name: str

    @abstractmethod
    def parse(self, file: BinaryIO) -> ParsedInvoice:
        """Extract normalized invoice lines from a supplier PDF."""
