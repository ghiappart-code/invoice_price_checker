from invoice_price_checker.suppliers import detect_supplier_from_text, list_suppliers
from invoice_price_checker.suppliers.ecodis import EcodisParser


def test_detect_supplier_from_text_finds_dds_header():
    text = "#TAI#|YSBONFACPDDS|D:\\EDI\\DDS\\extranet\\|DDS|002356|Facture|FC26002811"

    assert detect_supplier_from_text(text) == "2784"


def test_detect_supplier_from_text_finds_ecodis_header():
    text = "SDEB ECODIS\nRUE DE GALILEE\nEmail : facture@ecodis.info\nSIRET : 42921631000046"

    assert detect_supplier_from_text(text) == "227"


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


def test_ecodis_line_uses_net_price_without_temporary_discount():
    parser = EcodisParser()
    row = parser._row_from_items(
        "AH900",
        [
            (65.1, 282.1, 88.7, 293.1, "AH900"),
            (134.7, 282.1, 150.2, 293.1, "1.00"),
            (162.5, 282.1, 167.0, 293.1, "9"),
            (178.4, 282.1, 194.7, 293.1, "EAN"),
            (201.4, 282.1, 257.7, 293.1, "3760138831507"),
            (372.8, 282.1, 388.3, 293.1, "2.20"),
            (415.5, 282.1, 436.5, 293.1, "-5.5%"),
            (472.1, 282.1, 487.6, 293.1, "2.08"),
            (518.7, 282.1, 538.5, 293.1, "18.71"),
            (547.5, 282.1, 563.0, 293.1, "5.50"),
            (178.4, 290.7, 220.7, 301.7, "Bicarbonate"),
            (223.0, 290.7, 231.8, 301.7, "de"),
            (234.1, 290.7, 255.3, 301.7, "soude"),
            (257.6, 290.7, 295.6, 301.7, "alimentaire"),
            (297.9, 290.7, 311.0, 301.7, "500"),
            (313.3, 290.7, 317.7, 301.7, "g"),
            (320.0, 290.7, 335.0, 301.7, "tube"),
            (178.4, 308.0, 204.4, 319.0, "Remise"),
            (206.7, 308.0, 241.1, 319.0, "Successif"),
        ],
        1,
    )

    assert row["quantity"] == 9
    assert row["unit_price"] == 2.08
    assert row["gross_unit_price"] == 2.20
    assert row["remise_temp"] == 0
    assert row["remise_detail"] == ""
