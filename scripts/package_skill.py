"""Offline reproducible-file packaging checks. ZIP filenames use standard UTF-8 flags.
No install, dependency download, or font redistribution. Does not certify Office.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from common import sha256, read_json, write_json
from release_info import check_release

IGNORE_DIRS = {'__pycache__', '.pytest_cache', '.git', '.venv', 'node_modules', '.tmp', 'dist', 'checks', '.local-backups'}
FORBIDDEN_SUFFIXES = {'.ttf', '.otf', '.ttc', '.woff', '.woff2', '.key', '.pem', '.zip'}


def file_list(root: Path) -> list[Path]:
    paths = []
    for folder,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in IGNORE_DIRS]
        for name in [*dirs,*names]:
            path=Path(folder)/name;relative=path.relative_to(root)
            if path.is_symlink():raise ValueError(f'Symlink is not distributable: {relative}')
            if not path.is_file() or path.suffix=='.pyc' or relative.as_posix()=='MANIFEST.json':continue
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:raise ValueError(f'Forbidden bundled file: {relative}')
            paths.append(path)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def validate_local_links(root: Path) -> list[str]:
    issues = []
    for path in file_list(root):
        if path.suffix != '.md':
            continue
        text = path.read_text(encoding='utf-8-sig')
        text = re.sub(r'```.*?```', '', text, flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            target = target.strip().strip('<>')
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith(('#', '//')):
                continue  # External/reference history links are not local package dependencies.
            target = unquote(target.split('#', 1)[0])
            if not target:
                continue
            actual = (path.parent / target).resolve()
            if not actual.is_relative_to(root.resolve()) or not actual.exists():
                issues.append(f'{path.relative_to(root).as_posix()} -> {target}')
    return issues


def package(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if root.name != 'ppt-reference-rebuild' or not (root / 'SKILL.md').is_file():
        raise ValueError('Expected a complete ppt-reference-rebuild directory')
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Use a new ZIP path outside the skill tree')
    if (root / 'release.json').is_file():
        check_release(root)
    problems = validate_local_links(root)
    if problems:
        raise ValueError('Broken local links: ' + '; '.join(problems))
    files = file_list(root)
    version = re.search(r'^\s+version:\s*["\']([^"\']+)', (root / 'SKILL.md').read_text(encoding='utf-8'), re.M)
    if not version:
        raise ValueError('Skill metadata.version missing')
    manifest = {'name': root.name, 'version': version[1], 'entry': 'SKILL.md',
                'manifest_scope': 'SHA256 and sizes for every packaged file except this manifest. Not a runtime/fidelity certificate.',
                'file_count_excluding_manifest': len(files),
                'files': [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size, 'sha256': sha256(p)} for p in files]}
    write_json(root / 'MANIFEST.json', manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files + [root / 'MANIFEST.json']:
            arcname = root.name + '/' + path.relative_to(root).as_posix()
            # Passing a Unicode filename to zipfile sets bit 11 for non-ASCII names.
            archive.write(path, arcname)
    try:
        return verify_archive(output)
    except Exception:
        output.unlink()  # Only the exact new archive created by this call.
        raise


def verify_archive(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist(); names = [i.filename for i in infos]
        if sum(i.file_size for i in infos) > 250 * 1024 * 1024:
            raise ValueError('Archive exceeds 250MB uncompressed limit')
        canonical = set()
        for info in infos:
            name = info.filename; parts = PurePosixPath(name).parts
            if ('\\' in name or ':' in name or name.startswith('/') or '..' in parts
                    or not parts or parts[0] != 'ppt-reference-rebuild' or name != PurePosixPath(name).as_posix()):
                raise ValueError(f'Unsafe/noncanonical archive path: {name}')
            key = unicodedata.normalize('NFC', name).casefold()
            if key in canonical:
                raise ValueError('Duplicate/case-colliding archive filename')
            canonical.add(key)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Archive symlink rejected')
            if not name.isascii() and not info.flag_bits & 0x800:
                raise ValueError(f'Non-ASCII ZIP member missing UTF-8 flag: {name}')
        if archive.testzip():
            raise ValueError('ZIP CRC failure')
        manifest_name = 'ppt-reference-rebuild/MANIFEST.json'
        manifest = json.loads(archive.read(manifest_name))
        rows = manifest.get('files', [])
        expected = [f"ppt-reference-rebuild/{r['path']}" for r in rows]
        if len(expected) != len(set(expected)) or set(names) != set(expected + [manifest_name]):
            raise ValueError('Archive file set differs from manifest')
        if manifest.get('file_count_excluding_manifest') != len(rows):
            raise ValueError('Manifest file count mismatch')
        for row, name in zip(rows, expected):
            data = archive.read(name)
            if row.get('size') != len(data) or row.get('sha256') != hashlib.sha256(data).hexdigest():
                raise ValueError(f'Manifest content mismatch: {row["path"]}')
        for required in ['使用说明.md', '给模型的启动指令.txt', 'SKILL.md', 'scripts/compare_deck.py']:
            if 'ppt-reference-rebuild/' + required not in names:
                raise ValueError('Required package entry missing: ' + required)
        with tempfile.TemporaryDirectory(prefix='skill-standard-unzip-') as tmp:
            archive.extractall(tmp)  # All names/types verified above; standard decoding, no repair fallback.
            extracted = Path(tmp) / 'ppt-reference-rebuild'
            issues = validate_local_links(extracted)
            if issues:
                raise ValueError('Broken links after standard extraction: ' + '; '.join(issues))
            packaged = file_list(extracted)
            if len(packaged) != len(rows):
                raise ValueError('Excluded or forbidden files present in archive')
    return {'status': 'passed', 'archive': archive_path.name, 'sha256': sha256(archive_path),
            'size_bytes': archive_path.stat().st_size, 'files': len(names),
            'checks': ['standard_UTF8_filenames', 'safe_unique_paths', 'ZIP_CRC', 'complete_manifest_SHA256', 'extracted_local_links'],
            'scope': 'Package integrity only; no Office, host image generation or visual acceptance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('build'); p.add_argument('root', type=Path); p.add_argument('output', type=Path)
    p = commands.add_parser('verify'); p.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        result = package(args.root, args.output) if args.command == 'build' else verify_archive(args.archive)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except Exception as exc:
        print(f'Package check failed: {exc}', file=sys.stderr); return 1

if __name__ == '__main__':
    raise SystemExit(main())
