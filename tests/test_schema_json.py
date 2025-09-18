import json
from pathlib import Path


def test_schema_json_is_valid_and_includes_app_inventory():
    path = Path("src/database/schema.json")
    data = json.loads(path.read_text())
    assert "app_inventory" in data
    assert isinstance(data["app_inventory"], list)
    assert "product_name" in data["app_inventory"]
    assert "vip_items" in data
