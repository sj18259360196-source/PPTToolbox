"""Build from the inherited working tree and a hash-verified local runtime donor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from package_skill import file_list
from release_info import VERSION as PRODUCT_VERSION, check_release



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root, *, release=False):
    # Validation receipts can contain local database backups and project paths.
    # They are development evidence, never application distribution assets.
    excluded = {".git", ".tmp", "dist", "checks", "__pycache__", ".pytest_cache", "node_modules", ".venv", ".local-backups", ".playwright-cli", "ui-demo-20260928", "ui-prototype-0.9"}
    result = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in excluded]
        if release:
            dirs[:] = [name for name in dirs if name not in {"validation", "benchmarks", "tests", "docs"}]
        for name in dirs:
            directory = Path(folder) / name
            if directory.is_symlink() or getattr(directory.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked directory is not distributable: " + str(directory))
        for name in names:
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            if name.endswith(".pyc") or relative == "MANIFEST.json":
                continue
            if release and (name == "AGENTS.md" or name.startswith(".env")):
                if name.startswith(".env"):
                    raise ValueError("Environment file is not distributable: " + relative)
                continue
            if path.is_symlink() or path.suffix.lower() in {".key", ".pem", ".zip", ".sqlite", ".sqlite3", ".db"}:
                raise ValueError("Non-distributable file: " + relative)
            result[relative] = sha(path)
    return result


def digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def release_contract(root):
    from types import SimpleNamespace
    from toolbox_manager import VERSION as manager_version
    from toolbox_manager.mcp import MCP
    from common import VERSION as core_version
    release = check_release(root)
    if (root / 'PUBLIC_DISTRIBUTION.json').is_file():
        from distribution.public_source import audit
        public_audit = audit(root)
        if public_audit['issues']:
            raise ValueError('Public source audit failed: ' + json.dumps(public_audit['issues']))
    if manager_version != release['version'] or core_version != release['version']:
        raise ValueError('Loaded component code differs from the product release')
    specs=MCP.specs(SimpleNamespace(manager=SimpleNamespace(root=root)))
    names=[name for name,_,schema in specs]
    if len(names)!=len(set(names)) or any(schema.get('type')!='object' for _,_,schema in specs):
        raise ValueError('MCP discovery requires unique names and object-root schemas')
    return {'manager_version':manager_version,'core_version':core_version,
            'mcp_tool_count':len(names),'mcp_tool_names':names}


def runtime_files(donor):
    manifest = json.loads((donor / "FILES.json").read_text(encoding="utf-8-sig"))
    if isinstance(manifest, dict):
        manifest = [{"path": path, "sha256": value} for path, value in manifest.items()]
    expected = {row["path"]: row["sha256"] for row in manifest if row["path"].startswith("runtime/")
                and "__pycache__" not in row["path"].split("/") and not row["path"].endswith(".pyc")}
    if not expected or "runtime/python.exe" not in expected or "runtime/pythonw.exe" not in expected:
        raise ValueError("Missing verified Python runtime")
    for name, value in expected.items():
        path = (donor / name).resolve()
        if not path.is_relative_to((donor / "runtime").resolve()) or not path.is_file() or sha(path) != value:
            raise ValueError("Runtime identity mismatch: " + name)
    return expected


def build(root, donor, output):
    root, donor, output = root.resolve(), donor.resolve(), output.resolve()
    public_distribution = (root / 'PUBLIC_DISTRIBUTION.json').is_file()
    if not output.is_relative_to(root / "dist") or output == root / "dist":
        raise ValueError("Release must be a new child of this project's dist directory")
    archive = output.parent / (output.name + ".zip")
    if output.exists() or archive.exists():
        raise ValueError("Existing release is preserved; do not overwrite")
    release = check_release(root)
    contract = release_contract(root)
    files = source_files(root, release=True)
    runtime = runtime_files(donor)
    output.mkdir(parents=True)
    for name in files:
        target = output / "app" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
        if sha(target) != files[name]:
            raise ValueError("Source changed while building: " + name)
    for name in runtime:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(donor / name, target)
    shutil.copyfile(donor / "DEPENDENCIES.json", output / "DEPENDENCIES.json")
    shutil.copyfile(root / "distribution/portable_entry.py", output / "portable.py")
    shutil.copyfile(root / "distribution/agent_bridge.py", output / "agent_bridge.py")
    shutil.copyfile(root / "distribution/QUICKSTART.txt", output / "打开说明.txt")
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    scratch = root / '.tmp/codex'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=output.name+'-launcher-', dir=scratch) as temporary:
        metadata = Path(temporary) / 'ReleaseVersion.cs'
        metadata.write_text('using System.Reflection;\n'
            f'[assembly: AssemblyVersion("{release["version"]}.0")]\n'
            f'[assembly: AssemblyFileVersion("{release["version"]}.0")]\n'
            f'[assembly: AssemblyInformationalVersion("{release["version"]}")]\n', encoding='utf-8')
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/reference:System.Windows.Forms.dll",
                        "/out:" + str(output / "PPTToolbox.exe"), str(root / "distribution/Launcher.cs"),
                        str(metadata)], check=True)
    product = {**release, **contract, 'public_distribution': public_distribution,
               "source_sha256": digest(files),
               "source_files": files, "runtime_files": runtime,
               "runtime_donor_manifest_sha256": sha(donor / "FILES.json"),
               "external_requirements": ["Windows x64", "Microsoft Edge WebView2", "PowerPoint for Office operations"],
               "office_validation": "not_run", "data_directory": "data"}
    (output / "app/PRODUCT.json").write_text(json.dumps(product, indent=2), encoding="utf-8")
    app_files = [{"path": p.relative_to(output/"app").as_posix(), "size": p.stat().st_size, "sha256": sha(p)}
                 for p in sorted((output/"app").rglob("*")) if p.is_file()]
    (output / "app/MANIFEST.json").write_text(json.dumps({
        "name": "ppt-reference-rebuild", "version": release['version'], "entry": "SKILL.md",
        "files": app_files}, indent=2), encoding="utf-8")
    # Relative paths are resolved after extraction, not on the build machine.
    mcp = {"note": "Replace <extracted-package> with the actual extraction path. Do not duplicate an existing server.",
           "mcpServers": {"ppt_toolbox_manager": {
               "command": "<extracted-package>/runtime/python.exe",
               "args": ["-B", "<extracted-package>/portable.py", "mcp"]}}}
    (output / "mcp-template.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
    contents = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob("*") if p.is_file()}
    (output / "FILES.json").write_text(json.dumps(contents, indent=2), encoding="utf-8")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob("*")):
            if p.is_file():
                z.write(p, output.name + "/" + p.relative_to(output).as_posix())
    result = {"output": str(output), "archive": str(archive), "archive_sha256": sha(archive),
              "source_sha256": digest(files), "product_version": PRODUCT_VERSION,
              "runtime_file_count": len(runtime), "file_count": len(contents)}
    (output.parent / (output.name + ".receipt.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(ROOT, args.donor, args.output), indent=2))
