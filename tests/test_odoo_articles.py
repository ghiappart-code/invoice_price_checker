import pytest

from invoice_price_checker.odoo_articles import config_from_mapping, supplierinfo_partner_field, _search_read_all


class FakeOdooModel:
    def __init__(self, rows, fields=None):
        self.rows = rows
        self.fields = fields or {}
        self.search_calls = []
        self.read_calls = []

    def fields_get(self, fields=None):
        return self.fields

    def search(self, domain):
        self.search_calls.append({"domain": domain})
        return [row["id"] for row in self.rows]

    def read(self, ids, fields):
        self.read_calls.append({"ids": ids, "fields": fields})
        return [row for row in self.rows if row["id"] in ids]


def test_config_from_mapping_accepts_optional_timeout_and_batch_size():
    config = config_from_mapping(
        {
            "url": "odoo.example.org",
            "database": "db",
            "username": "user",
            "password": "password",
            "timeout": 420,
            "batch_size": 250,
        }
    )

    assert config.timeout == 420
    assert config.batch_size == 250


def test_config_from_mapping_defaults_timeout_and_batch_size():
    config = config_from_mapping(
        {
            "url": "odoo.example.org",
            "database": "db",
            "username": "user",
            "password": "password",
        }
    )

    assert config.timeout == 300
    assert config.batch_size == 500


def test_search_read_all_fetches_all_batches():
    rows = [{"id": index} for index in range(5)]
    model = FakeOdooModel(rows)

    result = _search_read_all(model, [("active", "=", True)], ["id"], batch_size=2)

    assert result == rows
    assert model.search_calls == [{"domain": [("active", "=", True)]}]
    assert [call["ids"] for call in model.read_calls] == [[0, 1], [2, 3], [4]]


def test_search_read_all_handles_exact_batch_boundary():
    rows = [{"id": index} for index in range(4)]
    model = FakeOdooModel(rows)

    result = _search_read_all(model, [], ["id"], batch_size=2)

    assert result == rows
    assert [call["ids"] for call in model.read_calls] == [[0, 1], [2, 3]]


def test_search_read_all_rejects_invalid_batch_size():
    with pytest.raises(ValueError, match="batch_size"):
        _search_read_all(FakeOdooModel([]), [], ["id"], batch_size=0)


def test_supplierinfo_partner_field_prefers_v16_partner_id():
    model = FakeOdooModel([], fields={"name": {}, "partner_id": {}})

    assert supplierinfo_partner_field(model) == "partner_id"


def test_supplierinfo_partner_field_supports_v12_name():
    model = FakeOdooModel([], fields={"name": {}})

    assert supplierinfo_partner_field(model) == "name"
