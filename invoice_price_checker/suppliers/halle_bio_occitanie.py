from __future__ import annotations

from invoice_price_checker.suppliers.relais_vert import RelaisVertParser


class HalleBioOccitanieParser(RelaisVertParser):
    supplier_code = "3329"
    display_name = "HALLE BIO OCCITANIE"
    PRODUCT_AREA_Y_MIN = 260
