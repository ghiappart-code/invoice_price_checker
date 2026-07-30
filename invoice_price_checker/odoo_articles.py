from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import pickle
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data_files"
DEFAULT_DATABASE_PATH = DEFAULT_DATA_DIR / "var_articles.data"


@dataclass(frozen=True)
class OdooConfig:
    url: str
    port: int
    database: str
    username: str
    password: str
    timeout: int = 300
    batch_size: int = 500


def default_database_path() -> Path:
    return DEFAULT_DATABASE_PATH


def database_status(path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": path, "created_at": None, "modified_at": None, "size_bytes": 0}
    stat = path.stat()
    return {
        "exists": True,
        "path": path,
        "created_at": stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime,
        "modified_at": stat.st_mtime,
        "size_bytes": stat.st_size,
    }


def config_from_env() -> OdooConfig:
    missing = [
        name
        for name in [
            "ODOO_URL",
            "ODOO_DATABASE",
            "ODOO_USERNAME",
            "ODOO_PASSWORD",
        ]
        if not os.getenv(name)
    ]
    if missing:
        raise ValueError(
            "Missing Odoo environment variable(s): " + ", ".join(missing)
        )
    return OdooConfig(
        url=os.environ["ODOO_URL"],
        port=int(os.getenv("ODOO_PORT", "443")),
        database=os.environ["ODOO_DATABASE"],
        username=os.environ["ODOO_USERNAME"],
        password=os.environ["ODOO_PASSWORD"],
        timeout=int(os.getenv("ODOO_TIMEOUT", "300")),
        batch_size=int(os.getenv("ODOO_BATCH_SIZE", "500")),
    )


def config_from_mapping(values: dict[str, Any]) -> OdooConfig:
    return OdooConfig(
        url=str(values["url"]),
        port=int(values.get("port", 443)),
        database=str(values["database"]),
        username=str(values["username"]),
        password=str(values["password"]),
        timeout=int(values.get("timeout", 300)),
        batch_size=int(values.get("batch_size", 500)),
    )


def refresh_articles_database(
    config: OdooConfig,
    output_path: Path = DEFAULT_DATABASE_PATH,
) -> pd.DataFrame:
    df = fetch_articles_from_odoo(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        pickle.dump(df, handle)
    return df


def fetch_articles_from_odoo(config: OdooConfig) -> pd.DataFrame:
    import odoorpc

    odoo = odoorpc.ODOO(config.url, port=config.port, protocol="jsonrpc+ssl", timeout=config.timeout)
    odoo.login(config.database, config.username, config.password)

    Product = odoo.env["product.product"]
    articles_data = _search_read_all(
        Product,
        [("active", "=", True)],
        [
            "id",
            "name",
            "standard_price",
            "barcode",
            "categ_id",
            "taxes_id",
            "product_tmpl_id",
            "margin_classification_id",
        ],
        batch_size=config.batch_size,
    )
    df_articles = pd.DataFrame(articles_data)

    df_articles["template_id"] = df_articles["product_tmpl_id"].apply(_relation_id)
    df_articles["categ_id_only"] = df_articles["categ_id"].apply(_relation_id)
    df_articles["marge_nom"] = df_articles["margin_classification_id"].apply(_relation_name)
    df_articles["marge_markup"] = df_articles["margin_classification_id"].apply(
        _relation_id
    ).map(margin_markup_by_id(Product, odoo, df_articles, config.batch_size))

    SupplierInfo = odoo.env["product.supplierinfo"]
    supplier_partner_field = supplierinfo_partner_field(SupplierInfo)
    fournisseurs_data = _search_read_all(
        SupplierInfo,
        [],
        [
            "id",
            "product_tmpl_id",
            "product_id",
            supplier_partner_field,
            "product_code",
            "price",
            "product_uom",
        ],
        batch_size=config.batch_size,
    )
    df_fournisseurs = pd.DataFrame(fournisseurs_data)
    if df_fournisseurs.empty:
        df_fournisseurs = pd.DataFrame(
            columns=["template_id", "product_code", "price", "supplier_id", "supplier_name", "uom_id", "uom_name"]
        )
    else:
        df_fournisseurs["supplier_id"] = df_fournisseurs[supplier_partner_field].apply(_relation_id)
        df_fournisseurs["supplier_name"] = df_fournisseurs[supplier_partner_field].apply(_relation_name)
        df_fournisseurs["uom_id"] = df_fournisseurs["product_uom"].apply(_relation_id)
        df_fournisseurs["uom_name"] = df_fournisseurs["product_uom"].apply(_relation_name)
        df_fournisseurs["template_id"] = df_fournisseurs["product_tmpl_id"].apply(_relation_id)

    uom_ids = df_fournisseurs["uom_id"].dropna().unique().tolist()
    if uom_ids:
        Uom = odoo.env["uom.uom"]
        uom_data = _search_read_all(
            Uom,
            [("id", "in", uom_ids)],
            ["id", "name", "factor"],
            batch_size=config.batch_size,
        )
        df_uom = pd.DataFrame(uom_data).rename(columns={"factor": "uom_ratio"})
    else:
        df_uom = pd.DataFrame(columns=["id", "uom_ratio"])

    all_tax_ids: list[int] = []
    for tax_list in df_articles["taxes_id"]:
        if tax_list:
            all_tax_ids.extend(tax_list)
    unique_tax_ids = list(set(all_tax_ids))
    if unique_tax_ids:
        Tax = odoo.env["account.tax"]
        tax_data = _search_read_all(
            Tax,
            [("id", "in", unique_tax_ids)],
            ["id", "name", "amount"],
            batch_size=config.batch_size,
        )
        df_taxes = pd.DataFrame(tax_data)
    else:
        df_taxes = pd.DataFrame(columns=["id", "amount"])

    categ_ids = df_articles["categ_id_only"].dropna().unique().tolist()
    if categ_ids:
        Category = odoo.env["product.category"]
        categ_data = _search_read_all(
            Category,
            [("id", "in", categ_ids)],
            ["id", "name", "parent_id"],
            batch_size=config.batch_size,
        )
        df_categories = pd.DataFrame(categ_data)
        df_categories["parent_name"] = df_categories["parent_id"].apply(_relation_name)
    else:
        df_categories = pd.DataFrame(columns=["id", "parent_name"])

    df_final = df_articles.merge(
        df_categories[["id", "parent_name"]],
        left_on="categ_id_only",
        right_on="id",
        how="left",
        suffixes=("", "_cat"),
    ).rename(columns={"parent_name": "categorie_mere"})

    df_final = df_final.merge(
        df_fournisseurs[["template_id", "product_code", "price", "supplier_id", "supplier_name", "uom_id", "uom_name"]],
        on="template_id",
        how="left",
    )

    df_final = df_final.merge(
        df_uom[["id", "uom_ratio"]],
        left_on="uom_id",
        right_on="id",
        how="left",
        suffixes=("", "_uom"),
    )

    df_final["tax_id"] = df_final["taxes_id"].apply(lambda x: x[0] if x and len(x) > 0 else None)
    df_final = df_final.merge(
        df_taxes[["id", "amount"]],
        left_on="tax_id",
        right_on="id",
        how="left",
        suffixes=("", "_tax"),
    ).rename(columns={"amount": "tax_amount"})

    column_mapping = {
        "id": "id",
        "name": "Nom",
        "supplier_id": "Fournisseurs/ID",
        "product_code": "Fournisseurs/Référence Fournisseur",
        "standard_price": "Coût",
        "price": "Fournisseurs/Prix",
        "uom_name": "Fournisseurs/Unité de mesure/Nom affiché",
        "uom_ratio": "Fournisseurs/Unité de mesure/Ratio",
        "tax_amount": "Taxes à la vente/Montant",
        "marge_nom": "Catégorie de marge/Nom",
        "marge_markup": "Catégorie de marge/Markup",
        "barcode": "Code Barre",
        "categorie_mere": "Catégorie d'article/Catégorie mère/Nom",
    }
    df_final = df_final.rename(columns=column_mapping)
    return df_final[[col for col in column_mapping.values()]]


def margin_markup_by_id(Product: Any, odoo: Any, df_articles: pd.DataFrame, batch_size: int) -> dict[int, float]:
    """Return Odoo product.margin.classification markup values keyed by classification id."""
    try:
        product_fields = Product.fields_get(["margin_classification_id"])
        relation_model = product_fields.get("margin_classification_id", {}).get("relation")
        if not relation_model:
            return {}

        margin_ids = sorted(
            {
                value
                for value in df_articles["margin_classification_id"].map(_relation_id).dropna().tolist()
                if value
            }
        )
        if not margin_ids:
            return {}

        Margin = odoo.env[relation_model]
        if "markup" not in _model_field_names(Margin):
            return {}

        rows = _search_read_all(
            Margin,
            [("id", "in", margin_ids)],
            ["id", "markup"],
            batch_size=min(batch_size, 100),
        )
        return {
            int(row["id"]): float(row["markup"])
            for row in rows
            if row.get("id") is not None and row.get("markup") is not None
        }
    except Exception:
        return {}


def supplierinfo_partner_field(model: Any) -> str:
    fields = _model_field_names(model)
    for field in ["partner_id", "name"]:
        if field in fields:
            return field
    raise ValueError("product.supplierinfo has neither partner_id nor name supplier field")


def _search_read_all(
    model: Any,
    domain: list[Any],
    fields: list[str],
    *,
    batch_size: int,
    skip_failed_batches: bool = False,
) -> list[dict[str, Any]]:
    if batch_size <= 0:
        raise ValueError("Odoo batch_size must be greater than zero")

    rows: list[dict[str, Any]] = []
    ids = model.search(domain)
    for offset in range(0, len(ids), batch_size):
        batch_ids = ids[offset : offset + batch_size]
        try:
            batch = _read_with_retry(
                model,
                batch_ids,
                fields,
                attempts=1 if skip_failed_batches else 2,
            )
        except Exception:
            if skip_failed_batches:
                continue
            raise
        rows.extend(batch)
    return rows


def _model_field_names(model: Any) -> set[str]:
    try:
        fields_metadata = model.fields_get()
    except TypeError:
        fields_metadata = model.fields_get([])
    return set(fields_metadata)


def _read_with_retry(
    model: Any,
    ids: list[int],
    fields: list[str],
    *,
    attempts: int = 2,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return model.read(ids, fields)
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _relation_id(value: object) -> int | None:
    return value[0] if isinstance(value, (list, tuple)) and value else None


def _relation_name(value: object) -> str | None:
    return value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else None
