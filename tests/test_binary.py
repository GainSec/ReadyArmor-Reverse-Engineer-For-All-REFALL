from coverage_service.binary import dangerous_present, build_investigations, DANGEROUS


def test_dangerous_present_handles_leading_underscore():
    # Mach-O imports carry a leading underscore (LIEF); catalog keys don't.
    d = dangerous_present(["_memcpy", "_ippReadIO", "CFArrayGetCount", "_system", "_totally_safe"])
    assert d["_memcpy"] == ("mem-corruption", 1)
    assert d["_ippReadIO"] == ("ipp-parse", 1)
    assert d["_system"] == ("command-exec", 1)
    assert "CFArrayGetCount" not in d and "_totally_safe" not in d


def test_build_investigations_clusters_by_function_and_prioritizes():
    callers = {
        "memcpy": [{"fcn": "sym.func.100017608", "addr": "0x17694"}],
        "calloc": [{"fcn": "sym.func.100017608", "addr": "0x17650"}],   # same fcn -> one investigation
        "fprintf": [{"fcn": "sym.func.100022a6c", "addr": "0x22a80"}],
    }
    invs = build_investigations("example-binary", "bin/Server", callers)
    assert len(invs) == 2                                   # two distinct functions
    top = invs[0]
    assert top["priority"] == 1                             # memcpy (risk 1) beats fprintf (risk 3)
    assert top["kind"] == "mem-corruption"
    assert top["target_files"] == ["bin/Server"]
    assert "memcpy" in top["question"] and "calloc" in top["question"]
    assert "pdc" in top["question"]                         # tells the researcher how to decompile
    assert invs[1]["priority"] == 3                         # fprintf function sorts last


def test_catalog_covers_ipp_http_surface():
    for fn in ("ippReadIO", "httpReadRequest", "memcpy", "posix_spawn", "sscanf"):
        assert fn in DANGEROUS
