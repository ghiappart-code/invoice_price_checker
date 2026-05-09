from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class EpiceParser(SupplierInvoiceParser):
    supplier_code = "262"
    display_name = "EPICE"

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
            if 18 <= x0 <= 565 and 235 <= y0 <= 780
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

        description = " ".join(item[4] for item in items if 95 <= item[0] < 390).strip()
        quantity = self._number_in_band(items, 390, 425)
        unit_price = self._number_in_band(items, 435, 482)
        amount = self._number_in_band(items, 492, 538)
        vat_code = self._text_in_band(items, 540, 562)

        if unit_price is None:
            return {}

        is_free = bool(unit_price == 0 or amount == 0 or "offert" in description.casefold())
        return {
            "supplier_article_code": reference,
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "adjusted_unit_price": unit_price,
            "currency": "EUR",
            "remise_temp": int(is_free),
            "remise_detail": "offert" if is_free else "",
            "gross_unit_price": unit_price,
            "line_amount": amount,
            "vat_code": vat_code,
            "page": page_index,
        }

    def _reference_from_items(self, items: list[tuple]) -> str | None:
        first = items[0][4].strip() if items else ""
        if not (18 <= items[0][0] <= 90):
            return None
        if first in {"Page", "Sarl", "RESERVE", "Notre", "RIB", "IBAN", "BIC"}:
            return None
        has_quantity = any(390 <= item[0] <= 425 and parse_decimal(item[4]) is not None for item in items)
        has_unit_price = any(435 <= item[0] <= 482 and parse_decimal(item[4]) is not None for item in items)
        if has_quantity and has_unit_price and re.fullmatch(r"[A-Z0-9][A-Z0-9.]*", first):
            return first
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
        match = re.search(r"\bFW\d+\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"\b\d{2}/\d{2}/\d{2}\b", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%d/%m/%y").date().isoformat()
        except ValueError:
            return match.group(0)
