"""Private graphics worker; heavyweight imports happen after the launch gate."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ENTRY = time.perf_counter()
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from toolbox_manager.graphics_lifecycle import atomic

def main(directory):
    directory = Path(directory)
    stages = []
    current = None
    def step(name, outcome='completed'):
        nonlocal current
        now = time.perf_counter()
        if current is not None:
            current.update(end_ms=round((now-ENTRY)*1000, 3),
                           duration_ms=round((now-ENTRY)*1000-current['start_ms'], 3), status=outcome)
        if name is not None:
            current = {'name': name, 'start_ms': round((now-ENTRY)*1000, 3), 'status': 'running'}
            stages.append(current)
        atomic(directory/'progress.json', {'step': name or current['name'], 'time': time.time(),
               'timing': {'format': 'graphics-preview-timing/1', 'worker_entry_clock': ENTRY,
                          'worker_elapsed_ms': round((now-ENTRY)*1000, 3), 'stages': stages}})
    step('launch_wait')
    limit = time.monotonic()+10
    while not (directory/'launch').exists():
        if time.monotonic() >= limit:
            step(None, 'timed_out')
            return 2
        time.sleep(.01)
    try:
        step('dependency_import')
        # Isolation ignores implicit user-site loading. Source execution still uses
        # its already-installed dependencies and interpreter-compatible repo vendors.
        # Append them explicitly, leaving bundled interpreter packages first.
        import site
        for location in (ROOT/'toolbox_manager/vendor/icons', ROOT/'toolbox_manager/vendor/graphics'):
            sys.path.append(str(location))
        if not (ROOT/'PRODUCT.json').exists():
            locations = site.getusersitepackages()
            sys.path.extend([locations] if isinstance(locations, str) else locations)
        # Prefer the interpreter's compatible binary before geometry adds legacy vendors.
        step('import_resvg')
        import resvg_py
        step('import_shapely')
        import shapely
        step('import_scipy')
        import scipy
        step('import_compiler')
        from graphics_recipe import compile_recipe
        from illustration_tools import analyze
        from graphics_preview import png, png_dimensions
        step('load_request')
        request = json.loads((directory/'request.json').read_text(encoding='utf-8'))
        previous = None
        if request.get('version'):
            from toolbox_manager.graphics import _load
            _, previous, conflicts = _load(Path(request['project']), request['version'])
            if conflicts:
                raise ValueError('Manual PowerPoint edits detected; old draft preserved')
        step('compiling')
        result = compile_recipe(request['recipe'], previous, previous['objects'] if previous else None)
        result['illustration_analysis'] = analyze(result['objects'])
        step('png_conversion')
        data = png(result)
        dimensions = png_dimensions(data)
        step('publishing')
        temp = directory/'preview.png.tmp'
        with temp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, directory/'preview.png')
        atomic(directory/'result.json', {'status': 'completed', 'compiled': result,
               'output_sha256': hashlib.sha256(data).hexdigest(), 'dimensions': dimensions,
               'published_at': time.time()})
        step('published')
        step(None)
        return 0
    except Exception as exc:
        step(None, 'failed')
        atomic(directory/'result.json', {'status': 'failed', 'error': type(exc).__name__+': '+str(exc),
               'published_at': time.time()})
        return 1

if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
