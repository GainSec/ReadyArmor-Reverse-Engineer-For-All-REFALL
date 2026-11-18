from ref_all_executor.cli import main


def test_list_uses_client(monkeypatch, capsys):
    class FakeAC:
        def list_automations(self):
            return {"automations": [{"id": "a1", "name": "n"}], "total": 1}

    monkeypatch.setattr("ref_all_executor.cli.AutoClient", lambda: FakeAC())
    assert main(["list"]) == 0
    assert "a1" in capsys.readouterr().out


def test_down_uses_cleanup(monkeypatch, capsys):
    calls = []

    class FakeCleanup:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"dry_run": kwargs["dry_run"], "containers": ["refall-agent-canvas"]}

    monkeypatch.setattr("ref_all_executor.cli.RefallCleanup", lambda: FakeCleanup())

    assert main(["down", "--dry-run", "--include-serena"]) == 0
    assert calls == [{
        "dry_run": True,
        "include_serena": True,
        "ports": None,
        "container_patterns": None,
        "extra_process_patterns": None,
    }]
    assert "refall-agent-canvas" in capsys.readouterr().out


def test_infra_status_uses_infra_manager(monkeypatch, capsys):
    calls = []

    class FakeInfra:
        def status(self):
            calls.append("status")
            return {"coverage": {"state": "running"}}

    monkeypatch.setattr("ref_all_executor.cli.RefallInfra", lambda: FakeInfra())

    assert main(["infra", "status"]) == 0
    assert calls == ["status"]
    assert "coverage" in capsys.readouterr().out


def test_subject_create_uses_arcticbase_client(monkeypatch, capsys):
    calls = []

    class FakeAB:
        def create_subject(self, name, **kwargs):
            calls.append((name, kwargs))
            return {"subject": name, "workbench_slug": name}

    monkeypatch.setattr("ref_all_executor.cli.ArcticBaseClient", lambda: FakeAB())

    assert main([
        "subject",
        "create",
        "alpha",
        "--source-path",
        "/projects/alpha",
        "--title",
        "Alpha",
        "--description",
        "test subject",
        "--tag",
        "web",
        "--tag",
        "api",
    ]) == 0
    assert calls == [(
        "alpha",
        {
            "source_path": "/projects/alpha",
            "title": "Alpha",
            "description": "test subject",
            "tags": ["web", "api"],
        },
    )]
    assert "workbench_slug" in capsys.readouterr().out


def test_ops_status_uses_arcticbase_client(monkeypatch, capsys):
    class FakeAB:
        def ops_status(self):
            return {"enabled": True}

    monkeypatch.setattr("ref_all_executor.cli.ArcticBaseClient", lambda: FakeAB())

    assert main(["ops", "status"]) == 0
    assert "enabled" in capsys.readouterr().out


def test_ops_command_forwards_named_command(monkeypatch, capsys):
    calls = []

    class FakeAB:
        def ops_command(self, command):
            calls.append(command)
            return {"status": "ok", "command": command}

    monkeypatch.setattr("ref_all_executor.cli.ArcticBaseClient", lambda: FakeAB())

    assert main(["ops", "command", "context", "alpha"]) == 0
    assert calls == ["context alpha"]
    assert "context alpha" in capsys.readouterr().out


def test_report_draft_command(monkeypatch, capsys):
    calls = []

    def fake_draft(workbench, subject):
        calls.append((workbench, subject))
        return {"object_id": "obj_report"}

    monkeypatch.setattr("ref_all_executor.cli.draft_report", fake_draft)

    assert main(["report", "draft", "alpha"]) == 0
    assert calls == [("alpha", "alpha")]
    assert "obj_report" in capsys.readouterr().out


def test_report_enrich_command(monkeypatch, capsys):
    calls = []

    def fake_enrich(workbench, subject):
        calls.append((workbench, subject))
        return {"enriched": {"findings": []}, "assembled": {"mode": "updated"}}

    monkeypatch.setattr("ref_all_executor.cli.enrich_workbench_report", fake_enrich)

    assert main(["report", "enrich", "alpha"]) == 0
    assert calls == [("alpha", "alpha")]
    assert "assembled" in capsys.readouterr().out


def test_doctor_command(monkeypatch, capsys):
    calls = []

    def fake_doctor(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "checks": [{"id": "arcticbase", "status": "ok"}]}

    monkeypatch.setattr("ref_all_executor.cli.doctor", fake_doctor)

    assert main(["doctor", "--subject", "alpha", "--no-network"]) == 0
    assert calls == [{"subject": "alpha", "check_network": False}]
    assert "arcticbase" in capsys.readouterr().out


def test_estimate_command(monkeypatch, capsys):
    calls = []

    def fake_estimate(subject):
        calls.append(subject)
        return {"subject": subject, "estimated_agent_tasks": 4}

    monkeypatch.setattr("ref_all_executor.cli.estimate_subject", fake_estimate)

    assert main(["estimate", "alpha"]) == 0
    assert calls == ["alpha"]
    assert "estimated_agent_tasks" in capsys.readouterr().out


def test_loop_commands_use_loop_manager(monkeypatch, capsys):
    calls = []

    class FakeLoop:
        def start(self, name):
            calls.append(("start", name))
            return {"status": "started", "subject": name}

        def update(self, name):
            calls.append(("update", name))
            return {"status": "updated", "subject": name}

        def closeout(self, name):
            calls.append(("closeout", name))
            return {"status": "closed", "subject": name}

    monkeypatch.setattr("ref_all_executor.cli.RefallLoopManager", lambda: FakeLoop())

    assert main(["loop", "start", "alpha"]) == 0
    assert main(["loop", "update", "alpha"]) == 0
    assert main(["loop", "closeout", "alpha"]) == 0
    assert calls == [("start", "alpha"), ("update", "alpha"), ("closeout", "alpha")]
    assert "closed" in capsys.readouterr().out
