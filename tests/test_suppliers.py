from invoice_price_checker.suppliers import detect_supplier_from_text, list_suppliers
from invoice_price_checker.suppliers.ecodis import EcodisParser
from invoice_price_checker.suppliers.ekibio import EKIBIO_ENERGY_TRANSPORT_SURCHARGE, EkibioParser


def test_detect_supplier_from_text_finds_dds_header():
    text = "#TAI#|YSBONFACPDDS|D:\\EDI\\DDS\\extranet\\|DDS|002356|Facture|FC26002811"

    assert detect_supplier_from_text(text) == "2784"


def test_detect_supplier_from_text_finds_ecodis_header():
    text = "SDEB ECODIS\nRUE DE GALILEE\nEmail : facture@ecodis.info\nSIRET : 42921631000046"

    assert detect_supplier_from_text(text) == "227"


def test_detect_supplier_from_text_finds_agidra_legal_footer():
    text = (
        "FACTURE\n"
        + ("ligne produit sans nom fournisseur\n" * 80)
        + "Siège social : SNC AGIDRA - SIRET : 96350030100030 - webagidra@agidra.com"
    )

    assert detect_supplier_from_text(text) == "329"


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


def test_ekibio_detects_energy_transport_surcharge():
    parser = EkibioParser()

    assert parser._energy_transport_surcharge("CONTRIBUTION ENERGIE TRANSPORT") == EKIBIO_ENERGY_TRANSPORT_SURCHARGE
    assert parser._energy_transport_surcharge("Facture sans contribution") == 0.0


def test_ekibio_line_adds_energy_transport_surcharge_to_adjusted_price():
    parser = EkibioParser()
    row = parser._row_from_items(
        [
            (20.0, 100.0, 45.0, 110.0, "010154"),
            (55.0, 100.0, 120.0, 110.0, "BOR"),
            (122.0, 100.0, 180.0, 110.0, "SAUCE"),
            (545.0, 100.0, 570.0, 110.0, "15"),
            (600.0, 100.0, 625.0, 110.0, "1.95"),
            (638.0, 100.0, 670.0, 110.0, "a:11%"),
            (672.0, 100.0, 704.0, 110.0, "b:5%"),
            (705.0, 100.0, 730.0, 110.0, "1.65"),
            (760.0, 100.0, 790.0, 110.0, "24.75"),
        ],
        1,
        EKIBIO_ENERGY_TRANSPORT_SURCHARGE,
    )

    assert row["unit_price"] == 1.65
    assert row["adjusted_unit_price"] == 1.65 + EKIBIO_ENERGY_TRANSPORT_SURCHARGE
    assert row["fuel_surcharge_amount"] == EKIBIO_ENERGY_TRANSPORT_SURCHARGE
    assert row["remise_temp"] == 1
