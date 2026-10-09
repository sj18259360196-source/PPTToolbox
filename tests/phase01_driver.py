"""Explicit local host verification client. Never authors or approves task results."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from toolbox_manager.service import Manager


def call(data, name, arguments, evidence):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    ]
    env = dict(__import__("os").environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run([sys.executable, str(ROOT/"manager.py"), "--data-dir", str(data), "mcp"],
                          input="\n".join(json.dumps(r, ensure_ascii=False) for r in requests)+"\n",
                          text=True, encoding="utf-8", capture_output=True, timeout=420, env=env)
    folder = evidence/"rpc"; folder.mkdir(parents=True, exist_ok=True)
    path = folder/(uuid.uuid4().hex+".json")
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    path.write_text(json.dumps({"requests": requests, "responses": rows, "stderr": proc.stderr,
                               "exit_code": proc.returncode}, ensure_ascii=False, indent=2), encoding="utf-8")
    if proc.returncode:
        raise RuntimeError("MCP process failed; see "+str(path))
    result = rows[-1]["result"]
    return result.get("structuredContent", json.loads(result["content"][0]["text"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", type=Path, required=True)
    commands = p.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup")
    setup.add_argument("--reference", type=Path, required=True)
    invoke = commands.add_parser("call")
    invoke.add_argument("--name", choices=["rebuild_"+n for n in ("start", "next", "submit", "status", "revise", "finish")], required=True)
    invoke.add_argument("--arguments", type=Path, required=True)
    a = p.parse_args()
    evidence = a.evidence.resolve()
    if evidence.is_relative_to(ROOT) or not evidence.parent.is_dir():
        raise ValueError("Use an explicit evidence directory outside the application")
    if a.command == "setup":
        if evidence.exists():
            raise ValueError("Use a new isolated evidence directory")
        inputs = evidence/"inputs"; inputs.mkdir(parents=True)
        reference = inputs/"reference.png"
        shutil.copyfile(a.reference, reference)
        m = Manager(evidence/"manager", root=ROOT, home=evidence/"home")
        m.authorize_project(evidence/"project", [inputs])
        m.save_settings({"revision": 0, "values": {"agent_execution_enabled": True}})
        result = {"project": str(evidence/"project"), "reference": str(reference),
                  "data": str(m.data), "scope": "Isolated test configuration only; user settings untouched"}
    else:
        result = call(evidence/"manager", a.name, json.loads(a.arguments.read_text(encoding="utf-8-sig")), evidence)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    main()
