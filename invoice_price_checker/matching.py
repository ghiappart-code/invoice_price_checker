from __future__ import annotations

import pandas as pd

from invoice_price_checker.models import MatchConfig
from invoice_price_checker.pricing import sale_price
from invoice_price_checker.text import normalize_key


INTERNAL_OUTPUT_COLUMNS = [
    "supplier_article_code",
    "article_code",
    "supplier_code",
    "invoice_description",
    "invoice_unit_price",
    "adjusted_unit_price",
    "comparison_unit_price",
    "current_price",
    "price_difference",
    "price_change_pct",
    "prix_de_vente",
    "price_changed",
    "remise_temp",
    "change_blocked",
    "abnormal_change",
    "block_reason",
    "supplier_unit_ratio",
    "remise_detail",
    "tax_rate",
    "margin_category",
    "currency",
    "matched",
    "match_method",
    "external_id",
    "database_description",
]


OUTPUT_COLUMN_RENAMES = {
    "article_code": "Article_Ref_EAN",
    "external_id": "ID_externe",
    "supplier_code": "ID_Fournisseur",
    "supplier_article_code": "Article_ID_Fournisseur",
    "database_description": "DB_Designation",
    "invoice_description": "Fact_Designation",
    "current_price": "DB_Prix_Net",
    "comparison_unit_price": "Fact_PU_unitaire",
    "price_difference": "Ecart_Prix",
    "price_change_pct": "Ecart_Prix_percent",
    "price_changed": "PU_Modif",
    "change_blocked": "Blocage_Modif",
    "abnormal_change": "Ecart_Prix_Anormal",
    "block_reason": "Raison_du_Blocage",
    "invoice_unit_price": "Fact_PU_Net",
    "adjusted_unit_price": "Fact_PU_Net_GZ",
    "supplier_unit_ratio": "DB_Fournisseur_Unit_Ratio",
    "remise_detail": "Detail_Remise",
    "tax_rate": "TVA",
    "margin_category": "Taux_de_Marque",
    "currency": "Monnaie",
    "matched": "Match_Fact_DB",
    "match_method": "Match_Methode",
}

OUTPUT_COLUMNS = [OUTPUT_COLUMN_RENAMES.get(column, column) for column in INTERNAL_OUTPUT_COLUMNS]




def compare_invoice_to_database(
    products: pd.DataFrame,
    invoice_lines: pd.DataFrame,
    config: MatchConfig,
) -> pd.DataFrame:
    supplier_products = products[
        products["supplier_code"].astype(str).str.casefold() == str(config.supplier_code).casefold()
    ].copy()

    prepared_lines = _prepare_invoice_lines(invoice_lines)
    rows = [
        _match_line(line, supplier_products, config)
        for _, line in prepared_lines.iterrows()
    ]
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    result = _flag_description_matches_for_manual_review(result)
    result = _flag_duplicate_invoice_lines(result)
    result = result[INTERNAL_OUTPUT_COLUMNS].rename(columns=OUTPUT_COLUMN_RENAMES)
    return _round_output_numbers(result)


def _flag_description_matches_for_manual_review(result: pd.DataFrame) -> pd.DataFrame:
    flagged = result.copy()
    description_match_mask = flagged["match_method"] == "description"
    if not description_match_mask.any():
        return flagged

    flagged.loc[description_match_mask, "price_changed"] = False
    flagged.loc[description_match_mask, "abnormal_change"] = False
    flagged.loc[description_match_mask, "change_blocked"] = True
    flagged.loc[description_match_mask, "block_reason"] = "reference differente a verifier"
    return flagged


def _flag_duplicate_invoice_lines(result: pd.DataFrame) -> pd.DataFrame:
    flagged = result.copy()
    duplicate_mask = flagged.duplicated(subset=["supplier_article_code"], keep="first")
    if not duplicate_mask.any():
        return flagged

    flagged.loc[duplicate_mask, "price_changed"] = False
    flagged.loc[duplicate_mask, "abnormal_change"] = True
    flagged.loc[duplicate_mask, "change_blocked"] = True
    flagged.loc[duplicate_mask, "block_reason"] = "ligne_dupliquee_facture"
    return flagged


def _round_output_numbers(result: pd.DataFrame) -> pd.DataFrame:
    rounded = result.copy()
    if "Ecart_Prix" in rounded:
        rounded["Ecart_Prix"] = pd.to_numeric(rounded["Ecart_Prix"], errors="coerce").round(3)
    if "Ecart_Prix_percent" in rounded:
        rounded["Ecart_Prix_percent"] = (
            pd.to_numeric(rounded["Ecart_Prix_percent"], errors="coerce")
            .map(_format_percent)
        )
    return rounded


def _format_percent(value: float) -> str | None:
    if pd.isna(value):
        return None
    return f"{value:.1%}"


def _prepare_invoice_lines(invoice_lines: pd.DataFrame) -> pd.DataFrame:
    lines = invoice_lines.copy()
    required = {"supplier_article_code", "description", "unit_price"}
    missing = required - set(lines.columns)
    if missing:
        raise ValueError(f"Parsed invoice is missing column(s): {', '.join(sorted(missing))}")
    lines["supplier_article_key"] = lines["supplier_article_code"].fillna("").map(normalize_key)
    lines["description_key"] = lines["description"].fillna("").map(normalize_key)
    lines["unit_price"] = pd.to_numeric(lines["unit_price"], errors="coerce")
    if "adjusted_unit_price" not in lines:
        lines["adjusted_unit_price"] = lines["unit_price"]
    lines["adjusted_unit_price"] = pd.to_numeric(lines["adjusted_unit_price"], errors="coerce")
    return lines


def _match_line(
    line: pd.Series,
    supplier_products: pd.DataFrame,
    config: MatchConfig,
) -> dict[str, object]:
    match = supplier_products[
        supplier_products["supplier_article_key"] == line["supplier_article_key"]
    ]
    match_method = "supplier_article_code"

    if match.empty:
        stripped_key = _strip_numeric_leading_zero_key(line.get("supplier_article_code"))
        if stripped_key and stripped_key != line["supplier_article_key"]:
            match = supplier_products[supplier_products["supplier_article_key"] == stripped_key]
            match_method = "supplier_article_code_without_leading_zeroes"

    if match.empty and str(config.supplier_code) == "262":
        match = _match_epice_truncated_reference(line, supplier_products)
        match_method = "epice_supplier_article_code_without_last_two_chars"

    if match.empty and config.allow_description_fallback:
        match = supplier_products[
            supplier_products["description_key"] == line["description_key"]
        ]
        match_method = "description"

    if match.empty:
        return _unmatched_row(line)

    product = match.iloc[0]
    current_price = product["current_price"]
    invoice_price = line["adjusted_unit_price"]
    supplier_unit_ratio = _line_or_product_unit_ratio(line, product)
    supplier_unit_ratio = _conditional_unit_ratio_override(
        line,
        supplier_unit_ratio,
        invoice_price,
        current_price,
        config,
    )
    comparison_price = invoice_price * supplier_unit_ratio
    difference = comparison_price - current_price
    pct = difference / current_price if current_price else None
    q_discount = _numeric_or_zero(line.get("q_discount"))
    p_discount = _numeric_or_zero(line.get("p_discount"))
    e_discount = _numeric_or_zero(line.get("e_discount"))
    remise_temp = int(_numeric_or_zero(line.get("remise_temp")) or bool(q_discount or p_discount or e_discount))
    remise_detail = line.get("remise_detail") or _remise_detail(q_discount, p_discount, e_discount)
    change_blocked = bool(difference < 0 and remise_temp)
    price_changed = bool(
        not change_blocked
        and (difference < config.borne_inf or difference > config.borne_sup)
    )
    abnormal_change = bool(
        pct is not None
        and abs(pct) > config.abnormal_ratio
        and (difference < config.borne_inf or difference > config.borne_sup)
    )
    price_for_sale = sale_price(
        comparison_price,
        product.get("tax_rate"),
        product.get("margin_category"),
    )

    return {
        "external_id": product.get("external_id"),
        "article_code": product["article_code"],
        "supplier_code": product["supplier_code"],
        "supplier_article_code": product["supplier_article_code"],
        "invoice_description": line["description"],
        "database_description": product["description"],
        "current_price": current_price,
        "invoice_unit_price": line["unit_price"],
        "adjusted_unit_price": invoice_price,
        "supplier_unit_ratio": supplier_unit_ratio,
        "comparison_unit_price": comparison_price,
        "price_difference": difference,
        "price_change_pct": pct,
        "tax_rate": _numeric_or_zero(product.get("tax_rate")),
        "margin_category": product.get("margin_category"),
        "prix_de_vente": price_for_sale,
        "currency": line.get("currency") or product.get("currency"),
        "remise_temp": remise_temp,
        "remise_detail": remise_detail,
        "q_discount": q_discount,
        "g_discount": _numeric_or_zero(line.get("g_discount")),
        "p_discount": p_discount,
        "e_discount": e_discount,
        "fuel_surcharge_pct": _numeric_or_zero(line.get("fuel_surcharge_pct")),
        "matched": True,
        "match_method": match_method,
        "price_changed": price_changed,
        "abnormal_change": abnormal_change,
        "change_blocked": change_blocked,
        "block_reason": _block_reason(change_blocked, abnormal_change, config),
    }


def _unmatched_row(line: pd.Series) -> dict[str, object]:
    return {
        "external_id": None,
        "article_code": None,
        "supplier_code": None,
        "supplier_article_code": line["supplier_article_code"],
        "invoice_description": line["description"],
        "database_description": None,
        "current_price": None,
        "invoice_unit_price": line["unit_price"],
        "adjusted_unit_price": line.get("adjusted_unit_price", line["unit_price"]),
        "supplier_unit_ratio": None,
        "comparison_unit_price": None,
        "price_difference": None,
        "price_change_pct": None,
        "tax_rate": None,
        "margin_category": None,
        "prix_de_vente": None,
        "currency": line.get("currency"),
        "remise_temp": int(_numeric_or_zero(line.get("remise_temp"))),
        "remise_detail": line.get("remise_detail") or _remise_detail(
            _numeric_or_zero(line.get("q_discount")),
            _numeric_or_zero(line.get("p_discount")),
            _numeric_or_zero(line.get("e_discount")),
        ),
        "q_discount": _numeric_or_zero(line.get("q_discount")),
        "g_discount": _numeric_or_zero(line.get("g_discount")),
        "p_discount": _numeric_or_zero(line.get("p_discount")),
        "e_discount": _numeric_or_zero(line.get("e_discount")),
        "fuel_surcharge_pct": _numeric_or_zero(line.get("fuel_surcharge_pct")),
        "matched": False,
        "match_method": None,
        "price_changed": False,
        "abnormal_change": False,
        "change_blocked": False,
        "block_reason": None,
    }


def _line_or_product_unit_ratio(line: pd.Series, product: pd.Series) -> float:
    override = line.get("supplier_unit_ratio_override")
    if override is not None and not pd.isna(override):
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    return _numeric_or_zero(product.get("supplier_unit_ratio")) or 1.0


def _conditional_unit_ratio_override(
    line: pd.Series,
    base_ratio: float,
    invoice_price: float,
    current_price: float,
    config: MatchConfig,
) -> float:
    override = line.get("supplier_unit_ratio_override_when_abnormal")
    if override is None or pd.isna(override):
        return base_ratio
    try:
        override_ratio = float(override)
    except (TypeError, ValueError):
        return base_ratio

    base_difference = invoice_price * base_ratio - current_price
    override_difference = invoice_price * override_ratio - current_price
    if _is_abnormal_price_change(base_difference, current_price, config) and not _is_abnormal_price_change(
        override_difference,
        current_price,
        config,
    ):
        return override_ratio
    return base_ratio


def _is_abnormal_price_change(
    difference: float,
    current_price: float,
    config: MatchConfig,
) -> bool:
    if not current_price:
        return False
    pct = difference / current_price
    return bool(
        abs(pct) > config.abnormal_ratio
        and (difference < config.borne_inf or difference > config.borne_sup)
    )


def _strip_numeric_leading_zero_key(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text.isdigit():
        return ""
    return text.lstrip("0") or "0"


def _match_epice_truncated_reference(line: pd.Series, supplier_products: pd.DataFrame) -> pd.DataFrame:
    invoice_key = line["supplier_article_key"]
    if not invoice_key:
        return supplier_products.iloc[0:0]

    truncated_keys = supplier_products["supplier_article_key"].astype(str).str[:-2]
    candidates = supplier_products[truncated_keys == invoice_key]
    if len(candidates) == 1:
        return candidates
    return supplier_products.iloc[0:0]


def _numeric_or_zero(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _remise_detail(q_discount: float, p_discount: float, e_discount: float) -> str:
    parts = []
    if q_discount:
        parts.append(f"Q*={q_discount:g}")
    if p_discount:
        parts.append(f"P={p_discount:g}")
    if e_discount:
        parts.append(f"E={e_discount:g}")
    return ", ".join(parts)


def _block_reason(change_blocked: bool, abnormal_change: bool, config: MatchConfig) -> str | None:
    if change_blocked:
        return "remise_non_appliquee"
    if abnormal_change:
        return f"ecart de prix > {config.abnormal_ratio:.0%}"
    return None
