"""Private bootstrap for an already-authorized registered Python tool.

No policy is granted here. The managed caller owns authorization and logging;
this process establishes only the active package's import path and argv.
"""
from __future__ import annotations
import json
from pathlib import Path
import runpy
import sys


def main():
    if len(sys.argv) < 4 or sys.argv[3] != '--':
        raise ValueError('Expected package root, registered Python entry, --, arguments')
    root = Path(sys.argv[1]).resolve(strict=True)
    relative = sys.argv[2]
    entry = (root / relative).resolve(strict=True)
    if not entry.is_relative_to(root) or not entry.is_file():
        raise ValueError('Python entry must stay inside the active package')
    registry = json.loads((root/'toolbox/registry.json').read_text(encoding='utf-8-sig'))
    allowed = {str(row.get('entry')) for row in registry.get('tools', []) if row.get('kind') == 'python'}
    if registry.get('single_entry'):
        allowed.add(str(registry['single_entry']))
    if relative not in allowed:
        raise ValueError('Expected a registered Python entry')
    sys.path[:0] = [str(root/'scripts'), str(root)]
    sys.argv = [str(entry), *sys.argv[4:]]
    runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
