"""Product chrome is configured once in conf/settings.yaml."""

from __future__ import annotations

import json

from uns_config import PlatformConfig, resolve_conf_dir


def test_product_identity_is_loaded_from_settings():
    assert PlatformConfig.product_name
    assert PlatformConfig.product_short_name
    assert PlatformConfig.console_name == f"{PlatformConfig.product_short_name} Console"
    assert PlatformConfig.example_public_host == f"{PlatformConfig.product_short_name.lower()}.example.com"


def test_example_hosts_are_derived_from_the_configured_public_host():
    host = PlatformConfig.example_public_host
    assert PlatformConfig.example_origin() == f"https://{host}"
    assert PlatformConfig.example_subdomain("enroll") == f"enroll.{host}"
    assert PlatformConfig.example_subdomain("edge-mgmt") == f"edge-mgmt.{host}"
    assert PlatformConfig.example_subdomain("mqtt") == f"mqtt.{host}"


def test_bearer_required_detail_names_the_product_not_the_realm_id():
    # The Keycloak realm id stays `uns`. The 401 copy is user-facing chrome.
    assert PlatformConfig.product_short_name in PlatformConfig.bearer_required_detail()
    assert "uns realm" not in PlatformConfig.bearer_required_detail().lower()


def test_keycloak_display_name_matches_product_name():
    realm_path = resolve_conf_dir() / "keycloak" / "realm.json"
    doc = json.loads(realm_path.read_text(encoding="utf-8"))
    assert doc["displayName"] == PlatformConfig.product_name
    assert doc["realm"] == "uns"
