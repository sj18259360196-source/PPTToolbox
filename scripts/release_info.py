"""One product release identity; protocol and saved project formats stay independent."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
SKILL_VERSION = re.compile(r'^(\s+version:\s*)["\']([^"\']+)["\']\s*$', re.M)


def read_release(root: Path = ROOT) -> dict:
    value = json.loads((Path(root) / "release.json").read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or value.get("product") != "PPT Toolbox"
            or not isinstance(value.get("version"), str)
            or not re.fullmatch(VERSION_PATTERN, value["version"])):
        raise ValueError("release.json requires PPT Toolbox and a numeric release version")
    return {"product": value["product"], "version": value["version"]}


def check_release(root: Path = ROOT) -> dict:
    root = Path(root)
    release = read_release(root)
    match = SKILL_VERSION.search((root / "SKILL.md").read_text(encoding="utf-8"))
    if not match or match[2] != release["version"]:
        raise ValueError("SKILL.md release metadata is stale; run scripts/release_info.py sync")
    plugin = Path(root) / '.codex-plugin/plugin.json'
    if plugin.is_file() and json.loads(plugin.read_text(encoding='utf-8'))['version'] != release['version']:
        raise ValueError('Plugin release metadata is stale; run scripts/release_info.py sync')
    manager = root / 'MANAGER.json'
    if manager.is_file():
        metadata = json.loads(manager.read_text('utf-8'))
        if metadata['version'] != release['version'] or metadata['bundled_core']['version'] != release['version']:
            raise ValueError('MANAGER.json release metadata is stale; run scripts/release_info.py sync')
    return release


def sync_release(root: Path = ROOT) -> dict:
    root = Path(root)
    release = read_release(root)
    path = root / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if len(SKILL_VERSION.findall(text)) != 1:
        raise ValueError("Expected one Skill metadata version")
    updated = SKILL_VERSION.sub(lambda m: m[1] + '"' + release["version"] + '"', text)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    plugin = root / '.codex-plugin/plugin.json'
    if plugin.is_file():
        data = json.loads(plugin.read_text(encoding='utf-8'))
        if data.get('version') != release['version']:
            data['version'] = release['version']
            plugin.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manager = root / 'MANAGER.json'
    if manager.is_file():
        data = json.loads(manager.read_text('utf-8'))
        data.update(version=release['version'], python_minimum='3.11', online_update_service=True)
        data['bundled_core']['version'] = release['version']
        manager.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return check_release(root)


VERSION = read_release()["version"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "sync"), default="check", nargs="?")
    args = parser.parse_args()
    print(json.dumps((sync_release if args.command == "sync" else check_release)(), ensure_ascii=False))
