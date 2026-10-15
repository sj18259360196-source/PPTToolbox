"""Discover MCP contracts in a clean package process, without opening manager data."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def probe(root):
    root = Path(root).resolve(strict=True)
    # Match the real package entry: only app root is added, never app/scripts.
    sys.path.insert(0, str(root))
    from toolbox_manager.mcp import MCP
    from toolbox_manager import VERSION
    from jsonschema import Draft202012Validator
    specs = MCP.specs(SimpleNamespace(manager=SimpleNamespace(root=root)))
    names = [name for name, _, _ in specs]
    if not names or len(names) != len(set(names)):
        raise ValueError('MCP discovery must return unique tool names')
    for name, _, schema in specs:
        if schema.get('type') != 'object':
            raise ValueError('MCP tool schema must have an object root: '+name)
        Draft202012Validator.check_schema(schema)
    return {'status':'passed', 'version':VERSION, 'tool_count':len(names), 'tool_names':names}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    print(json.dumps(probe(parser.parse_args().root)))
