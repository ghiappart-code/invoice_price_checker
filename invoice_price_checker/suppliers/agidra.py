from __future__ import annotations

import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class AgidraParser(SupplierInvoiceParser):
    supplier_code = "329"
    display_name = "AGIDRA"

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
        lines = self._group_words_by_line(page.get_text("words"))
        starts = []
        for index, items in enumerate(lines):
            reference = self._reference_from_items(items)
            if reference:
                starts.append((index, reference))

        rows: list[dict[str, object]] = []
        for position, (line_index, reference) in enumerate(starts):
            next_line_index = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            block = [word for row in lines[line_index:next_line_index] for word in row]
            row = self._row_from_block(reference, block, page_index)
            if row:
                rows.append(row)
        return rows

    def _group_words_by_line(self, words: list[tuple]) -> list[list[tuple]]:
        useful_words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in words
            if 15 <= x0 <= 560 and 280 <= y0 <= 735
        ]
        useful_words.sort(key=lambda item: (round(item[1], 1), item[0]))

        lines: list[list[tuple]] = []
        for word in useful_words:
            if not lines or abs(lines[-1][0][1] - word[1]) > 4:
                lines.append([word])
            else:
                lines[-1].append(word)
        return lines

    def _row_from_block(self, reference: str, block: list[tuple], page_index: int) -> dict[str, object]:
        start_y = min(item[1] for item in block if item[4].strip() == reference)
        first_line = [item for item in block if abs(item[1] - start_y) <= 4]

        description = " ".join(
            item[4]
            for item in block
            if 150 <= item[0] < 325 and not self._is_footer_word(item[4])
        ).strip()
        conditionnement = " ".join(item[4] for item in block if 40 <= item[0] < 108).strip()
        brand = " ".join(item[4] for item in block if 260 <= item[0] < 322).strip()
        bio = self._text_in_band(first_line, 320, 345)
        colis = self._number_in_band(first_line, 20, 44)
        quantity = self._number_in_band(first_line, 360, 390)
        gross_price = self._number_in_band(first_line, 392, 425)
        discount = self._number_in_band(first_line, 426, 462)
        unit_price = self._number_in_band(first_line, 468, 505)
        amount = self._number_in_band(first_line, 515, 542)
        vat_code = self._text_in_band(first_line, 540, 556)

        if unit_price is None:
            return {}

        return {
            "supplier_article_code": reference,
            "description": description,
            "colis": colis,
            "quantity": quantity,
            "unit_price": unit_price,
            "adjusted_unit_price": unit_price,
            "currency": "EUR",
            "remise_temp": 0,
            "remise_detail": f"Remise={discount:g}%" if discount else "",
            "supplier_unit_ratio_override": self._unit_ratio_override(colis, quantity, unit_price, amount, description, conditionnement),
            "gross_unit_price": gross_price,
            "line_amount": amount,
            "conditionnement": conditionnement,
            "brand": brand,
            "bio": bio,
            "vat_code": vat_code,
            "page": page_index,
        }

    def _reference_from_items(self, items: list[tuple]) -> str | None:
        references = [
            item[4].strip()
            for item in items
            if 108 <= item[0] <= 145 and re.fullmatch(r"\d{5,8}", item[4].strip())
        ]
        return references[0] if references else None

    def _unit_ratio_override(
        self,
        colis: float | None,
        quantity: float | None,
        unit_price: float | None,
        amount: float | None,
        description: str,
        conditionnement: str,
    ) -> float | None:
        if quantity is None or unit_price is None or amount is None:
            return None
        if abs(quantity * unit_price - amount) >= 0.03:
            return None

        package_kg = self._package_kg(description, conditionnement)
        if package_kg is None or package_kg == 1:
            return 1.0

        colis_count = colis or 1.0
        # If invoice quantity is the total weight, the unit price is already per kg.
        if abs(quantity - colis_count * package_kg) < 0.03:
            return 1.0

        # If invoice quantity is the number of bags/inner units, the unit price is per package.
        return 1.0 / package_kg

    def _package_kg(self, description: str, conditionnement: str) -> float | None:
        text = f"{description} {conditionnement}".upper().replace(",", ".")
        matches = re.findall(r"(\d+(?:\.\d+)?)\s*KG", text)
        if not matches:
            return None
        try:
            return float(matches[-1])
        except ValueError:
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

    def _is_footer_word(self, value: str) -> bool:
        return value in {"La", "distribution", "des", "produits", "bio", "et", "en", "conversion", "est", "certifiée"}

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"\bFCAG\d+-\d+\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return match.group(0)
