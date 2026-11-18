import drive_binresearch
import drive_binreview
import drive_binvalidate
import drive_research
from ref_all_executor.wishlist import format_provided_wishlist


PROVIDED = [
    {
        "kind": "tool",
        "item": "r2ghidra pdg decompiler plugin",
        "reason": "requested for binary decompilation",
        "requested_by": "bin-0-A0",
        "status": "provided",
    }
]


def test_format_provided_wishlist_lists_delivered_items():
    block = format_provided_wishlist("example-binary", PROVIDED)

    assert "DELIVERED WISHLIST ITEMS" in block
    assert "r2ghidra pdg decompiler plugin" in block
    assert "Use these before requesting duplicate tooling" in block
    assert "/wishlist?subject=example-binary&status=provided" in block


def test_format_provided_wishlist_handles_empty_state():
    block = format_provided_wishlist("example-binary", [])

    assert "No delivered wishlist items are recorded yet" in block
    assert "/wishlist?subject=example-binary&status=provided" in block


def test_all_loop_prompts_embed_provided_wishlist_items():
    prompts = [
        drive_research._objective("res-1", "example-binary", 1, provided_wishes=PROVIDED),
        drive_binresearch._objective("bin-1", "example-binary", "bin", 1, provided_wishes=PROVIDED),
        drive_binreview._objective("rev-1", "example-binary", "bin", ["f1"], provided_wishes=PROVIDED),
        drive_binvalidate._objective("val-1", "example-binary", "bin", ["f1"], provided_wishes=PROVIDED),
    ]

    for prompt in prompts:
        assert "DELIVERED WISHLIST ITEMS" in prompt
        assert "r2ghidra pdg decompiler plugin" in prompt
        assert "Do not re-request matching items" in prompt
