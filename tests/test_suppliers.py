from invoice_price_checker.suppliers import detect_supplier_from_text, list_suppliers


def test_detect_supplier_from_text_finds_dds_header():
    text = "#TAI#|YSBONFACPDDS|D:\\EDI\\DDS\\extranet\\|DDS|002356|Facture|FC26002811"

    assert detect_supplier_from_text(text) == "2784"


def test_detect_supplier_from_text_returns_none_for_unknown_supplier():
    assert detect_supplier_from_text("Facture ACME inconnue") is None


def test_detect_supplier_from_text_does_not_match_product_word_fragment():
    assert detect_supplier_from_text("Facture ACME - lot de melanges d'epices") is None


def test_detect_supplier_from_text_only_uses_header():
    text = (
        "FACTURE\n"
        "www.relais-vert.com\n"
        + ("ligne de detail produit\n" * 80)
        + "CHORIZO EPICE EN U OU SARTA\n"
    )

    assert detect_supplier_from_text(text) == "254"


def test_app_supplier_list_excludes_generic_parser_when_requested():
    assert "GENERIC" not in list_suppliers(include_generic=False)
