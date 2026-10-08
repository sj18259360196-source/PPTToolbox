"""Release boundaries and real filesystem failure recovery; no Office claims."""
import hashlib
import json
from pathlib import Path

import pytest

from distribution.build_portable import source_files
from distribution.update_installed import install_new, verify
from test_installed_upgrade import installed


def test_release_omits_development_evidence_but_keeps_runtime(tmp_path):
    names = ["README.md", "AGENTS.md", "scripts/workflow.py", "assets/icon-packs/LICENSE.txt",
             "tests/test_fixture.py", "validation/user-project.json", "docs/upgrade/private.json",
             "benchmarks/observations.json", "manager_docs/USER_GUIDE.md"]
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture", encoding="utf-8")
    assert set(source_files(tmp_path, release=True)) == {
        "README.md", "scripts/workflow.py", "assets/icon-packs/LICENSE.txt", "manager_docs/USER_GUIDE.md"}
    assert "tests/test_fixture.py" in source_files(tmp_path)


def test_release_rejects_environment_files(tmp_path):
    (tmp_path / ".env.local").write_text("fixture", encoding="utf-8")
    with pytest.raises(ValueError, match="Environment"):
        source_files(tmp_path, release=True)


@pytest.mark.parametrize("name", ["location.json", "DATA/private.json", "app/data/settings.json",
                                  "app/../secret.txt", "app\\alias.txt", "app/file:stream",
                                  "app/alias./x", "FILES.json"])
def test_manifest_rejects_state_and_noncanonical_paths(installed, name):
    bundle, _, _ = installed
    manifest = json.loads((bundle / "FILES.json").read_text())
    manifest[name] = hashlib.sha256(b"fixture").hexdigest()
    (bundle / "FILES.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(bundle)


def test_fresh_runtime_failure_creates_no_installation(installed, tmp_path):
    bundle, _, _ = installed
    dest, data, projects, pointer = [tmp_path / p for p in ("fresh", "fresh-data", "projects", "pointer.json")]
    def reject(path):
        assert path == bundle
        raise RuntimeError("missing runtime dependency")
    with pytest.raises(RuntimeError, match="dependency"):
        install_new(bundle, dest, data, projects, pointer, process_check=lambda _: [], validate=reject)
    assert not any(p.exists() for p in (dest, data, projects, pointer))


def test_installed_runtime_failure_rolls_back_only_new_program(installed, tmp_path):
    bundle, _, _ = installed
    dest, data, projects = [tmp_path / p for p in ("fresh", "fresh-data", "projects")]
    dest.mkdir()
    (dest / "unins000.dat").write_bytes(b"existing installer metadata")
    def reject(path):
        if path == dest:
            (dest / "user-note.txt").write_text("keep", encoding="utf-8")
            raise RuntimeError("installed runtime rejected")
    with pytest.raises(RuntimeError, match="rejected"):
        install_new(bundle, dest, data, projects, process_check=lambda _: [], installer=True, validate=reject)
    assert {p.name for p in dest.iterdir()} == {"unins000.dat", "user-note.txt"}
    assert not data.exists() and not projects.exists()


def test_fresh_copy_failure_is_retryable(installed, tmp_path, monkeypatch):
    from distribution import update_installed
    bundle, _, _ = installed
    dest, data, projects = [tmp_path / p for p in ("fresh", "fresh-data", "projects")]
    original = update_installed.shutil.copyfileobj
    calls = []
    def fail(source, target):
        calls.append(source.name)
        if len(calls) == 3:
            target.write(b"partial")
            raise OSError("disk write failed")
        return original(source, target)
    monkeypatch.setattr(update_installed.shutil, "copyfileobj", fail)
    with pytest.raises(OSError, match="disk write"):
        install_new(bundle, dest, data, projects, process_check=lambda _: [])
    assert not dest.exists() and not data.exists()
    monkeypatch.setattr(update_installed.shutil, "copyfileobj", original)
    assert install_new(bundle, dest, data, projects, process_check=lambda _: [])["status"] == "installed"


@pytest.mark.parametrize("pointer_kind", ["inside", "existing"])
def test_pointer_is_checked_before_install_writes(installed, tmp_path, pointer_kind):
    bundle, _, _ = installed
    dest, data, projects = [tmp_path / p for p in ("fresh", "fresh-data", "projects")]
    pointer = dest / "pointer.json" if pointer_kind == "inside" else tmp_path / "pointer.json"
    if pointer_kind == "existing":
        pointer.write_bytes(b"existing identity")
    with pytest.raises(ValueError):
        install_new(bundle, dest, data, projects, pointer, process_check=lambda _: [])
    assert not dest.exists() and not data.exists()
    if pointer_kind == "existing":
        assert pointer.read_bytes() == b"existing identity"
