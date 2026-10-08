"""Detached update runner using the installed Python, with persistent diagnostics."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def run(installer, expected_sha256, destination, version, result_path, log_path):
    exit_code = 1
    error = ''
    try:
        from distribution.install_local import no_reparse
        for path in (installer, destination, result_path, log_path):
            no_reparse(path)
        with installer.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_sha256:
                raise ValueError('Installer hash mismatch')
        # The owner requested installation. Show Inno Setup and its error dialogs.
        # Only the helper has no console; the installer keeps a normal window.
        process = subprocess.Popen([str(installer), '/NORESTART',
                                    '/DIR=' + str(destination), '/LOG=' + str(log_path)])
        exit_code = process.wait()
    except Exception as exc:
        error = str(exc)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write('\nUpdate runner failed: ' + error + '\n')
    finally:
        result_path.write_text(json.dumps({'version': version, 'exit_code': exit_code,
                                          'error': error, 'finished_at': time.time()}), encoding='utf-8')
    return exit_code


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser()
    for name in ('installer', 'destination', 'result-path', 'log-path'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.installer, args.expected_sha256, args.destination,
                         args.version, args.result_path, args.log_path))
