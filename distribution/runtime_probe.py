"""Read-only package-local import and native binary checks, with no Office or DB."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


def require_local(path, bundle):
    resolved = Path(path).resolve()
    roots = [bundle / "runtime", bundle / "app"]
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError("Runtime dependency is outside this package: " + str(resolved))
    return resolved


def probe(bundle):
    bundle = Path(bundle).resolve()
    require_local(sys.executable, bundle)
    sys.path[:0] = [str(bundle / "app"), str(bundle / "app/scripts")]
    # The normal geometry entry registers the shipped optional vendor directories.
    importlib.import_module("graphics_geometry")
    names = ("webview", "pystray", "toolbox_manager.service", "toolbox_manager.mcp",
             "pptx", "PIL", "lxml", "jsonschema", "numpy", "scipy",
             "scipy.optimize", "scipy.ndimage", "resvg_py", "shapely", "cryptography", "pypdfium2")
    modules = {name: importlib.import_module(name) for name in names}
    origins = {name: str(require_local(module.__file__, bundle))
               for name, module in modules.items()}
    np = modules["numpy"]
    fit = modules["scipy.optimize"].least_squares(lambda x: x - 2, [0.0])
    filtered = modules["scipy.ndimage"].gaussian_filter(np.ones((3, 3)), .5)
    payload = modules["resvg_py"].svg_to_bytes(
        svg_string='<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
                   '<rect width="8" height="8" fill="#dd2244"/></svg>',
        skip_system_fonts=True)
    from PIL import Image
    from shapely.geometry import Polygon
    with Image.open(io.BytesIO(payload)) as image:
        rendered = image.size == (8, 8) and image.convert("RGB").getpixel((4, 4)) == (221, 34, 68)
    checks = {"scipy_fit": bool(fit.success and np.allclose(fit.x, [2.0], atol=1e-7)),
              "scipy_filter": bool(np.allclose(filtered, 1.0)),
              "svg_render": rendered,
              "geometry": Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]).area == 4.0}
    entrypoints = {}
    from scripts.runtime_env import python_tool_argv
    registry = json.loads((bundle/'app/toolbox/registry.json').read_text(encoding='utf-8'))
    python_tools = [row for row in registry['tools'] if row.get('kind') == 'python']
    from toolbox_manager.service import WORKFLOWS
    from toolbox_manager.contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
    python_tools += [{'id':'workflow.'+cmd, 'entry':registry['single_entry'], 'prefix':[cmd]}
                     for cmd in dict.fromkeys([*WORKFLOWS, *LOCAL_COMMANDS, *REQUEST_COMMANDS])]
    def check_entry(row):
        began = time.monotonic()
        argv = python_tool_argv(sys.executable, bundle/'app', row['entry'], [*row.get('prefix', []), '--help'], isolated=True)
        try:
            run = subprocess.run(argv, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding='utf-8', timeout=20,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            passed = run.returncode == 0 and 'usage:' in run.stdout.lower()
            return row['id'], {'passed':passed, 'entry':row['entry'], 'prefix':row.get('prefix', []),
                'returncode':run.returncode, 'seconds':round(time.monotonic()-began,3),
                'error':run.stderr[-1200:] if not passed else ''}
        except subprocess.TimeoutExpired:
            return row['id'], {'passed':False, 'entry':row['entry'], 'error':'help_timeout'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        entrypoints = dict(pool.map(check_entry, python_tools))
    checks['native_tool_entrypoints'] = bool(entrypoints) and all(row['passed'] for row in entrypoints.values())
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    key.public_key().verify(key.sign(b'PPTToolbox runtime probe'), b'PPTToolbox runtime probe')
    checks['update_signature'] = True
    pdf = modules['pypdfium2'].PdfDocument.new()
    try:
        page = pdf.new_page(8, 8)
        bitmap = page.render(scale=1)
        checks['pdf_preview'] = bitmap.to_pil().size == (8, 8)
        bitmap.close(); page.close()
    finally:
        pdf.close()
    if not all(checks.values()):
        failed={k:v for k,v in entrypoints.items() if not v['passed']}
        raise ValueError('Packaged runtime checks failed: '+json.dumps({'checks':checks,'entries':failed}))
    return {"status": "passed", "bundle": str(bundle), "checks": checks,
            "origins": origins, "entrypoints": entrypoints,
            "versions": {name: importlib.metadata.version(name)
                         for name in ("numpy", "scipy", "resvg-py", "shapely")},
            "scope": "Package-local imports and tiny native computations; no Office, UI, DB or host acceptance."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.bundle), ensure_ascii=False))
