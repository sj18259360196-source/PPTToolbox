"""Build a pinned Windows embedded runtime from official Python/PyPI artifacts."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(output, cache):
    output, cache = Path(output).resolve(), Path(cache).resolve()
    if output.exists():
        raise ValueError('Use a new runtime directory; existing releases are preserved')
    config = json.loads((ROOT/'distribution/runtime-lock.json').read_text('utf-8'))
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / config['filename']
    if not archive.is_file():
        url = f'https://www.python.org/ftp/python/{config["version"]}/{config["filename"]}'
        with urlopen(url, timeout=120) as response, archive.open('xb') as stream:
            while data := response.read(1024*1024):
                stream.write(data)
    if sha(archive) != config['sha256']:
        raise ValueError('Official Python runtime archive hash differs from runtime-lock.json')
    output.mkdir(parents=True)
    runtime = output/'runtime'
    runtime.mkdir()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or ':' in entry.filename:
                raise ValueError('Unsafe runtime archive path')
            source.extract(entry, runtime)
    target = runtime/'Lib/site-packages'
    args = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
            '--only-binary=:all:', '--no-binary=proxy_tools', '--no-deps', '--no-build-isolation',
            '--platform', 'win_amd64', '--python-version', config['python_minor'],
            '--implementation', 'cp', '--abi', config['abi'], '--require-hashes',
            '--target', str(target), '-r', str(ROOT/'distribution/requirements-release.lock'),
            '--cache-dir', str(cache/'pip')]
    wheels = cache/'wheels'
    if wheels.is_dir():
        args += ['--no-index', '--find-links', str(wheels)]
    subprocess.run(args, check=True, env={**os.environ,'SOURCE_DATE_EPOCH':'1791417600'})
    minor = config['python_minor'].replace('.', '')
    (runtime/f'python{minor}._pth').write_text(f'python{minor}.zip\n.\nLib/site-packages\nimport site\n', encoding='utf-8')
    # Embedded Python does not automatically add a target directory's .pth files.
    (target/'sitecustomize.py').write_text(
        'import site\nfrom pathlib import Path\nsite.addsitedir(str(Path(__file__).parent))\n', encoding='utf-8')
    probe = subprocess.run([str(runtime/'python.exe'), '-B', '-c',
        'import json,sys,importlib.metadata as m; import win32api,pythoncom,webview,cryptography,pypdfium2; '
        'print(json.dumps({"python":sys.version,"distributions":sorted(['
        '{"name":d.metadata["Name"],"version":d.version} for d in m.distributions()],key=lambda x:x["name"])}))'],
        check=True, capture_output=True, text=True, encoding='utf-8')
    (output/'DEPENDENCIES.json').write_text(probe.stdout, encoding='utf-8')
    inventory={p.relative_to(output).as_posix():sha(p) for p in runtime.rglob('*') if p.is_file()}
    if any('/fitz/' in n or '/pymupdf/' in n for n in inventory):
        raise ValueError('Public runtime must not contain PyMuPDF')
    (output/'FILES.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    return {'runtime':str(output),'python':config['version'],'files':len(inventory)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.cache),indent=2))
