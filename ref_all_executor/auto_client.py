import json
import urllib.request
import urllib.error

from . import config


def _urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class AutoClient:
    def __init__(self, base=None, api_key=None, transport=None):
        self.base = base or config.AUTO_BASE
        self._key = api_key
        self.transport = transport or _urllib_transport

    @property
    def api_key(self):
        if self._key is None:
            self._key = config.session_api_key()
        return self._key

    def _req(self, method, path, body=None, ok=(200, 201)):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-Session-API-Key": self.api_key, "Content-Type": "application/json"}
        status, raw = self.transport(method, self.base + path, headers, data)
        if status not in ok and status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {}

    # trigger builders
    def cron(self, schedule, timezone="UTC"):
        return {"type": "cron", "schedule": schedule, "timezone": timezone}

    def event(self, source, on):
        return {"type": "event", "source": source, "on": on}

    # automations
    def create_prompt_automation(self, name, prompt, trigger, model=None,
                                 keep_alive=False, repos=None, timeout=None):
        body = {"name": name, "prompt": prompt, "trigger": trigger,
                "keep_alive": keep_alive}
        if model is not None:
            body["model"] = model
        if repos is not None:
            body["repos"] = repos
        if timeout is not None:
            body["timeout"] = timeout
        return self._req("POST", "/preset/prompt", body)

    def create_code_automation(self, name, tarball_path, entrypoint, trigger,
                               setup_script_path=None, model=None, keep_alive=False, timeout=None):
        body = {"name": name, "tarball_path": tarball_path, "entrypoint": entrypoint,
                "trigger": trigger, "keep_alive": keep_alive}
        for k, v in (("setup_script_path", setup_script_path), ("model", model), ("timeout", timeout)):
            if v is not None:
                body[k] = v
        return self._req("POST", "/", body)

    def upload_tarball(self, name, file_bytes, description=""):
        import uuid
        boundary = "----refall" + uuid.uuid4().hex
        parts = []
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n')
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\n{description}\r\n')
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}.tar.gz"\r\n'
                'Content-Type: application/gzip\r\n\r\n').encode()
        payload = ("".join(parts)).encode() + head + file_bytes + f"\r\n--{boundary}--\r\n".encode()
        headers = {"X-Session-API-Key": self.api_key,
                   "Content-Type": f"multipart/form-data; boundary={boundary}"}
        status, raw = self.transport("POST", self.base + "/uploads", headers, payload)
        if status >= 400:
            raise RuntimeError(f"upload -> {status}: {raw[:300]!r}")
        return json.loads(raw)

    def dispatch(self, automation_id):
        return self._req("POST", f"/{automation_id}/dispatch", {})

    def list_runs(self, automation_id):
        return self._req("GET", f"/{automation_id}/runs")

    def list_automations(self):
        return self._req("GET", "")

    def get_automation(self, automation_id):
        return self._req("GET", f"/{automation_id}")

    def delete_automation(self, automation_id):
        self._req("DELETE", f"/{automation_id}", ok=(200, 204))

    # KV blackboard
    def kv_set(self, key, value):
        return self._req("PUT", f"/kv/{key}", {"value": value})

    def kv_get(self, key):
        return self._req("GET", f"/kv/{key}")

    def kv_lpush(self, key, value):
        return self._req("POST", f"/kv/{key}/lpush", {"value": value})

    def kv_rpop(self, key):
        return self._req("POST", f"/kv/{key}/rpop", {})
