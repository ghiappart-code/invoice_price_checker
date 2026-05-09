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
    )


def config_from_mapping(values: dict[str, Any]) -> OdooConfig:
    return OdooConfig(
        url=str(values["url"]),
        port=int(values.get("port", 443)),
        database=str(values["database"]),
        username=str(values["username"]),
        password=str(values["password"]),
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

    odoo = odoorpc.ODOO(config.url, port=config.port, protocol="jsonrpc+ssl")
    odoo.login(config.database, config.username, config.password)

    Product = odoo.env["product.product"]
    articles_data = Product.search_read(
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
    )
    df_articles = pd.DataFrame(articles_data)

    IrModelData = odoo.env["ir.model.data"]
    external_ids_data = IrModelData.search_read(
        [("model", "=", "product.product")],
        ["res_id", "complete_name"],
    )
    df_external_ids = pd.DataFrame(external_ids_data)
    if not df_external_ids.empty:
        df_external_ids = df_external_ids.rename(columns={"complete_name": "external_id"})
        df_articles = df_articles.merge(
            df_external_ids[["res_id", "external_id"]],
            left_on="id",
            right_on="res_id",
            how="left",
        )
    else:
        df_articles["external_id"] = None

    df_articles["template_id"] = df_articles["product_tmpl_id"].apply(_relation_id)
    df_articles["categ_id_only"] = df_articles["categ_id"].apply(_relation_id)
    df_articles["marge_nom"] = df_articles["margin_classification_id"].apply(_relation_name)

    SupplierInfo = odoo.env["product.supplierinfo"]
    fournisseurs_data = SupplierInfo.search_read(
        [],
        [
            "id",
            "product_tmpl_id",
            "product_id",
            "name",
            "product_code",
            "price",
            "product_uom",
        ],
    )
    df_fournisseurs = pd.DataFrame(fournisseurs_data)
    if df_fournisseurs.empty:
        df_fournisseurs = pd.DataFrame(
            columns=["template_id", "product_code", "price", "supplier_id", "supplier_name", "uom_id", "uom_name"]
        )
    else:
        df_fournisseurs["supplier_id"] = df_fournisseurs["name"].apply(_relation_id)
        df_fournisseurs["supplier_name"] = df_fournisseurs["name"].apply(_relation_name)
        df_fournisseurs["uom_id"] = df_fournisseurs["product_uom"].apply(_relation_id)
        df_fournisseurs["uom_name"] = df_fournisseurs["product_uom"].apply(_relation_name)
        df_fournisseurs["template_id"] = df_fournisseurs["product_tmpl_id"].apply(_relation_id)

    uom_ids = df_fournisseurs["uom_id"].dropna().unique().tolist()
    if uom_ids:
        Uom = odoo.env["uom.uom"]
        uom_data = Uom.search_read([("id", "in", uom_ids)], ["id", "name", "factor"])
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
        tax_data = Tax.search_read([("id", "in", unique_tax_ids)], ["id", "name", "amount"])
        df_taxes = pd.DataFrame(tax_data)
    else:
        df_taxes = pd.DataFrame(columns=["id", "amount"])

    categ_ids = df_articles["categ_id_only"].dropna().unique().tolist()
    if categ_ids:
        Category = odoo.env["product.category"]
        categ_data = Category.search_read([("id", "in", categ_ids)], ["id", "name", "parent_id"])
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
        "external_id": "ID Externe",
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
        "barcode": "Code Barre",
        "categorie_mere": "Catégorie d'article/Catégorie mère/Nom",
    }
    df_final = df_final.rename(columns=column_mapping)
    return df_final[[col for col in column_mapping.values()]]


def _relation_id(value: object) -> int | None:
    return value[0] if isinstance(value, (list, tuple)) and value else None


def _relation_name(value: object) -> str | None:
    return value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else None
