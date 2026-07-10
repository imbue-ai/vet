import os
import subprocess
import time
from pathlib import Path

import pytest

from vet.imbue_core.agents.agent_api.transport import _terminate_process_group


class TestTerminateProcessGroup:
    def test_terminates_direct_process(self) -> None:
        popen = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            assert popen.poll() is None
            _terminate_process_group(popen)
            assert popen.poll() is not None
        finally:
            if popen.poll() is None:
                popen.kill()
                popen.wait()

    def test_terminates_detached_grandchild_in_same_process_group(self, tmp_path: Path) -> None:
        # Mirrors kiro-cli's own behavior: it forks a detached helper process that stays
        # in the same process group as the process we spawned but is not our direct child,
        # so popen.terminate()/wait() alone would never reach it.
        pidfile = tmp_path / "grandchild.pid"
        script = f"(sleep 30 & echo $! > {pidfile}) ; sleep 30"
        popen = subprocess.Popen(["bash", "-c", script], start_new_session=True)
        try:
            deadline = time.time() + 5
            while not pidfile.exists() and time.time() < deadline:
                time.sleep(0.05)
            assert pidfile.exists(), "grandchild process never started"
            grandchild_pid = int(pidfile.read_text().strip())

            # Confirm the grandchild is alive before teardown.
            os.kill(grandchild_pid, 0)

            _terminate_process_group(popen)

            time.sleep(0.2)
            with pytest.raises(ProcessLookupError):
                os.kill(grandchild_pid, 0)
        finally:
            if popen.poll() is None:
                popen.kill()
                popen.wait()

    def test_already_exited_process_is_a_no_op(self) -> None:
        popen = subprocess.Popen(["true"], start_new_session=True)
        popen.wait()
        # Should not raise even though the process (and its group) is already gone.
        _terminate_process_group(popen)
