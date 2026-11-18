import json


def test_record_usage_fetches_stats_before_delete(tmp_path):
    from ref_all_executor import usage

    class FakeOH:
        def __init__(self):
            self.calls = []

        def conversation_info(self, cid):
            self.calls.append(("info", cid))
            return {
                "id": cid,
                "execution_status": "finished",
                "stats": {"usage_to_metrics": {"default": {"model_name": "gpt-5.5"}}},
            }

        def delete(self, cid):
            self.calls.append(("delete", cid))

    oh = FakeOH()
    usage.record_and_delete(
        oh,
        "cid-1",
        {"agent_id": "bin-0-A0", "subject": "example-binary", "driver": "binresearch"},
        log_path=tmp_path / "usage.jsonl",
    )

    assert oh.calls == [("info", "cid-1"), ("delete", "cid-1")]
    row = json.loads((tmp_path / "usage.jsonl").read_text())
    assert row["agent_id"] == "bin-0-A0"
    assert row["conversation_id"] == "cid-1"
    assert row["stats"]["usage_to_metrics"]["default"]["model_name"] == "gpt-5.5"


def test_record_usage_deletes_even_if_stats_fetch_fails(tmp_path):
    from ref_all_executor import usage

    class FakeOH:
        def __init__(self):
            self.deleted = []

        def conversation_info(self, cid):
            raise RuntimeError("gone")

        def delete(self, cid):
            self.deleted.append(cid)

    oh = FakeOH()
    usage.record_and_delete(oh, "cid-1", {"agent_id": "a"}, log_path=tmp_path / "usage.jsonl")

    assert oh.deleted == ["cid-1"]
    row = json.loads((tmp_path / "usage.jsonl").read_text())
    assert row["usage_error"] == "gone"
