from invoice_price_checker.suppliers import detect_supplier_from_text, list_suppliers
from invoice_price_checker.suppliers.agidra import AgidraParser
from invoice_price_checker.suppliers.ecodis import EcodisParser
from invoice_price_checker.suppliers.ekibio import EKIBIO_ENERGY_TRANSPORT_SURCHARGE_RATE, EkibioParser
from invoice_price_checker.suppliers.halle_bio_occitanie import HalleBioOccitanieParser
from invoice_price_checker.suppliers.relais_vert import RelaisVertParser


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


def test_ecodis_proposes_unit_ratio_override_when_net_price_already_matches_line_amount():
    parser = EcodisParser()
    row = parser._row_from_items(
        "BV7151",
        [
            (125.0, 100.0, 140.0, 110.0, "1"),
            (155.0, 100.0, 170.0, 110.0, "3"),
            (178.0, 100.0, 210.0, 110.0, "Sac"),
            (212.0, 100.0, 245.0, 110.0, "cabas"),
            (247.0, 100.0, 290.0, 110.0, "assorti"),
            (360.0, 100.0, 390.0, 110.0, "10,90"),
            (448.0, 100.0, 490.0, 110.0, "10,30"),
            (510.0, 100.0, 542.0, 110.0, "30,90"),
            (542.0, 100.0, 568.0, 110.0, "20"),
        ],
        2,
    )

    assert row["quantity"] == 3
    assert row["unit_price"] == 10.30
    assert row["line_amount"] == 30.90
    assert row["supplier_unit_ratio_override_when_abnormal"] == 1.0


def test_relais_vert_proposes_unit_ratio_override_when_net_price_already_matches_line_amount():
    parser = RelaisVertParser()
    row = parser._row_from_items(
        "39345",
        [
            (368.0, 338.5, 376.8, 349.5, "25"),
            (397.8, 338.5, 417.9, 349.5, "12,49"),
            (439.0, 338.7, 446.7, 348.3, "12"),
            (487.8, 338.7, 507.9, 349.8, "10,99"),
            (517.2, 338.5, 541.7, 349.5, "274,75"),
            (89.1, 338.7, 118.8, 348.3, "AMANDE"),
            (120.7, 338.7, 171.7, 348.3, "DECORTIQUEE"),
            (175.6, 338.7, 198.0, 348.3, "(25KG)"),
            (199.8, 338.7, 233.2, 348.3, "ESPAGNE"),
        ],
        1,
        0.4,
    )

    assert row["quantity"] == 25
    assert row["unit_price"] == 10.99
    assert row["line_amount"] == 274.75
    assert row["supplier_unit_ratio_override_when_abnormal"] == 1.0


def test_halle_bio_occitanie_reads_product_line_above_relais_vert_default_area():
    class Page:
        def get_text(self, mode):
            assert mode == "words"
            return [
                (40.0, 267.0, 62.0, 276.0, "E980"),
                (90.0, 267.0, 130.0, 276.0, "CORDONS"),
                (132.0, 267.0, 166.0, 276.0, "BLEUS"),
                (168.0, 267.0, 205.0, 276.0, "(200G)"),
                (207.0, 267.0, 235.0, 276.0, "ELIBIO"),
                (237.0, 267.0, 255.0, 276.0, "-"),
                (90.0, 276.0, 130.0, 285.0, "EPICIERS"),
                (132.0, 276.0, 150.0, 285.0, "BIO"),
                (365.0, 267.0, 376.0, 276.0, "2"),
                (395.0, 267.0, 410.0, 276.0, "5,00"),
                (485.0, 267.0, 500.0, 276.0, "4,50"),
                (518.0, 267.0, 540.0, 276.0, "9,00"),
            ]

    assert RelaisVertParser()._parse_page(Page(), 1, 0.0) == []

    lines = HalleBioOccitanieParser()._parse_page(Page(), 1, 0.0)

    assert len(lines) == 1
    assert lines[0]["supplier_article_code"] == "E980"
    assert lines[0]["description"] == "CORDONS BLEUS (200G) ELIBIO - EPICIERS BIO"
    assert lines[0]["quantity"] == 2
    assert lines[0]["unit_price"] == 4.50


def test_ekibio_detects_energy_transport_surcharge():
    parser = EkibioParser()

    assert parser._energy_transport_surcharge_rate("CONTRIBUTION ENERGIE TRANSPORT") == EKIBIO_ENERGY_TRANSPORT_SURCHARGE_RATE
    assert parser._energy_transport_surcharge_rate("Facture sans contribution") == 0.0


def test_ekibio_line_applies_energy_transport_surcharge_rate_to_adjusted_price():
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
        EKIBIO_ENERGY_TRANSPORT_SURCHARGE_RATE,
    )

    assert row["unit_price"] == 1.65
    assert row["adjusted_unit_price"] == 1.65 * (1 + EKIBIO_ENERGY_TRANSPORT_SURCHARGE_RATE)
    assert row["fuel_surcharge_pct"] == EKIBIO_ENERGY_TRANSPORT_SURCHARGE_RATE * 100
    assert row["supplier_unit_ratio_override_when_abnormal"] == 1.0
    assert row["remise_temp"] == 1


def test_agidra_recognizes_invoice_and_credit_numbers():
    parser = AgidraParser()

    assert parser._find_invoice_number("Facture FCAG92606-00749") == "FCAG92606-00749"
    assert parser._find_invoice_number("Facture FWAG92607-00011") == "FWAG92607-00011"


def test_agidra_reads_expected_line_count():
    parser = AgidraParser()

    assert parser._find_expected_line_count("Nb Lignes :  69") == 69
    assert parser._find_expected_line_count("aucun total") is None


def test_agidra_stops_product_at_large_vertical_gap():
    parser = AgidraParser()
    lines = [
        [(156.0, 700.0, 190.0, 708.0, "FARINE")],
        [(156.0, 709.0, 180.0, 717.0, "1KG")],
        [(198.0, 731.0, 230.0, 739.0, "produits")],
    ]

    assert [word[4] for word in parser._product_words(lines, "fc_brand")] == ["FARINE", "1KG"]


def test_agidra_keeps_words_from_top_and_bottom_of_continuation_pages():
    parser = AgidraParser()
    words = [
        (115.0, 44.0, 135.0, 52.0, "179005", 0, 0, 0),
        (156.0, 44.5, 190.0, 52.5, "MOUTARDE", 0, 0, 0),
        (483.0, 44.0, 495.0, 52.0, "1,20", 0, 0, 0),
        (115.0, 796.0, 135.0, 804.0, "177603", 0, 0, 0),
        (156.0, 796.5, 200.0, 804.5, "VINAIGRETTE", 0, 0, 0),
        (483.0, 796.0, 495.0, 804.0, "1,09", 0, 0, 0),
    ]

    lines = parser._group_words_by_line(words)

    assert [parser._reference_from_items(line) for line in lines] == ["179005", "177603"]


def test_agidra_separates_description_from_fc_brand():
    parser = AgidraParser()
    block = [
        (115.0, 300.0, 135.0, 308.0, "1570181"),
        (156.0, 300.5, 190.0, 308.5, "MELANGE"),
        (192.0, 300.5, 225.0, 308.5, "LYON"),
        (270.0, 300.0, 300.0, 308.0, "Agidra"),
        (302.0, 300.0, 318.0, 308.0, "IDS"),
        (376.0, 300.0, 384.0, 308.0, "18"),
        (411.0, 300.0, 423.0, 308.0, "2,74"),
        (483.0, 300.0, 495.0, 308.0, "2,74"),
        (524.0, 300.0, 540.0, 308.0, "49,32"),
    ]

    row = parser._row_from_block("1570181", block, 1, "fc_brand")

    assert row["description"] == "MELANGE LYON"
    assert row["brand"] == "Agidra IDS"


def test_agidra_separates_description_from_fw_customs_columns():
    parser = AgidraParser()
    block = [
        (115.0, 300.0, 135.0, 308.0, "809000"),
        (156.0, 300.5, 190.0, 308.5, "BOISSON"),
        (192.0, 300.5, 230.0, 308.5, "VEGETALE"),
        (294.0, 300.0, 303.0, 308.0, "IT"),
        (312.0, 300.0, 340.0, 308.0, "22029915"),
        (376.0, 300.0, 384.0, 308.0, "12"),
        (411.0, 300.0, 423.0, 308.0, "1,68"),
        (483.0, 300.0, 495.0, 308.0, "1,68"),
        (524.0, 300.0, 540.0, 308.0, "20,16"),
    ]

    row = parser._row_from_block("809000", block, 1, "fw_customs")

    assert row["description"] == "BOISSON VEGETALE"
    assert row["origin"] == "IT"
    assert row["customs_reference"] == "22029915"
