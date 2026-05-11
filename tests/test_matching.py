import pandas as pd

from invoice_price_checker.database import normalize_product_database
from invoice_price_checker.matching import compare_invoice_to_database
from invoice_price_checker.models import MatchConfig


def test_compare_detects_changed_price():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Organic flour 1kg",
                    "supplier_code": "GENERIC",
                    "supplier_article_code": "FLOUR-1KG",
                    "current_price": 2.50,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "FLOUR-1KG",
                "description": "Organic flour 1kg",
                "unit_price": 2.75,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="GENERIC"),
    )

    assert bool(result.loc[0, "Match_Fact_DB"]) is True
    assert bool(result.loc[0, "PU_Modif"]) is True
    assert result.loc[0, "Ecart_Prix"] == 0.25

def test_duplicate_invoice_reference_is_flagged_after_first_occurrence():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Organic flour 1kg",
                    "supplier_code": "GENERIC",
                    "supplier_article_code": "FLOUR-1KG",
                    "current_price": 2.50,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "FLOUR-1KG",
                "description": "Organic flour 1kg",
                "unit_price": 2.75,
                "currency": "EUR",
            },
            {
                "supplier_article_code": "FLOUR-1KG",
                "description": "Organic flour 1kg",
                "unit_price": 2.75,
                "currency": "EUR",
            },
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="GENERIC"),
    )

    assert bool(result.loc[0, "PU_Modif"]) is True
    assert bool(result.loc[0, "Ecart_Prix_Anormal"]) is False
    assert bool(result.loc[1, "PU_Modif"]) is False
    assert bool(result.loc[1, "Ecart_Prix_Anormal"]) is True
    assert result.loc[1, "Raison_du_Blocage"] == "ligne_dupliquee_facture"


def test_abnormal_price_change_has_readable_block_reason():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Organic flour 1kg",
                    "supplier_code": "GENERIC",
                    "supplier_article_code": "FLOUR-1KG",
                    "current_price": 2.00,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "FLOUR-1KG",
                "description": "Organic flour 1kg",
                "unit_price": 2.80,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="GENERIC", abnormal_ratio=0.30),
    )

    assert bool(result.loc[0, "Ecart_Prix_Anormal"]) is True
    assert result.loc[0, "Raison_du_Blocage"] == "ecart de prix > 30%"
