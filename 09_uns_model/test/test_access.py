from uns_model.access import covers

ROOT = "AcmeWater/Site1/Filtration"


def test_covers_the_root_a_child_and_a_grandchild():
    assert covers(ROOT, ROOT)
    assert covers(f"{ROOT}/Train1", ROOT)
    assert covers(f"{ROOT}/Train1/F101", ROOT)


def test_does_not_cover_a_sibling():
    assert not covers("AcmeWater/Site1/RawWater", ROOT)
    assert not covers("AcmeWater/Site1/RawWater/Train1", ROOT)


def test_does_not_cover_a_prefix_without_a_slash_boundary():
    assert not covers("AcmeWater/Site1/FiltrationEast", ROOT)
    assert not covers(f"{ROOT}East", ROOT)
