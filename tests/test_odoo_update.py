import pandas as pd

from invoice_price_checker.odoo_update import _relation_or_scalar_id, prepare_odoo_update_rows


def test_prepare_odoo_update_rows_excludes_unchanged_prices():
    rows = pd.DataFrame(
        [
            {
                "Article_Ref_EAN": "1",
                "ID_Fournisseur": "254",
                "Fact_PU_unitaire": 2.5,
                "Fact_PU_Net_GZ": 7.5,
                "prix_de_vente": 3.4,
                "Match_Fact_DB": True,
                "PU_Modif": True,
                "Ecart_Prix_Anormal": False,
                "Blocage_Modif": False,
            },
            {
                "Article_Ref_EAN": "2",
                "ID_Fournisseur": "254",
                "Fact_PU_unitaire": 2.0,
                "Fact_PU_Net_GZ": 6.0,
                "prix_de_vente": 3.0,
                "Match_Fact_DB": True,
                "PU_Modif": False,
                "Ecart_Prix_Anormal": False,
                "Blocage_Modif": False,
            },
        ]
    )

    result = prepare_odoo_update_rows(rows)

    assert len(result) == 1
    assert "ID Externe" not in result.columns
    assert result.loc[0, "Coût"] == 2.5
    assert result.loc[0, "Fournisseurs/Prix"] == 7.5


def test_relation_or_scalar_id_handles_many2one_and_scalar_values():
    assert _relation_or_scalar_id([42, "Product Template"]) == 42
    assert _relation_or_scalar_id("42") == 42
    assert _relation_or_scalar_id(None) is None
