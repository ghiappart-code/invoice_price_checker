from __future__ import annotations

import pickle
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.text import normalize_key


REQUIRED_COLUMNS = {
    "article_code",
    "description",
    "supplier_code",
    "supplier_article_code",
    "current_price",
}

COLUMN_ALIASES = {
    "id": "article_code",
    "id_externe": "external_id",
    "article": "article_code",
    "code_article": "article_code",
    "reference_article": "article_code",
    "nom": "description",
    "designation": "description",
    "libelle": "description",
    "fournisseur": "supplier_code",
    "fournisseurs/id": "supplier_code",
    "code_fournisseur": "supplier_code",
    "supplier": "supplier_code",
    "reference_fournisseur": "supplier_article_code",
    "article_fournisseur": "supplier_article_code",
    "code_article_fournisseur": "supplier_article_code",
    "fournisseurs/référence_fournisseur": "supplier_article_code",
    "fournisseurs/reference_fournisseur": "supplier_article_code",
    "fournisseurs/prix": "current_price",
    "fournisseurs/unité_de_mesure/ratio": "supplier_unit_ratio",
    "fournisseurs/unite_de_mesure/ratio": "supplier_unit_ratio",
    "taxes_à_la_vente/montant": "tax_rate",
    "taxes_a_la_vente/montant": "tax_rate",
    "catégorie_de_marge/nom": "margin_category",
    "categorie_de_marge/nom": "margin_category",
    "coût": "current_price",
    "cout": "current_price",
    "prix": "current_price",
    "prix_actuel": "current_price",
    "prix_achat": "current_price",
    "devise": "currency",
    "monnaie": "currency",
    "catégorie_d'article/catégorie_mère/nom": "category",
    "categorie_d'article/categorie_mere/nom": "category",
}


def load_product_database(file: BinaryIO) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file)
    elif name.endswith(".data"):
        df = pickle.load(file)
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Pickle .data file does not contain a pandas DataFrame.")
    else:
        raise ValueError("Unsupported database format. Use CSV, Excel, or pickle .data.")

    df.columns = [normalize_column_name(col) for col in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        columns = ", ".join(sorted(missing))
        raise ValueError(f"Missing required column(s): {columns}")
    return normalize_product_database(df)


def normalize_product_database(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(col) for col in df.columns]
    df = _coalesce_duplicate_columns(df)
    for column in [
        "article_code",
        "external_id",
        "supplier_code",
        "supplier_article_code",
        "description",
        "currency",
        "margin_category",
    ]:
        if column in df:
            df[column] = df[column].fillna("").astype(str).str.strip()
    for column in ["supplier_code", "supplier_article_code"]:
        if column in df:
            df[column] = df[column].map(_clean_identifier)
    if "current_price" in df:
        df["current_price"] = pd.to_numeric(df["current_price"], errors="coerce")
    if "tax_rate" in df:
        df["tax_rate"] = pd.to_numeric(df["tax_rate"], errors="coerce").fillna(0.0)
    else:
        df["tax_rate"] = 0.0
    if "margin_category" not in df:
        df["margin_category"] = ""
    if "supplier_unit_ratio" in df:
        df["supplier_unit_ratio"] = pd.to_numeric(df["supplier_unit_ratio"], errors="coerce").fillna(1.0)
        df.loc[df["supplier_unit_ratio"] == 0, "supplier_unit_ratio"] = 1.0
    else:
        df["supplier_unit_ratio"] = 1.0
    if "category" in df:
        category_key = df["category"].fillna("").map(normalize_key)
        fruit_veg_keys = {
            normalize_key("Fruits & Legumes"),
            normalize_key("Fruits et legumes"),
            normalize_key("Fruits et légumes"),
        }
        df = df[~category_key.isin(fruit_veg_keys)].copy()
    if "currency" not in df:
        df["currency"] = "EUR"
    if "external_id" not in df:
        df["external_id"] = ""
    df["supplier_article_key"] = df.get("supplier_article_code", "").map(normalize_key)
    df["description_key"] = df.get("description", "").map(normalize_key)
    return df


def normalize_column_name(column: object) -> str:
    name = str(column).strip().lower()
    normalized = name.replace(" ", "_").replace("-", "_")
    return COLUMN_ALIASES.get(normalized, normalized)


def _coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = pd.DataFrame(index=df.index)
    for column in dict.fromkeys(df.columns):
        values = df.loc[:, df.columns == column]
        if values.shape[1] == 1:
            output[column] = values.iloc[:, 0]
        else:
            output[column] = values.bfill(axis=1).iloc[:, 0]
    return output


def _clean_identifier(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text
