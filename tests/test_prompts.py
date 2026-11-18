from ref_all_executor.prompts import build_prompt


def test_prompt_embeds_pipeline_and_writeback():
    p = build_prompt("the /projects/bra binary", "https://workbench.example.test", "ref-all")
    for needle in ("intake", "classify", "verify", "tier", "ref-all", "/api/workbenches/ref-all/objects"):
        assert needle.lower() in p.lower()
    assert "the /projects/bra binary" in p
