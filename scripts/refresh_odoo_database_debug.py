from __future__ import annotations

"""Refresh the local Odoo article database with detailed timing logs.

Run from the project root:

    python scripts/refresh_odoo_database_debug.py

The script reads .streamlit/secrets.toml, downloads Odoo data in batches, and
writes data_files/var_articles.data. It is intentionally separate from the
Streamlit app so local network or Odoo timeout issues can be diagnosed directly.
"""

from pathlib import Path
import pickle
import sys
import time
import tomllib
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from invoice_price_checker.odoo_articles import config_from_mapping, margin_markup_by_id, supplierinfo_partner_field  # noqa: E402


DEFAULT_OUTPUT_PATH = ROOT / "data_files" / "var_articles.data"


def main() -> int:
    started_at = time.monotonic()
    print("Odoo database debug refresh")
    print(f"Project root: {ROOT}")

    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"ERROR: secrets file not found: {secrets_path}", file=sys.stderr)
        return 1

    with secrets_path.open("rb") as handle:
        secrets = tomllib.load(handle)
    if "odoo" not in secrets:
        print("ERROR: missing [odoo] section in .streamlit/secrets.toml", file=sys.stderr)
        return 1

    config = config_from_mapping(secrets["odoo"])
    output_path = Path(secrets["odoo"].get("output_path", DEFAULT_OUTPUT_PATH))

    print(f"Odoo host: {config.url}:{config.port}")
    print(f"Odoo database: {config.database}")
    print(f"Odoo username: {config.username}")
    print(f"Timeout per request: {config.timeout}s")
    print(f"Batch size: {config.batch_size}")
    print(f"Output path: {output_path}")

    try:
        df = fetch_articles_from_odoo_debug(config)
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        print(f"ERROR after {elapsed:.1f}s: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        pickle.dump(df, handle)

    elapsed = time.monotonic() - started_at
    print(f"Wrote {len(df)} rows to {output_path}")
    print(f"Total elapsed: {elapsed:.1f}s")
    return 0


def fetch_articles_from_odoo_debug(config) -> pd.DataFrame:
    import odoorpc

    with timed("connect"):
        odoo = odoorpc.ODOO(config.url, port=config.port, protocol="jsonrpc+ssl", timeout=config.timeout)

    with timed("login"):
        odoo.login(config.database, config.username, config.password)

    Product = odoo.env["product.product"]
    articles_data = search_read_all_debug(
        "product.product active products",
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
    print(f"DataFrame articles: {len(df_articles)} rows")

    df_articles["template_id"] = df_articles["product_tmpl_id"].apply(relation_id)
    df_articles["categ_id_only"] = df_articles["categ_id"].apply(relation_id)
    df_articles["marge_nom"] = df_articles["margin_classification_id"].apply(relation_name)
    inspect_margin_classifications(Product, odoo, df_articles, config.batch_size)
    df_articles["marge_markup"] = df_articles["margin_classification_id"].apply(
        relation_id
    ).map(margin_markup_by_id(Product, odoo, df_articles, config.batch_size))

    SupplierInfo = odoo.env["product.supplierinfo"]
    supplier_partner_field = supplierinfo_partner_field(SupplierInfo)
    print(f"product.supplierinfo supplier field: {supplier_partner_field}")
    fournisseurs_data = search_read_all_debug(
        "product.supplierinfo",
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
    print(f"DataFrame fournisseurs: {len(df_fournisseurs)} rows")
    if df_fournisseurs.empty:
        df_fournisseurs = pd.DataFrame(
            columns=["template_id", "product_code", "price", "supplier_id", "supplier_name", "uom_id", "uom_name"]
        )
    else:
        df_fournisseurs["supplier_id"] = df_fournisseurs[supplier_partner_field].apply(relation_id)
        df_fournisseurs["supplier_name"] = df_fournisseurs[supplier_partner_field].apply(relation_name)
        df_fournisseurs["uom_id"] = df_fournisseurs["product_uom"].apply(relation_id)
        df_fournisseurs["uom_name"] = df_fournisseurs["product_uom"].apply(relation_name)
        df_fournisseurs["template_id"] = df_fournisseurs["product_tmpl_id"].apply(relation_id)

    uom_ids = df_fournisseurs["uom_id"].dropna().unique().tolist()
    if uom_ids:
        uom_data = search_read_all_debug(
            "uom.uom",
            odoo.env["uom.uom"],
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
        tax_data = search_read_all_debug(
            "account.tax",
            odoo.env["account.tax"],
            [("id", "in", unique_tax_ids)],
            ["id", "name", "amount"],
            batch_size=config.batch_size,
        )
        df_taxes = pd.DataFrame(tax_data)
    else:
        df_taxes = pd.DataFrame(columns=["id", "amount"])

    categ_ids = df_articles["categ_id_only"].dropna().unique().tolist()
    if categ_ids:
        categ_data = search_read_all_debug(
            "product.category",
            odoo.env["product.category"],
            [("id", "in", categ_ids)],
            ["id", "name", "parent_id"],
            batch_size=config.batch_size,
        )
        df_categories = pd.DataFrame(categ_data)
        df_categories["parent_name"] = df_categories["parent_id"].apply(relation_name)
    else:
        df_categories = pd.DataFrame(columns=["id", "parent_name"])

    with timed("merge dataframes"):
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

        df_final["tax_id"] = df_final["taxes_id"].apply(lambda value: value[0] if value and len(value) > 0 else None)
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
            "product_code": "Fournisseurs/Reference Fournisseur",
            "standard_price": "Cout",
            "price": "Fournisseurs/Prix",
            "uom_name": "Fournisseurs/Unite de mesure/Nom affiche",
            "uom_ratio": "Fournisseurs/Unite de mesure/Ratio",
            "tax_amount": "Taxes a la vente/Montant",
            "marge_nom": "Categorie de marge/Nom",
            "marge_markup": "Categorie de marge/Markup",
            "barcode": "Code Barre",
            "categorie_mere": "Categorie d'article/Categorie mere/Nom",
        }
        df_final = df_final.rename(columns=column_mapping)

    # Preserve the exact accented column names expected by the main application.
    df_final = df_final.rename(
        columns={
            "Fournisseurs/Reference Fournisseur": "Fournisseurs/Référence Fournisseur",
            "Cout": "Coût",
            "Fournisseurs/Unite de mesure/Nom affiche": "Fournisseurs/Unité de mesure/Nom affiché",
            "Fournisseurs/Unite de mesure/Ratio": "Fournisseurs/Unité de mesure/Ratio",
            "Taxes a la vente/Montant": "Taxes à la vente/Montant",
            "Categorie de marge/Nom": "Catégorie de marge/Nom",
            "Categorie de marge/Markup": "Catégorie de marge/Markup",
            "Categorie d'article/Categorie mere/Nom": "Catégorie d'article/Catégorie mère/Nom",
        }
    )
    final_columns = [
        "id",
        "Nom",
        "Fournisseurs/ID",
        "Fournisseurs/Référence Fournisseur",
        "Coût",
        "Fournisseurs/Prix",
        "Fournisseurs/Unité de mesure/Nom affiché",
        "Fournisseurs/Unité de mesure/Ratio",
        "Taxes à la vente/Montant",
        "Catégorie de marge/Nom",
        "Catégorie de marge/Markup",
        "Code Barre",
        "Catégorie d'article/Catégorie mère/Nom",
    ]
    return df_final[final_columns]


def inspect_margin_classifications(Product: Any, odoo: Any, df_articles: pd.DataFrame, batch_size: int) -> None:
    print("START margin_classification_id inspection")
    try:
        product_fields = Product.fields_get(["margin_classification_id"])
        field_info = product_fields.get("margin_classification_id", {})
        relation_model = field_info.get("relation")
        print(f"margin_classification_id field info: {field_info}")
        print(f"margin_classification_id relation model: {relation_model}")
        if not relation_model:
            print("END margin_classification_id inspection: no relation model")
            return

        margin_ids = sorted(
            {
                value
                for value in df_articles["margin_classification_id"].map(relation_id).dropna().tolist()
                if value
            }
        )
        print(f"margin classifications used by active products: {len(margin_ids)} ids {margin_ids}")
        if not margin_ids:
            print("END margin_classification_id inspection: no used ids")
            return

        MarginModel = odoo.env[relation_model]
        fields_metadata = MarginModel.fields_get()
        candidate_names = [
            name
            for name, meta in fields_metadata.items()
            if _is_margin_candidate_field(name, meta)
        ]
        print(f"{relation_model}: candidate numeric/text fields: {candidate_names}")

        fields_to_read = ["id", "name", *[field for field in candidate_names if field not in {"id", "name"}]]
        records = search_read_all_debug(
            f"{relation_model} used margin classifications",
            MarginModel,
            [("id", "in", margin_ids)],
            fields_to_read,
            batch_size=min(batch_size, 100),
        )
        print(f"{relation_model}: records read for margin inspection:")
        for record in records:
            print(f"  {record}")
    except Exception as exc:
        print(f"FAILED margin_classification_id inspection: {type(exc).__name__}: {exc}")
    print("END margin_classification_id inspection")


def _is_margin_candidate_field(name: str, meta: dict[str, Any]) -> bool:
    field_type = meta.get("type")
    lower = name.lower()
    label = str(meta.get("string", "")).lower()
    text = f"{lower} {label}"
    if field_type in {"float", "integer", "monetary", "selection", "char"}:
        return any(token in text for token in ["rate", "margin", "marge", "mark", "taux", "percent", "pourcent", "consigne"])
    return name in {"name", "display_name"}


def search_read_all_debug(
    label: str,
    model: Any,
    domain: list[Any],
    fields: list[str],
    *,
    batch_size: int,
    skip_failed_batches: bool = False,
) -> list[dict[str, Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    rows: list[dict[str, Any]] = []
    print(f"START {label}: fields={len(fields)} batch_size={batch_size}")
    with timed(f"{label}: search ids"):
        ids = model.search(domain)
    print(f"{label}: found {len(ids)} ids")
    for batch_index, offset in enumerate(range(0, len(ids), batch_size), start=1):
        batch_ids = ids[offset : offset + batch_size]
        batch_start = time.monotonic()
        print(
            f"  {label}: read batch {batch_index} offset={offset} "
            f"count={len(batch_ids)} first_id={batch_ids[0]} last_id={batch_ids[-1]}",
            flush=True,
        )
        try:
            batch = read_with_retry_debug(
                label,
                model,
                batch_ids,
                fields,
                attempts=1 if skip_failed_batches else 2,
            )
        except Exception as exc:
            if skip_failed_batches:
                print(
                    f"  {label}: SKIP batch {batch_index} after retries "
                    f"({len(batch_ids)} ids): {type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue
            raise
        elapsed = time.monotonic() - batch_start
        print(f"  {label}: read batch {batch_index} returned {len(batch)} rows in {elapsed:.1f}s", flush=True)
        rows.extend(batch)
    print(f"END {label}: total={len(rows)} rows")
    return rows


def read_with_retry_debug(
    label: str,
    model: Any,
    ids: list[int],
    fields: list[str],
    *,
    attempts: int = 2,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(f"    {label}: retry {attempt}/{attempts} for {len(ids)} ids", flush=True)
            return model.read(ids, fields)
        except Exception as exc:
            last_error = exc
            print(f"    {label}: attempt {attempt}/{attempts} failed: {type(exc).__name__}: {exc}", flush=True)
    if last_error is not None:
        raise last_error
    return []


class timed:
    def __init__(self, label: str):
        self.label = label
        self.started_at = 0.0

    def __enter__(self):
        self.started_at = time.monotonic()
        print(f"START {self.label}", flush=True)
        return self

    def __exit__(self, exc_type, exc, traceback):
        elapsed = time.monotonic() - self.started_at
        if exc is None:
            print(f"END {self.label}: {elapsed:.1f}s", flush=True)
        else:
            print(f"FAILED {self.label} after {elapsed:.1f}s: {exc}", flush=True)
        return False


def relation_id(value: object) -> int | None:
    return value[0] if isinstance(value, (list, tuple)) and value else None


def relation_name(value: object) -> str | None:
    return value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else None


if __name__ == "__main__":
    raise SystemExit(main())
