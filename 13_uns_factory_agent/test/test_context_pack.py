from uns_factory_agent.chat import PageContext
from uns_factory_agent.context_pack import build_context_pack, page_hint, resolve_paths


def test_page_hint_from_route():
    assert page_hint("/alerts") == "alarms"
    assert page_hint("/condition-monitoring") == "condition_monitoring"
    assert page_hint("/hierarchy") == "hierarchy"
    assert page_hint("/dashboard") == "plant"


def test_empty_focus_uses_access_group_roots():
    pack = build_context_pack(
        PageContext("", "", "", ""),
        is_admin=False,
        root_paths=frozenset({"AcmeWater/Site1/Filtration"}),
    )
    assert pack.default_plant == ("AcmeWater/Site1/Filtration",)
    assert resolve_paths(pack) == ("AcmeWater/Site1/Filtration",)
    assert pack.unrestricted is False


def test_focus_wins_over_roots():
    pack = build_context_pack(
        PageContext("/condition-monitoring", "AcmeWater/Site1/Filtration/P101", "", ""),
        is_admin=False,
        root_paths=frozenset({"AcmeWater/Site1"}),
    )
    assert resolve_paths(pack) == ("AcmeWater/Site1/Filtration/P101",)


def test_admin_uses_admin_roots():
    pack = build_context_pack(
        PageContext("", "", "", ""),
        is_admin=True,
        root_paths=frozenset(),
        admin_roots=("AcmeWater", "AcmeWater/Site1"),
    )
    assert pack.unrestricted is True
    assert resolve_paths(pack) == ("AcmeWater", "AcmeWater/Site1")
