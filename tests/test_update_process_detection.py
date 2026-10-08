import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path
import pytest
from distribution import install_local

@pytest.mark.skipif(os.name != "nt", reason="Windows process inventory")
@pytest.mark.parametrize("spaced", [False, True])
def test_update_waiter_does_not_block_but_live_controllers_do(monkeypatch, tmp_path, spaced):
    root = tmp_path / ("Tool box" if spaced else "Toolbox")
    runner = subprocess.list2cmdline([str(root / "runtime/python.exe"), "-B", "-I", "-X", "utf8", str(root / "app/distribution/update_runner.py")]) + " --installer candidate.exe"
    rows = [
        {"ProcessId": 910001, "CommandLine": runner},
        {"ProcessId": 910002, "CommandLine": str(root / "runtime/python.exe") + " manager.py desktop"},
        {"ProcessId": 910003, "CommandLine": str(root / "runtime/python.exe") + ' -c "print(123)" # update_runner.py'},
        {"ProcessId": 910004, "CommandLine": runner.replace(" -B -I -X utf8 ", " -c ")},
        {"ProcessId": 910005, "CommandLine": str(root / "runtime/python.exe") + " agent_bridge.py"},
    ]
    monkeypatch.setattr(install_local.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(rows)))
    assert install_local.controllers([root]) == [910002, 910003, 910004, 910005]
