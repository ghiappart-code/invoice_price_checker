from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class EcodisParser(SupplierInvoiceParser):
    supplier_code = "227"
    display_name = "ECODIS"

    def parse(self, file: BinaryIO) -> ParsedInvoice:
        import fitz

        file.seek(0)
        data = file.read()
        records: list[dict[str, object]] = []
        metadata: dict[str, object] = {
            "supplier_code": self.supplier_code,
            "parser": self.__class__.__name__,
        }

        with fitz.open(stream=data, filetype="pdf") as doc:
            full_text = "\n".join(page.get_text() for page in doc)
            metadata["invoice_number"] = self._find_invoice_number(full_text)
            metadata["invoice_date"] = self._find_invoice_date(full_text)
            for page_index, page in enumerate(doc, start=1):
                records.extend(self._parse_page(page, page_index))

        lines = pd.DataFrame(records)
        metadata["line_count"] = len(lines)
        return ParsedInvoice(
            supplier_code=self.supplier_code,
            invoice_number=metadata["invoice_number"],
            invoice_date=None,
            lines=lines,
            metadata=metadata,
        )

    def _parse_page(self, page: object, page_index: int) -> list[dict[str, object]]:
        words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in page.get_text("words")
        ]
        starts: list[tuple[float, str]] = []
        for x0, y0, _x1, _y1, text in words:
            if not self._is_product_start(x0, y0, text, page_index):
                continue
            starts.append((y0, text.strip()))

        starts.sort(key=lambda item: item[0])
        rows: list[dict[str, object]] = []
        for index, (start_y, reference) in enumerate(starts):
            next_y = starts[index + 1][0] if index + 1 < len(starts) else self._page_product_bottom(page_index)
            items = [
                word
                for word in words
                if start_y - 2 <= word[1] < next_y - 2
            ]
            row = self._row_from_items(reference, items, page_index)
            if row:
                rows.append(row)
        return rows

    def _is_product_start(self, x0: float, y0: float, text: str, page_index: int) -> bool:
        if not 50 <= x0 <= 105:
            return False
        if y0 < self._page_product_top(page_index) or y0 > self._page_product_bottom(page_index):
            return False
        return bool(re.fullmatch(r"[A-Z]{1,4}\d+[A-Z0-9]*", text.strip()))

    def _page_product_top(self, page_index: int) -> float:
        return 260 if page_index == 1 else 20

    def _page_product_bottom(self, page_index: int) -> float:
        return 790 if page_index == 1 else 650

    def _row_from_items(self, reference: str, items: list[tuple], page_index: int) -> dict[str, object]:
        quantity = self._number_in_band(items, 155, 170)
        colis = self._number_in_band(items, 125, 155)
        gross_price = self._number_in_band(items, 360, 392)
        unit_price = self._number_in_band(items, 448, 490)
        amount = self._number_in_band(items, 510, 542)
        vat_rate = self._number_in_band(items, 542, 568)
        description = self._description_from_items(items)

        if unit_price is None:
            return {}

        return {
            "supplier_article_code": reference,
            "description": description,
            "quantity": quantity,
            "colis": colis,
            "unit_price": unit_price,
            "adjusted_unit_price": unit_price,
            "currency": "EUR",
            "remise_temp": 0,
            "remise_detail": "",
            "gross_unit_price": gross_price,
            "line_amount": amount,
            "vat_code": vat_rate,
            "page": page_index,
        }

    def _description_from_items(self, items: list[tuple]) -> str:
        values: list[str] = []
        stop_words = {
            "Remise",
            "Successif",
            "Certifié",
            "Certifie",
            "Certification",
            "Nos",
            "Base(s)",
            "Taux",
            "Montant",
            "Total",
            "Net",
            "Informations",
            "Nom",
        }
        for x0, _y0, _x1, _y1, text in sorted(items, key=lambda item: (item[1], item[0])):
            if not 178 <= x0 < 350:
                continue
            cleaned = text.strip()
            if cleaned in stop_words:
                break
            if cleaned in {"EAN", ":"} or re.fullmatch(r"\d{13}", cleaned):
                continue
            values.append(cleaned)
        return " ".join(values).strip()

    def _number_in_band(self, items: list[tuple], x_min: float, x_max: float) -> float | None:
        values = [
            parse_decimal(item[4])
            for item in items
            if x_min <= item[0] <= x_max and parse_decimal(item[4]) is not None
        ]
        return values[0] if values else None

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"FACTURE\s+(\d+)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"\b\d{6}\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return match.group(0)
