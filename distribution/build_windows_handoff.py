"""Package a verified Windows release and a compact, offline development copy."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from distribution.build_portable import sha, source_files
from distribution.update_installed import verify

DEV_DISTRIBUTIONS = ("pytest", "PyYAML", "pluggy", "packaging", "iniconfig",
                     "colorama", "Pygments")
PRIVATE_NAMES = {"auth.json", "credentials.json", "cookies.json",
                 "storage-state.json", "storagestate.json", ".npmrc", ".envrc"}
OMIT_DIRS = {"validation", "data", "logs", "runs", ".dev-runtime"}
SHARED_PREFIXES = ("assets/", "toolbox_manager/vendor/")


def safe_name(name):
    path = PurePosixPath(name)
    return (bool(path.parts) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and ":" not in name and str(path) == name)


def source_allowed(name):
    path = PurePosixPath(name)
    if not safe_name(name):
        raise ValueError("Unsafe source path: " + name)
    if any(part in OMIT_DIRS for part in path.parts) or name == "AGENTS.md":
        return False
    if (path.name.lower() in PRIVATE_NAMES or path.name.startswith(".env")
            or path.suffix.lower() in {".pfx", ".p12", ".key", ".pem", ".db",
                                       ".sqlite", ".sqlite3", ".log"}):
        raise ValueError("Private/local file cannot be packaged: " + name)
    return True


def development_dependencies():
    files, versions = {}, {}
    for name in DEV_DISTRIBUTIONS:
        dist = importlib.metadata.distribution(name)
        site = Path(dist.locate_file("")).resolve()
        versions[name] = dist.version
        for entry in dist.files or ():
            relative = str(entry).replace("\\", "/")
            if (not safe_name(relative) or "__pycache__" in entry.parts
                    or relative.endswith(".pyc")):
                continue
            path = Path(dist.locate_file(entry))
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(site):
                raise ValueError("Linked developer dependency: " + relative)
            files["DevSupport/site-packages/" + relative] = path
    return files, versions


def build(bundle, output):
    bundle, output = bundle.resolve(), output.resolve()
    if not output.is_relative_to(ROOT / "dist") or output.suffix != ".zip":
        raise ValueError("Use a new ZIP inside this project's dist directory")
    if output.exists():
        raise ValueError("Existing archives are never overwritten")
    release = verify(bundle)
    product = json.loads((bundle / "app/PRODUCT.json").read_text(encoding="utf-8"))
    entries = {"Run/" + name: bundle / name for name in release}
    entries["Run/FILES.json"] = bundle / "FILES.json"
    source = source_files(ROOT)
    source = {name: value for name, value in source.items() if source_allowed(name)}
    shared = {}
    for name, expected in source.items():
        released = release.get("app/" + name)
        if released is not None and released != expected:
            raise ValueError("Source differs from release; build a fresh release first: " + name)
        if name.startswith(SHARED_PREFIXES) and released == expected:
            shared[name] = expected
        else:
            entries["Source/" + name] = ROOT / name
    deps, versions = development_dependencies()
    entries.update(deps)
    templates = ROOT / "distribution/windows-handoff"
    for name in ("Develop.cmd", "dev.py", "README.txt"):
        entries[name] = templates / name
    entries["Source/AGENTS.md"] = templates / "AGENTS.md"
    generated = {
        "DevSupport/shared-source.json": json.dumps(shared, indent=2).encode(),
        "DevSupport/dependencies.json": json.dumps(versions, indent=2).encode(),
        "DevSupport/source-files.json": json.dumps(source, indent=2).encode(),
    }
    prefix = output.stem
    hashes, total = {}, 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(entries.items()):
            data = path.read_bytes()
            expected = (release.get(name[4:]) if name.startswith("Run/")
                        else source.get(name[7:]) if name.startswith("Source/") else None)
            value = hashlib.sha256(data).hexdigest()
            if expected and value != expected:
                raise ValueError("File changed while packaging: " + name)
            archive.writestr(prefix + "/" + name, data)
            hashes[name] = value
            total += len(data)
        for name, data in generated.items():
            archive.writestr(prefix + "/" + name, data)
            hashes[name] = hashlib.sha256(data).hexdigest()
            total += len(data)
        manifest = {
            "version": product["version"], "platform": "Windows x64",
            "files": hashes, "shared_source_files": len(shared),
            "source_snapshot": "Current working tree, including uncommitted code",
            "omitted": ["Git history", "user projects", "management databases",
                        "credentials", "local caches", "historical validation outputs"],
            "external_requirements": product["external_requirements"],
        }
        archive.writestr(prefix + "/TRANSFER.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError("Archive CRC verification failed")
    result = {"archive": str(output), "version": product["version"],
              "archive_bytes": output.stat().st_size, "archive_sha256": sha(output),
              "uncompressed_bytes": total, "files": len(hashes) + 1,
              "shared_source_files": len(shared), "development_dependencies": versions}
    output.with_suffix(".receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.bundle, args.output), indent=2))
