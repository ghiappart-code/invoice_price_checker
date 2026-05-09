from invoice_price_checker.pricing import sale_price


def test_sale_price_without_deposit():
    assert sale_price(10, 5.5, "Taux de marque 25%") == 14.15


def test_sale_price_with_deposit():
    assert sale_price(10, 5.5, "Taux de marque 25%-Consigne 2€5") == 16.65
