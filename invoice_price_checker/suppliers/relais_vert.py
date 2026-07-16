from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class RelaisVertParser(SupplierInvoiceParser):
    supplier_code = "254"
    display_name = "RELAIS VERT"
    PRODUCT_AREA_Y_MIN = 280

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
            fuel_pct = self._find_fuel_surcharge_pct(full_text)
            metadata["taxe_gazole"] = f"{fuel_pct:g}%"

            for page_index, page in enumerate(doc, start=1):
                records.extend(self._parse_page(page, page_index, fuel_pct))

        lines = pd.DataFrame(records)
        metadata["line_count"] = len(lines)
        return ParsedInvoice(
            supplier_code=self.supplier_code,
            invoice_number=metadata["invoice_number"],
            invoice_date=None,
            lines=lines,
            metadata=metadata,
        )

    def _parse_page(self, page: object, page_index: int, fuel_pct: float) -> list[dict[str, object]]:
        words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in page.get_text("words")
            if self.PRODUCT_AREA_Y_MIN <= y0 <= 780
        ]
        words.sort(key=lambda item: (item[1], item[0]))

        starts: list[tuple[float, str]] = []
        for word in words:
            x0, y0, *_ = word
            if not 38 <= x0 <= 80:
                continue
            reference = self._reference_from_words([word])
            if reference is not None:
                starts.append((y0, reference))

        starts.sort(key=lambda item: item[0])
        product_rows: list[dict[str, object]] = []
        for index, (start_y, reference) in enumerate(starts):
            next_y = starts[index + 1][0] if index + 1 < len(starts) else 790
            items = [
                word
                for word in words
                if start_y - 2 <= word[1] < next_y - 2
            ]
            row = self._row_from_items(reference, items, page_index, fuel_pct)
            if row:
                product_rows.append(row)
        return product_rows

    def _row_from_items(
        self,
        reference: str,
        items: list[tuple],
        page_index: int,
        fuel_pct: float,
    ) -> dict[str, object]:
        description = " ".join(item[4] for item in items if 85 <= item[0] <= 255)
        if "GAZOLE" in description.upper():
            return {}
        unit_price = self._number_in_band(items, 480, 512)
        gross_price = self._number_in_band(items, 390, 420)
        q_discount = self._number_in_band(items, 420, 435) or 0.0
        g_discount = self._number_in_band(items, 435, 450) or 0.0
        p_discount = self._number_in_band(items, 450, 463) or 0.0
        e_discount = self._number_in_band(items, 463, 477) or 0.0
        quantity = self._number_in_band(items, 360, 382)
        amount = self._number_in_band(items, 515, 542)

        adjusted_price = unit_price * (1 + fuel_pct / 100) if unit_price is not None else None
        remise_temp = int(bool(q_discount or p_discount or e_discount))
        remise_parts = []
        if q_discount:
            remise_parts.append(f"Q*={q_discount:g}")
        if p_discount:
            remise_parts.append(f"P={p_discount:g}")
        if e_discount:
            remise_parts.append(f"E={e_discount:g}")
        remise_detail = ", ".join(remise_parts)

        return {
            "supplier_article_code": reference,
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "adjusted_unit_price": adjusted_price,
            "currency": "EUR",
            "q_discount": q_discount,
            "g_discount": g_discount,
            "p_discount": p_discount,
            "e_discount": e_discount,
            "fuel_surcharge_pct": fuel_pct,
            "remise_temp": remise_temp,
            "remise_detail": remise_detail,
            "supplier_unit_ratio_override_when_abnormal": self._unit_ratio_override_when_abnormal(quantity, unit_price, amount),
            "gross_unit_price": gross_price,
            "line_amount": amount,
            "page": page_index,
        }

    def _reference_from_words(self, words: list[tuple]) -> str | None:
        candidates = [word[4] for word in words]
        for candidate in candidates:
            cleaned = candidate.strip()
            if cleaned.startswith("BL"):
                continue
            if cleaned.isdigit() and len(cleaned) == 13:
                continue
            if re.fullmatch(r"[A-Z0-9]{4,6}", cleaned):
                return cleaned
        return None

    def _number_in_band(self, items: list[tuple], x_min: float, x_max: float) -> float | None:
        values = [
            parse_decimal(item[4])
            for item in items
            if x_min <= item[0] <= x_max and parse_decimal(item[4]) is not None
        ]
        return values[0] if values else None

    def _unit_ratio_override_when_abnormal(
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

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"\bFC\d+\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return match.group(0)

    def _find_fuel_surcharge_pct(self, text: str) -> float:
        match = re.search(r"GAZOLE\s*:\s*([0-9]+(?:[,.][0-9]+)?)\s*%", text, re.IGNORECASE)
        if not match:
            return 0.0
        return parse_decimal(match.group(1)) or 0.0
