from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class DdsParser(SupplierInvoiceParser):
    supplier_code = "2784"
    display_name = "DDS"

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
        rows: list[dict[str, object]] = []
        for items in self._group_words_by_line(page.get_text("words")):
            row = self._row_from_items(items, page_index)
            if row:
                rows.append(row)
        return rows

    def _group_words_by_line(self, words: list[tuple]) -> list[list[tuple]]:
        useful_words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in words
            if 15 <= x0 <= 585 and 245 <= y0 <= 790
        ]
        useful_words.sort(key=lambda item: (round(item[1], 1), item[0]))

        lines: list[list[tuple]] = []
        for word in useful_words:
            if not lines or abs(lines[-1][0][1] - word[1]) > 4:
                lines.append([word])
            else:
                lines[-1].append(word)
        return lines

    def _row_from_items(self, items: list[tuple], page_index: int) -> dict[str, object]:
        reference = self._reference_from_items(items)
        if reference is None:
            return {}

        quantity = self._number_in_band(items, 70, 104)
        unit = self._text_in_band(items, 104, 122)
        description = " ".join(item[4] for item in items if 125 <= item[0] < 430).strip()
        vat_code = self._text_in_band(items, 435, 458)
        unit_price = self._number_in_band(items, 485, 520)
        amount = self._number_in_band(items, 545, 582)

        if unit_price is None:
            return {}

        return {
            "supplier_article_code": reference,
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "adjusted_unit_price": unit_price,
            "currency": "EUR",
            "remise_temp": 0,
            "remise_detail": "",
            "supplier_unit_ratio_override": self._unit_ratio_override(quantity, unit_price, amount),
            "line_amount": amount,
            "unit": unit,
            "vat_code": vat_code,
            "page": page_index,
        }

    def _reference_from_items(self, items: list[tuple]) -> str | None:
        if not items:
            return None
        first = items[0][4].strip()
        if 15 <= items[0][0] <= 55 and re.fullmatch(r"\d{6}", first):
            return first
        return None

    def _unit_ratio_override(
        self,
        quantity: float | None,
        unit_price: float | None,
        amount: float | None,
    ) -> float | None:
        if quantity is None or unit_price is None or amount is None:
            return None
        if abs(quantity * unit_price - amount) < 0.03:
            return 1.0
        return None

    def _number_in_band(self, items: list[tuple], x_min: float, x_max: float) -> float | None:
        values = [
            parse_decimal(item[4])
            for item in items
            if x_min <= item[0] <= x_max and parse_decimal(item[4]) is not None
        ]
        return values[0] if values else None

    def _text_in_band(self, items: list[tuple], x_min: float, x_max: float) -> str | None:
        values = [item[4].strip() for item in items if x_min <= item[0] <= x_max and item[4].strip()]
        return " ".join(values) or None

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"\bFC\d+\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"Date Facture\s*\n\s*(\d{2}/\d{2}/\d{4})", text)
        if match is None:
            match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
            date_text = match.group(0) if match else None
        else:
            date_text = match.group(1)
        if not date_text:
            return None
        try:
            return datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return date_text
