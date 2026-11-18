from coverage_service.ids import unit_id


def test_id_is_stable_and_type_sensitive():
    a = unit_id("bra", "file", "head/x.py", None, None)
    b = unit_id("bra", "file", "head/x.py", None, None)
    c = unit_id("bra", "symbol", "head/x.py", 1, 5, "f")
    assert a == b and a != c and len(a) == 40
