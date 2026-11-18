import drive_binresearch
import drive_binreview
import drive_research


def test_binary_research_prompt_tells_agents_to_read_provided_wishlist_items():
    prompt = drive_binresearch._objective("agent-1", "example-binary", "bin", 1)

    assert "/wishlist?subject=example-binary" in prompt
    assert "provided" in prompt
    assert "pdg" in prompt
    assert "Evidence handoff" in prompt
    assert "REF-All report spec" in prompt
    assert '"repro_hints"' in prompt


def test_source_research_prompt_tells_agents_to_read_provided_wishlist_items():
    prompt = drive_research._objective("agent-1", "some-subject", 1)

    assert "/wishlist?subject=some-subject" in prompt
    assert "provided" in prompt
    assert "Evidence handoff" in prompt
    assert "REF-All report spec" in prompt
    assert '"repro_hints"' in prompt


def test_binary_review_prompt_hands_off_concrete_validation_targets():
    prompt = drive_binreview._objective("reviewer-1", "example-binary", "bin", ["finding-1"])

    assert "Report/evidence handoff" in prompt
    assert "REF-All report spec" in prompt
    assert "repro_hints" in prompt
    assert "collapsed rejected appendix" in prompt
