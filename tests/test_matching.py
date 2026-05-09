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
