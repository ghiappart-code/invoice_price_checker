from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


EKIBIO_ENERGY_TRANSPORT_SURCHARGE = 0.006


class EkibioParser(SupplierInvoiceParser):
    supplier_code = "358"
    display_name = "EKIBIO"

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
            energy_transport_surcharge = self._energy_transport_surcharge(full_text)
            metadata["taxe_gazole"] = energy_transport_surcharge

            for page_index, page in enumerate(doc, start=1):
                records.extend(self._parse_page(page, page_index, energy_transport_surcharge))

        lines = pd.DataFrame(records)
        metadata["line_count"] = len(lines)
        return ParsedInvoice(
            supplier_code=self.supplier_code,
            invoice_number=metadata["invoice_number"],
            invoice_date=None,
            lines=lines,
            metadata=metadata,
        )

    def _parse_page(
        self,
        page: object,
        page_index: int,
        energy_transport_surcharge: float,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        line_words = self._group_words_by_line(page.get_text("words"))
        for items in line_words:
            row = self._row_from_items(items, page_index, energy_transport_surcharge)
            if row:
                rows.append(row)
        return rows

    def _group_words_by_line(self, words: list[tuple]) -> list[list[tuple]]:
        useful_words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in words
            if 20 <= x0 <= 820 and 80 <= y0 <= 560
        ]
        useful_words.sort(key=lambda item: (round(item[1], 1), item[0]))

        lines: list[list[tuple]] = []
        for word in useful_words:
            if not lines or abs(lines[-1][0][1] - word[1]) > 3:
                lines.append([word])
            else:
                lines[-1].append(word)
        return lines

    def _row_from_items(
        self,
        items: list[tuple],
        page_index: int,
        energy_transport_surcharge: float,
    ) -> dict[str, object]:
        reference = self._reference_from_items(items)
        if reference is None:
            return {}

        description = " ".join(item[4] for item in items if 55 <= item[0] < 360).strip()
        quantity = self._number_in_band(items, 545, 595)
        gross_price = self._number_in_band(items, 600, 640)
        unit_price = self._number_in_band(items, 705, 745)
        amount = self._number_in_band(items, 760, 805)
        vat_code = self._text_in_band(items, 805, 820)
        remise_detail = " ".join(item[4] for item in items if 638 <= item[0] < 705 and ":" in item[4])
        remise_temp = int(self._has_temporary_discount(remise_detail))

        if unit_price is None:
            return {}

        adjusted_unit_price = unit_price + energy_transport_surcharge
        return {
            "supplier_article_code": reference,
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "adjusted_unit_price": adjusted_unit_price,
            "currency": "EUR",
            "remise_temp": remise_temp,
            "remise_detail": remise_detail,
            "fuel_surcharge_amount": energy_transport_surcharge,
            "supplier_unit_ratio_override": self._unit_ratio_override(quantity, unit_price, amount),
            "gross_unit_price": gross_price,
            "line_amount": amount,
            "vat_code": vat_code,
            "page": page_index,
        }

    def _reference_from_items(self, items: list[tuple]) -> str | None:
        references = [
            item[4].strip()
            for item in items
            if 20 <= item[0] <= 60 and re.fullmatch(r"\d{6}", item[4].strip())
        ]
        return references[0] if references else None

    def _unit_ratio_override(self, quantity: float | None, unit_price: float | None, amount: float | None) -> float | None:
        if quantity is None or unit_price is None or amount is None:
            return None
        expected_amount = quantity * unit_price
        if quantity > 1 and abs(expected_amount - amount) < 0.02:
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

    def _has_temporary_discount(self, remise_detail: str) -> bool:
        # EKIBIO legend: b = ponctuelle, d = promo. These are treated as temporary discounts.
        return bool(re.search(r"\b[bd]:", remise_detail, re.IGNORECASE))

    def _energy_transport_surcharge(self, text: str) -> float:
        if re.search(r"CONTRIBUTION\s+ENERGIE\s+TRANSPORT", text, re.IGNORECASE):
            return EKIBIO_ENERGY_TRANSPORT_SURCHARGE
        return 0.0

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"FACTURE\s+No.*?\n(\d+)", text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
        match = re.search(r"\b0\d{7}\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"du\s+(\d{2}/\d{2}/\d{2})\s+En Euro", text, re.IGNORECASE)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%d/%m/%y").date().isoformat()
        except ValueError:
            return match.group(1)
