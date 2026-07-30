from invoice_price_checker.pricing import sale_price


def test_sale_price_without_deposit():
    assert sale_price(10, 5.5, "Taux de marque 25%") == 14.15


def test_sale_price_with_deposit():
    assert sale_price(10, 5.5, "Taux de marque 25%-Consigne 2€5") == 16.65


def test_sale_price_temporary_v16_margin_aliases():
    assert sale_price(10, 5.5, "21\u202f% de marge sur cout") == sale_price(10, 5.5, "Taux de marque 21%")
    assert sale_price(10, 5.5, "25\u202f% de marge sur cout") == sale_price(10, 5.5, "Taux de marque 25%")


def test_sale_price_prefers_odoo_markup_over_legacy_mapping():
    assert sale_price(10, 5.5, "21\u202f% de marge sur cout", 21.0) == 12.77
