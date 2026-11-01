from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import parse_decimal


class AgidraParser(SupplierInvoiceParser):
    supplier_code = "329"
    display_name = "AGIDRA"

    DESCRIPTION_START = 145
    FC_DESCRIPTION_END = 260
    FW_DESCRIPTION_END = 281

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
            layout = self._detect_layout(full_text)
            metadata["layout"] = layout
            for page_index, page in enumerate(doc, start=1):
                page_words = page.get_text("words")
                columns = self._columns_from_header(page_words)
                records.extend(self._parse_page(page, page_index, layout, columns))

        lines = pd.DataFrame(records)
        expected_line_count = self._find_expected_line_count(full_text)
        expected_total, expected_total_label = self._find_expected_total(full_text)
        extracted_total = self._sum_line_amounts(lines)
        total_difference = (
            round(extracted_total - expected_total, 2)
            if extracted_total is not None and expected_total is not None
            else None
        )
        validation_errors = self._validate_lines(lines)
        validation_warnings: list[str] = []

        metadata["line_count"] = len(lines)
        metadata["expected_line_count"] = expected_line_count
        metadata["line_count_verified"] = (
            len(lines) == expected_line_count if expected_line_count is not None else None
        )
        metadata["expected_line_total"] = expected_total
        metadata["extracted_line_total"] = extracted_total
        metadata["line_total_difference"] = total_difference
        metadata["line_total_verified"] = (
            abs(total_difference) < 0.03 if total_difference is not None else None
        )
        metadata["line_validation_errors"] = validation_errors
        metadata["lines_validated"] = not validation_errors

        if expected_line_count is not None and len(lines) != expected_line_count:
            validation_warnings.append(
                f"Le PDF annonce {expected_line_count} lignes, mais {len(lines)} ont été extraites."
            )
        if expected_total is not None:
            if extracted_total is None:
                validation_warnings.append(
                    "Le total des montants des lignes n'a pas pu être calculé."
                )
            elif total_difference is not None and abs(total_difference) >= 0.03:
                validation_warnings.append(
                    f"La somme des montants extraits ({extracted_total:.2f} €) ne correspond "
                    f"pas au {expected_total_label} imprimé ({expected_total:.2f} €). "
                    f"Écart : {total_difference:+.2f} €."
                )
        if validation_errors:
            validation_warnings.append(
                "Le contrôle quantité × prix a échoué pour les références : "
                + ", ".join(validation_errors)
            )
        metadata["validation_warnings"] = validation_warnings
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
        layout: str,
        columns: dict[str, float] | None = None,
    ) -> list[dict[str, object]]:
        lines = self._group_words_by_line(page.get_text("words"))
        starts = []
        for index, items in enumerate(lines):
            reference = self._reference_from_items(items)
            unit_price = (
                self._number_near_column(items, columns, "unit_price")
                if columns
                else self._unit_price_from_items(items, layout)
            )
            if reference and unit_price is not None:
                starts.append((index, reference))

        rows: list[dict[str, object]] = []
        for position, (line_index, reference) in enumerate(starts):
            next_line_index = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            block_lines = lines[line_index:next_line_index]
            block = self._product_words(block_lines, layout)
            row = self._row_from_block(reference, block, page_index, layout, columns)
            if row:
                rows.append(row)
        return rows

    def _group_words_by_line(self, words: list[tuple]) -> list[list[tuple]]:
        useful_words = [
            (x0, y0, x1, y1, text)
            for x0, y0, x1, y1, text, *_ in words
            if 15 <= x0 <= 620 and 0 <= y0 <= 810
        ]
        useful_words.sort(key=lambda item: (round(item[1], 1), item[0]))

        lines: list[list[tuple]] = []
        for word in useful_words:
            if not lines or abs(lines[-1][0][1] - word[1]) > 4:
                lines.append([word])
            else:
                lines[-1].append(word)
        return lines

    def _product_words(self, lines: list[list[tuple]], layout: str) -> list[tuple]:
        if not lines:
            return []
        description_end = self._description_end(layout)
        product_lines = [lines[0]]
        for line in lines[1:]:
            if line[0][1] - product_lines[-1][0][1] > 15:
                break
            has_description = any(
                self.DESCRIPTION_START <= item[0] < description_end for item in line
            )
            has_brand = layout == "fc_brand" and any(260 <= item[0] < 322 for item in line)
            if not has_description and not has_brand:
                break
            product_lines.append(line)
        return [word for line in product_lines for word in line]

    def _row_from_block(
        self,
        reference: str,
        block: list[tuple],
        page_index: int,
        layout: str,
        columns: dict[str, float] | None = None,
    ) -> dict[str, object]:
        start_y = min(item[1] for item in block if item[4].strip() == reference)
        first_line = [item for item in block if abs(item[1] - start_y) <= 4]
        description_end = self._description_end(layout)

        description = " ".join(
            item[4]
            for item in block
            if self.DESCRIPTION_START <= item[0] < description_end
        ).strip()
        conditionnement = " ".join(item[4] for item in block if 40 <= item[0] < 108).strip()
        brand = (
            " ".join(item[4] for item in block if 260 <= item[0] < 322).strip()
            if layout == "fc_brand"
            else ""
        )
        origin = self._text_in_band(first_line, 281, 306) if layout == "fw_customs" else None
        customs_reference = self._text_in_band(first_line, 306, 342) if layout == "fw_customs" else None
        bio = (
            self._text_in_band(first_line, 342, 356)
            if layout == "fw_customs"
            else self._text_in_band(first_line, 320, 345)
        )
        colis = self._number_in_band(first_line, 20, 44)
        if columns:
            quantity = self._number_near_column(first_line, columns, "quantity")
            gross_price = self._number_near_column(first_line, columns, "gross_price")
            discount = self._number_near_column(first_line, columns, "discount")
            unit_price = self._number_near_column(first_line, columns, "unit_price")
            amount = self._number_near_column(first_line, columns, "amount")
            vat_code = self._text_near_column(first_line, columns, "vat")
        elif layout == "fw_customs":
            has_new_columns = self._uses_new_fw_customs_bands(first_line)
            quantity = self._number_in_band(first_line, 397, 432) or self._number_in_band(first_line, 360, 390)
            gross_price = self._number_in_band(first_line, 432, 466) or self._number_in_band(first_line, 392, 425)
            discount = (
                self._number_in_band(first_line, 468, 505)
                if has_new_columns
                else self._number_in_band(first_line, 426, 462)
            )
            unit_price = self._unit_price_from_items(first_line, layout)
            amount = self._number_in_band(first_line, 544, 578) or self._number_in_band(first_line, 515, 542)
            vat_code = self._text_in_band(first_line, 580, 604) or self._text_in_band(first_line, 540, 556)
        else:
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
            "origin": origin,
            "customs_reference": customs_reference,
            "vat_code": vat_code,
            "page": page_index,
        }

    def _reference_from_items(self, items: list[tuple]) -> str | None:
        references = [
            item[4].strip()
            for item in items
            if 105 <= item[0] <= 145 and re.fullmatch(r"\d{5,8}", item[4].strip())
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

    def _columns_from_header(self, words: list[tuple]) -> dict[str, float] | None:
        """Read numeric column positions from this page's printed table header."""
        useful = [
            (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]).strip())
            for w in words
            if 15 <= w[0] <= 620 and 0 <= w[1] <= 810 and str(w[4]).strip()
        ]
        lines: list[list[tuple]] = []
        for word in sorted(useful, key=lambda item: (round(item[1], 1), item[0])):
            if not lines or abs(lines[-1][0][1] - word[1]) > 4:
                lines.append([word])
            else:
                lines[-1].append(word)

        for header in lines:
            normalized = [(word, self._normalize_header_word(word[4])) for word in header]
            labels = {text for _word, text in normalized}
            if not any(text.startswith("reference") for text in labels):
                continue
            if not any(text.startswith("designation") for text in labels):
                continue
            if not any(text.startswith("quantite") for text in labels):
                continue

            columns: dict[str, float] = {}

            def center(word: tuple) -> float:
                return (word[0] + word[2]) / 2

            for word, label in normalized:
                if label.startswith("quantite"):
                    columns["quantity"] = center(word)
                elif label in {"total", "totalht"}:
                    columns["amount"] = center(word)
                elif label in {"tva", "vat"}:
                    columns["vat"] = center(word)
                elif label.startswith("remise"):
                    columns["discount"] = center(word)

            unit_headers = [word for word, label in normalized if label in {"pu", "puht"}]
            qualifiers = [
                (word, label)
                for word, label in normalized
                if label in {"net", "ht"}
            ]
            for unit_header in unit_headers:
                nearest_qualifier = min(
                    qualifiers,
                    key=lambda item: abs(center(item[0]) - center(unit_header)),
                    default=None,
                )
                qualifier = (
                    nearest_qualifier[1]
                    if nearest_qualifier is not None
                    and abs(center(nearest_qualifier[0]) - center(unit_header)) <= 36
                    else ""
                )
                if qualifier == "net":
                    columns["unit_price"] = center(unit_header)
                elif qualifier == "ht":
                    columns["gross_price"] = center(unit_header)

            # Older AGIDRA headers may print a single P.U label beside the net
            # price, without repeating “Net”. Use it only when the table has a
            # clear total column and no separate gross/net labels were found.
            if "unit_price" not in columns and len(unit_headers) == 1 and "amount" in columns:
                columns["unit_price"] = center(unit_headers[0])

            if {"quantity", "unit_price", "amount"}.issubset(columns):
                return columns
        return None

    def _normalize_header_word(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.sub(r"[^a-z]", "", normalized)

    def _number_near_column(
        self,
        items: list[tuple],
        columns: dict[str, float],
        column: str,
    ) -> float | None:
        target = columns.get(column)
        if target is None:
            return None
        values = [
            (abs((item[0] + item[2]) / 2 - target), parse_decimal(item[4]))
            for item in items
            if parse_decimal(item[4]) is not None
        ]
        if not values:
            return None
        distance, value = min(values, key=lambda item: item[0])
        return value if distance <= 26 else None

    def _text_near_column(
        self,
        items: list[tuple],
        columns: dict[str, float],
        column: str,
    ) -> str | None:
        target = columns.get(column)
        if target is None:
            return None
        candidates = [
            item for item in items
            if abs((item[0] + item[2]) / 2 - target) <= 26 and item[4].strip()
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: abs((item[0] + item[2]) / 2 - target))[4].strip()

    def _unit_price_from_items(self, items: list[tuple], layout: str) -> float | None:
        if layout == "fw_customs" and self._uses_new_fw_customs_bands(items):
            return self._number_in_band(items, 509, 542)
        return self._number_in_band(items, 468, 505)

    def _uses_new_fw_customs_bands(self, items: list[tuple]) -> bool:
        return (
            self._number_in_band(items, 509, 542) is not None
            and self._number_in_band(items, 544, 578) is not None
        )

    def _text_in_band(self, items: list[tuple], x_min: float, x_max: float) -> str | None:
        values = [item[4].strip() for item in items if x_min <= item[0] <= x_max and item[4].strip()]
        return " ".join(values) or None

    def _detect_layout(self, text: str) -> str:
        if re.search(r"\bOrigine\b", text) and re.search(r"Réf\s+douane", text, re.IGNORECASE):
            return "fw_customs"
        return "fc_brand"

    def _description_end(self, layout: str) -> float:
        return self.FW_DESCRIPTION_END if layout == "fw_customs" else self.FC_DESCRIPTION_END

    def _find_expected_total(self, text: str) -> tuple[float | None, str | None]:
        amount_pattern = r"([0-9][0-9 \t\u00a0\u202f.,]*[,\.][0-9]{2})"
        # AGIDRA's standalone TOTAL is the sum before a possible global rebate.
        # Prefer it to TOTAL HT, which can already include that rebate.
        for label, pattern in (
            ("TOTAL", rf"(?im)^[ \t]*TOTAL[ \t]*\r?\n[ \t]*{amount_pattern}[ \t]*$"),
            (
                "TOTAL H.T.",
                rf"(?im)^[ \t]*TOTAL[ \t]+H[ \t]*\.[ \t]*T[ \t]*\.[ \t]*\r?\n[ \t]*{amount_pattern}[ \t]*$",
            ),
            ("TOTAL HT", rf"(?im)^[ \t]*TOTAL[ \t]+HT[ \t]*\r?\n[ \t]*{amount_pattern}[ \t]*$"),
        ):
            matches = re.findall(pattern, text)
            if matches:
                total = parse_decimal(matches[-1])
                if total is not None:
                    return total, label
        return None, None

    def _sum_line_amounts(self, lines: pd.DataFrame) -> float | None:
        if lines.empty:
            return 0.0
        if "line_amount" not in lines:
            return None
        amounts = pd.to_numeric(lines["line_amount"], errors="coerce")
        if amounts.isna().any():
            return None
        return round(float(amounts.sum()), 2)

    def _find_expected_line_count(self, text: str) -> int | None:
        matches = re.findall(r"Nb\s+Lignes\s*:\s*(\d+)", text, re.IGNORECASE)
        if not matches:
            return None
        return int(matches[-1])

    def _validate_lines(self, lines: pd.DataFrame) -> list[str]:
        errors: list[str] = []
        for _, line in lines.iterrows():
            reference = str(line.get("supplier_article_code") or "?")
            description = str(line.get("description") or "").strip()
            quantity = line.get("quantity")
            unit_price = line.get("unit_price")
            amount = line.get("line_amount")
            if not description or any(pd.isna(value) for value in (quantity, unit_price, amount)):
                errors.append(reference)
                continue
            if abs(float(quantity) * float(unit_price) - float(amount)) >= 0.03:
                errors.append(reference)
        return errors

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(r"\bF[CW]AG\d+-\d+\b", text)
        return match.group(0) if match else None

    def _find_invoice_date(self, text: str) -> str | None:
        match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return match.group(0)
