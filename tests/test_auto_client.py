import json
from ref_all_executor.auto_client import AutoClient


class Fake:
    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        assert headers.get("X-Session-API-Key") == "K"
        for (m, suffix), resp in self.script.items():
            if method == m and url.endswith(suffix):
                s, d = resp
                return s, json.dumps(d).encode()
        raise AssertionError(f"unexpected {method} {url}")


def client(script):
    return AutoClient(base="http://x/api/automation/v1", api_key="K", transport=Fake(script))


def test_cron_and_event_builders():
    c = client({})
    assert c.cron("0 9 * * 5", "UTC") == {"type": "cron", "schedule": "0 9 * * 5", "timezone": "UTC"}
    assert c.event("github", "push") == {"type": "event", "source": "github", "on": "push"}


def test_create_prompt_automation_posts_expected_body():
    t = Fake({("POST", "/preset/prompt"): (200, {"id": "auto_1"})})
    c = AutoClient(base="http://x/api/automation/v1", api_key="K", transport=t)
    out = c.create_prompt_automation(
        name="refall-loop", prompt="do research",
        trigger=c.cron("0 3 * * *"), model=None, keep_alive=True)
    assert out["id"] == "auto_1"
    body = json.loads(t.calls[-1][3])
    assert body["name"] == "refall-loop" and body["prompt"] == "do research"
    assert body["trigger"]["type"] == "cron" and body["keep_alive"] is True


def test_dispatch_posts_to_dispatch_path():
    t = Fake({("POST", "/auto_1/dispatch"): (200, {"run_id": "run_9", "status": "PENDING"})})
    c = AutoClient(base="http://x/api/automation/v1", api_key="K", transport=t)
    assert c.dispatch("auto_1")["run_id"] == "run_9"


def test_kv_set_and_get():
    t = Fake({("PUT", "/kv/bb"): (200, {"ok": True}), ("GET", "/kv/bb"): (200, {"value": "v"})})
    c = AutoClient(base="http://x/api/automation/v1", api_key="K", transport=t)
    c.kv_set("bb", "v")
    assert c.kv_get("bb")["value"] == "v"
