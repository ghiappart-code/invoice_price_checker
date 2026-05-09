import pandas as pd

from invoice_price_checker.odoo_update import prepare_odoo_update_rows


def test_prepare_odoo_update_rows_excludes_unchanged_prices():
    rows = pd.DataFrame(
        [
            {
                "ID_externe": "changed",
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
                "ID_externe": "unchanged",
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
    assert result.loc[0, "ID Externe"] == "changed"
    assert result.loc[0, "Coût"] == 2.5
    assert result.loc[0, "Fournisseurs/Prix"] == 7.5
