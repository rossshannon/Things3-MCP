"""The osascript runner, with a stand-in process so no script reaches Things."""

import subprocess

import pytest

from things3_mcp import applescript_bridge as ab


class FakeProcess:
    def __init__(self, *, interrupt=None, returncode=0, stdout=b"", stderr=b""):
        self.interrupt = interrupt
        self.returncode = None
        self.final_returncode = returncode
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr
        self.killed = False

    def communicate(self, input=None, timeout=None):  # noqa: A002 - mirrors Popen
        if self.interrupt is not None and not self.killed:
            raise self.interrupt
        self.returncode = -9 if self.killed else self.final_returncode
        return self.stdout_bytes, self.stderr_bytes

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.returncode = -9
        return self.returncode


@pytest.fixture
def process(monkeypatch):
    def install(**kwargs):
        fake = FakeProcess(**kwargs)
        monkeypatch.setattr(ab.subprocess, "Popen", lambda *_args, **_kwargs: fake)
        return fake

    return install


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(1)])
def test_an_interrupted_caller_does_not_leave_osascript_running(process, interrupt):
    fake = process(interrupt=interrupt)
    with pytest.raises(type(interrupt)):
        ab.run_applescript('tell application "Things3" to count of lists')
    assert fake.killed and fake.returncode is not None


def test_a_timeout_kills_the_process_and_is_reported_as_unknown(process):
    fake = process(interrupt=subprocess.TimeoutExpired("osascript", 1))
    with pytest.raises(ab.AppleScriptError) as raised:
        ab.run_applescript("return 1", timeout=1)
    assert raised.value.error_code == "applescript_timeout" and raised.value.outcome == "outcome_unknown"
    assert fake.killed


def test_a_finished_process_is_left_alone(process):
    fake = process(stdout=b"3\n")
    assert ab.run_applescript("return 3") == "3"
    assert not fake.killed
