from pathlib import Path

from ref_all_executor.doctor import doctor
from ref_all_executor.estimate import estimate_subject


class FakeArcticBase:
    def __init__(self) -> None:
        self.coverage_stats_return = {
            "lines_total": 100,
            "lines_covered": 25,
            "resolved_pct": 25.0,
            "symbols_total": 10,
        }

    def coverage_stats(self, slug: str) -> dict:
        assert slug == "alpha"
        return self.coverage_stats_return

    def get_source_inventory(self, slug: str) -> dict:
        assert slug == "alpha"
        return {
            "subject": "alpha",
            "files": [
                {"path": "app.py", "total_lines": 80, "size_bytes": 1200},
                {"path": "views.py", "total_lines": 20, "size_bytes": 400},
            ],
        }

    def list_pending_actions(self, slug: str, **filters) -> list[dict]:
        assert slug == "alpha"
        assert filters.get("include_terminal") is False
        return [{"id": "pa_1", "status": "open"}]

    def coverage_funnel(self, slug: str) -> dict:
        assert slug == "alpha"
        return {"findings": {"total": 2, "by_severity": {"HIGH": 1}}}

    def capabilities(self, slug: str) -> dict:
        assert slug == "alpha"
        return {"grants": [{"class": "lan_network_probe"}], "requests": []}

    def closeout_gate(self, slug: str) -> dict:
        assert slug == "alpha"
        return {"passed": False, "summary": {"pending_actions_open": 1}}


def test_doctor_reports_readiness_without_secret_values(monkeypatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("super-secret-token", encoding="utf-8")
    monkeypatch.setenv("REFALL_OPENHANDS_API_KEY_PATH", str(secret_file))
    monkeypatch.setenv("REFALL_CODEX_COMMAND", "python3")
    monkeypatch.setenv("REFALL_CLAUDE_COMMAND", "definitely-missing-claude-for-test")
    monkeypatch.setenv("REFALL_GROK_COMMAND", "definitely-missing-grok-for-test")

    result = doctor(check_network=False)

    assert result["status"] in {"ok", "warn", "fail"}
    assert "checks" in result
    rendered = str(result).lower()
    assert "super-secret-token" not in rendered
    assert any(check["id"] == "openhands_api_key" and check["status"] == "ok" for check in result["checks"])
    assert any(check["id"] == "provider.codex" for check in result["checks"])


def test_estimate_subject_uses_coverage_inventory_and_prerequisites(monkeypatch) -> None:
    monkeypatch.setenv("REFALL_CODEX_COMMAND", "python3")
    fake = FakeArcticBase()

    result = estimate_subject("alpha", arcticbase=fake, check_network=False)

    assert result["subject"] == "alpha"
    assert result["coverage"]["lines_total"] == 100
    assert result["source_inventory"]["files_total"] == 2
    assert result["estimated_open_units"] >= 1
    assert result["estimated_agent_tasks"] >= result["estimated_open_units"]
    assert result["pending_actions_open"] == 1
    assert result["dynamic_testing"] == "available"
    assert isinstance(result["missing_prerequisites"], list)
