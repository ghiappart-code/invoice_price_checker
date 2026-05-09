from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from invoice_price_checker.odoo_articles import OdooConfig


UPDATE_COLUMNS = [
    "ID Externe",
    "id",
    "Fournisseurs/ID",
    "Coût",
    "Fournisseurs/Prix",
    "Prix de vente",
]


@dataclass(frozen=True)
class UpdateSummary:
    total: int
    success: int
    warnings: int
    errors: int
    results: pd.DataFrame


def prepare_odoo_update_rows(changed_rows: pd.DataFrame) -> pd.DataFrame:
    if changed_rows.empty:
        return pd.DataFrame(columns=UPDATE_COLUMNS)

    eligible = changed_rows[
        (changed_rows["Match_Fact_DB"] == True)
        & (changed_rows["PU_Modif"] == True)
        & (changed_rows["Ecart_Prix_Anormal"] == False)
        & (changed_rows["Blocage_Modif"] == False)
    ].copy()

    update_rows = pd.DataFrame(
        {
            "ID Externe": eligible.get("ID_externe"),
            "id": eligible.get("Article_Ref_EAN"),
            "Fournisseurs/ID": eligible.get("ID_Fournisseur"),
            "Coût": eligible.get("Fact_PU_unitaire"),
            "Fournisseurs/Prix": eligible.get("Fact_PU_Net_GZ"),
            "Prix de vente": eligible.get("prix_de_vente"),
        }
    )
    update_rows = update_rows.dropna(subset=["id", "Fournisseurs/ID", "Coût", "Fournisseurs/Prix", "Prix de vente"])
    if update_rows.empty:
        return pd.DataFrame(columns=UPDATE_COLUMNS)
    update_rows = update_rows[update_rows["Prix de vente"].map(_is_number)]
    if update_rows.empty:
        return pd.DataFrame(columns=UPDATE_COLUMNS)
    return update_rows[UPDATE_COLUMNS]


def update_odoo_prices(update_rows: pd.DataFrame, config: OdooConfig) -> UpdateSummary:
    import odoorpc

    odoo = odoorpc.ODOO(config.url, port=config.port, protocol="jsonrpc+ssl")
    odoo.login(config.database, config.username, config.password)

    Product = odoo.env["product.product"]
    SupplierInfo = odoo.env["product.supplierinfo"]

    results: list[dict[str, Any]] = []
    for _, row in update_rows.iterrows():
        article_id = _safe_int(row.get("id"))
        supplier_id = _safe_int(row.get("Fournisseurs/ID"))
        if article_id is None or supplier_id is None:
            results.append(_result(row, "error", "Missing article id or supplier id"))
            continue

        try:
            new_cost = float(row["Coût"])
            new_supplier_price = float(row["Fournisseurs/Prix"])
            new_sale_price = float(row["Prix de vente"])

            article = Product.browse(article_id)
            template_id = article.product_tmpl_id.id

            supplier_info = SupplierInfo.search_read(
                [("product_tmpl_id", "=", template_id), ("name", "=", supplier_id)],
                ["id"],
            )

            supplier_message = "supplier price updated"
            status = "success"
            if supplier_info:
                SupplierInfo.write([supplier_info[0]["id"]], {"price": new_supplier_price})
            else:
                supplier_message = "supplier info not found; product prices updated only"
                status = "warning"

            Product.write(
                [article_id],
                {
                    "standard_price": new_cost,
                    "list_price": new_sale_price,
                },
            )
            results.append(
                _result(
                    row,
                    status,
                    f"{supplier_message}; cost={new_cost}; sale_price={new_sale_price}",
                )
            )
        except Exception as exc:
            results.append(_result(row, "error", str(exc)))

    result_df = pd.DataFrame(results)
    if result_df.empty:
        result_df = pd.DataFrame(columns=[*UPDATE_COLUMNS, "status", "message"])
    return UpdateSummary(
        total=len(result_df),
        success=int((result_df["status"] == "success").sum()) if not result_df.empty else 0,
        warnings=int((result_df["status"] == "warning").sum()) if not result_df.empty else 0,
        errors=int((result_df["status"] == "error").sum()) if not result_df.empty else 0,
        results=result_df,
    )


def _result(row: pd.Series, status: str, message: str) -> dict[str, Any]:
    return {
        "ID Externe": row.get("ID Externe"),
        "id": row.get("id"),
        "Fournisseurs/ID": row.get("Fournisseurs/ID"),
        "Coût": row.get("Coût"),
        "Fournisseurs/Prix": row.get("Fournisseurs/Prix"),
        "Prix de vente": row.get("Prix de vente"),
        "status": status,
        "message": message,
    }


def _safe_int(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
