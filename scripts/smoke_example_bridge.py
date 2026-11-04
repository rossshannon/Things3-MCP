"""Exercise only the signed synthetic adapter using fresh private state."""

import argparse
import hashlib
import http.client
import json
import os
import plistlib
import signal
import socket
import subprocess
import time
from pathlib import Path


def main():
    """Verify a synthetic signed bundle using an explicitly fresh state directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    app = args.app.resolve()
    runtime = args.runtime.absolute()
    manifest = json.loads((app / "Contents/Resources/build-manifest.json").read_text())
    assert manifest["entrypoint"] == "clawbridge.demo:main", "Only synthetic adapters may run"
    assert not any("apple-events" in key for key in manifest["entitlements"])
    assert not any("network" in key for key in manifest["entitlements"])
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    executable = app / "Contents/MacOS" / info["CFBundleExecutable"]
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True)
    signed = subprocess.run(["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app)], check=True, capture_output=True)
    assert plistlib.loads(signed.stdout) == manifest["entitlements"]
    for name in ("bridge.sock", "bridge.token", "demo-state.json", "operations"):
        assert not (runtime / name).exists(), f"Refusing existing state: {name}"
    endpoint = runtime / "bridge.sock"
    token_file = runtime / "bridge.token"
    assert len(os.fsencode(endpoint)) < 104
    child_env = {key: value for key, value in os.environ.items() if not key.startswith(("THINGS", "CLAWBRIDGE", "PYTHON"))}
    process = subprocess.Popen([str(executable), "--socket", str(endpoint), "--token-file", str(token_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env, start_new_session=True)
    observations = {"build_id": manifest["build_id"], "source_revision": manifest["source_revision"], "source_dirty": manifest["source_dirty"], "sandbox": manifest["sandbox"]}
    token = ""

    def request(method, path, payload=None, credential=None):
        connection = http.client.HTTPConnection("localhost", timeout=40)
        connection.sock = socket.socket(socket.AF_UNIX)
        connection.sock.settimeout(40)
        connection.sock.connect(str(endpoint))
        headers = {"Authorization": f"Bearer {token if credential is None else credential}", "X-Correlation-ID": "synthetic-frozen-smoke"}
        connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        response = connection.getresponse()
        status, body = response.status, json.loads(response.read())
        connection.close()
        return status, body

    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Synthetic app exited with {process.returncode}")
            try:
                token = token_file.read_text().strip()
                status, envelope = request("GET", "/status")
                if status == 200:
                    break
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("Synthetic app did not become ready")
            time.sleep(0.05)
        identity = envelope["data"]
        assert identity["pid"] == process.pid
        assert identity["executable"] == str(executable)
        assert identity["identity"] == {key: manifest[key] for key in ("bundle_id", "version", "build_id")}
        assert request("GET", "/status", credential="wrong")[0] == 401
        assert request("GET", "/health", credential="")[1]["data"]["running"] is True
        assert request("GET", "/demo/read")[1]["data"] == {"value": 0}
        canary = 'synthetic-private-payload-☘-quoted-"'
        assert request("POST", "/demo/echo", {"text": canary})[1]["data"] == {"text": canary}
        status, mutation = request("POST", "/demo/increment", {"amount": 7})
        assert status == 200 and mutation["outcome"] == "succeeded"
        assert mutation["data"]["value"] == 7
        assert request("GET", "/demo/read")[1]["data"]["value"] == 7
        operation = request("GET", f"/operations/{mutation['operation_id']}")[1]["data"]
        assert operation["outcome"] == "succeeded" and "payload" not in operation
        records = request("GET", "/operations?correlation_id=synthetic-frozen-smoke")[1]["data"]
        assert len(records) == 1 and records[0]["operation_id"] == mutation["operation_id"]
        for path in (endpoint, token_file, runtime / "demo-state.json", runtime / "operations" / f"{mutation['operation_id']}.json"):
            assert path.stat().st_mode & 0o777 == 0o600
        observations.update(passed=True, operation_id=mutation["operation_id"], instance_id=identity["instance_id"], executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    except BaseException as error:
        observations.update(passed=False, error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        observations.update(exit_code=process.returncode, stdout=stdout.decode(errors="replace"), stderr=stderr.decode(errors="replace"))
        if b"synthetic-private-payload-" in stdout + stderr:
            observations["passed"] = False
            observations["error"] = "Synthetic request payload appeared in process output"
        if token and token.encode() in stdout + stderr:
            observations["passed"] = False
            observations["error"] = "Token appeared in process output"
            observations.pop("stdout", None)
            observations.pop("stderr", None)
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(observations, indent=2) + "\n")
        os.chmod(args.result, 0o600)
    assert observations["passed"]
    print(json.dumps({key: observations[key] for key in ("passed", "build_id", "source_revision", "sandbox")}))


if __name__ == "__main__":
    main()
