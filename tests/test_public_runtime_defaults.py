"""Portable defaults keep local tools independent of a specific deployment."""

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_defaults(monkeypatch, relative):
    name = "ref_all_executor._release_defaults" if relative.startswith("ref_all_executor/") else "_release_defaults"
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", [
    "coverage_service/project.py",
    "coverage_service/tools/report_findings.py",
    "coverage_service/tools/vendor_disclosure.py",
])
@pytest.mark.parametrize("configured", [None, "https://workbench.example.test"])
def test_publishers_use_local_default_and_preserve_override(monkeypatch, relative, configured):
    if configured is None:
        monkeypatch.delenv("REFALL_WORKBENCH_BASE", raising=False)
    else:
        monkeypatch.setenv("REFALL_WORKBENCH_BASE", configured)
    module = load_defaults(monkeypatch, relative)
    assert module.WB == (configured or "http://127.0.0.1:7673")


@pytest.mark.parametrize("relative", [
    "ref_all_executor/watchdog.py",
    "ref_all_executor/supervisor.py",
])
def test_supervision_defaults_use_checkout_and_loopback(monkeypatch, relative):
    monkeypatch.delenv("REFALL_REPO_ROOT", raising=False)
    monkeypatch.delenv("REFALL_PUBLIC_BASE_URL", raising=False)
    module = load_defaults(monkeypatch, relative)
    assert Path(module.DEFAULT_REPO_ROOT) == ROOT
    assert module.DEFAULT_BASE_URL == "http://127.0.0.1:7673"
