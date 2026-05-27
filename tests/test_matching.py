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
    assert result.loc[0, "Ecart_Prix_percent"] == "10.0%"

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


def test_conditional_unit_ratio_override_is_used_only_when_database_ratio_is_abnormal():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Amande decortiquee vrac",
                    "supplier_code": "254",
                    "supplier_article_code": "39345",
                    "current_price": 9.30,
                    "supplier_unit_ratio": 0.04,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "39345",
                "description": "Amande decortiquee (25kg)",
                "unit_price": 10.99,
                "adjusted_unit_price": 11.03396,
                "supplier_unit_ratio_override_when_abnormal": 1.0,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="254", abnormal_ratio=0.30),
    )

    assert result.loc[0, "DB_Fournisseur_Unit_Ratio"] == 1.0
    assert result.loc[0, "Fact_PU_unitaire"] == 11.03396
    assert bool(result.loc[0, "Ecart_Prix_Anormal"]) is False


def test_conditional_unit_ratio_override_is_ignored_when_database_ratio_is_not_abnormal():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Biscuits coeur orange vrac",
                    "supplier_code": "254",
                    "supplier_article_code": "33509",
                    "current_price": 17.59,
                    "supplier_unit_ratio": 1 / 3,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "33509",
                "description": "Biscuits coeur orange chocolat noir vrac (3kg)",
                "unit_price": 52.53,
                "adjusted_unit_price": 52.74012,
                "supplier_unit_ratio_override_when_abnormal": 1.0,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="254", abnormal_ratio=0.30),
    )

    assert round(result.loc[0, "DB_Fournisseur_Unit_Ratio"], 6) == round(1 / 3, 6)
    assert round(result.loc[0, "Fact_PU_unitaire"], 3) == 17.58
    assert bool(result.loc[0, "Ecart_Prix_Anormal"]) is False


def test_epice_matches_database_reference_with_extra_two_character_suffix():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Biscuits Caramel Sel Guerande VRAC",
                    "supplier_code": "262",
                    "supplier_article_code": "BCSDAOVRAC",
                    "current_price": 43.35,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "BCSDAOVR",
                "description": "Biscuits Caramel Sel Guerande VRAC",
                "unit_price": 43.35,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="262"),
    )

    assert bool(result.loc[0, "Match_Fact_DB"]) is True
    assert result.loc[0, "Article_ID_Fournisseur"] == "BCSDAOVRAC"
    assert result.loc[0, "Match_Methode"] == "epice_supplier_article_code_without_last_two_chars"


def test_epice_truncated_reference_does_not_match_when_ambiguous():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Biscuits Caramel Sel Guerande VRAC",
                    "supplier_code": "262",
                    "supplier_article_code": "BCSDAOVRAC",
                    "current_price": 43.35,
                    "currency": "EUR",
                },
                {
                    "article_code": "A1002",
                    "description": "Biscuits Caramel Sel Guerande autre",
                    "supplier_code": "262",
                    "supplier_article_code": "BCSDAOVRZZ",
                    "current_price": 43.35,
                    "currency": "EUR",
                },
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "BCSDAOVR",
                "description": "Biscuits Caramel Sel Guerande VRAC",
                "unit_price": 43.35,
                "currency": "EUR",
            }
        ]
    )

    result = compare_invoice_to_database(
        products,
        invoice,
        MatchConfig(supplier_code="262", allow_description_fallback=False),
    )

    assert bool(result.loc[0, "Match_Fact_DB"]) is False


def test_description_match_is_flagged_for_manual_review():
    products = normalize_product_database(
        pd.DataFrame(
            [
                {
                    "article_code": "A1001",
                    "description": "Organic flour 1kg",
                    "supplier_code": "GENERIC",
                    "supplier_article_code": "FLOUR-DB",
                    "current_price": 2.50,
                    "currency": "EUR",
                }
            ]
        )
    )
    invoice = pd.DataFrame(
        [
            {
                "supplier_article_code": "FLOUR-INVOICE",
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
    assert result.loc[0, "Match_Methode"] == "description"
    assert bool(result.loc[0, "PU_Modif"]) is False
    assert bool(result.loc[0, "Blocage_Modif"]) is True
    assert bool(result.loc[0, "Ecart_Prix_Anormal"]) is False
    assert result.loc[0, "Raison_du_Blocage"] == "reference differente a verifier"
