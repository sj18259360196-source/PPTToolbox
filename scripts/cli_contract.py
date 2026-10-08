"""Opt-in read-only CLI help checks. Never execute documentation task arguments."""
from __future__ import annotations
import ast
import json
import re
import shlex
import subprocess
import sys
from runtime_env import child_environment, python_tool_argv


def declared_options(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    return {arg.value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'add_argument'
            for arg in node.args if isinstance(arg, ast.Constant)
            and isinstance(arg.value, str) and arg.value.startswith('--')} | {'--help'}


def check_contracts(root, rows):
    issues, cache = [], {}
    by_id = {r['id']: r for r in rows}

    def help_for(entry, prefix):
        key = (entry, *prefix)
        if key not in cache:
            path = (root/entry).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError('Invalid CLI entry: ' + entry)
            argv=(python_tool_argv(sys.executable,root,entry,[*prefix,'--help'])
                  if (root/'toolbox/registry.json').is_file() else [sys.executable,str(path),*prefix,'--help'])
            result = subprocess.run(argv,
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='strict', timeout=20, env=child_environment(), shell=False)
            if result.returncode:
                raise ValueError('CLI help failed: ' + ' '.join(key) + '\n' + result.stderr[:400])
            cache[key] = result.stdout
        return cache[key]

    for row in rows:
        if row['kind'] != 'python':
            continue
        try:
            help_text = help_for(row['entry'], row.get('prefix', []))
            declared = set(re.findall(r'--[a-zA-Z][a-zA-Z0-9_-]*', help_text)) | declared_options(root/row['entry'])
            advertised = set(re.findall(r'--[a-zA-Z][a-zA-Z0-9_-]*', json.dumps(row.get('inputs', ''), ensure_ascii=False)))
            for flag in sorted(advertised - declared):
                issues.append(row['id'] + ': undocumented CLI option in registry: ' + flag)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            issues.append(row['id'] + ': ' + str(exc))

    # Check real fenced command lines, including managed examples. Values and paths
    # are never run; only the fixed entry and its subcommand receive --help.
    for doc in [root/'SKILL.md', root/'toolbox/COMMANDS.md', root/'toolbox/README.md']:
        fenced = False
        for number, line in enumerate(doc.read_text(encoding='utf-8').splitlines(), 1):
            if line.startswith('```'):
                fenced = not fenced
                continue
            if not fenced or not line.startswith('python '):
                continue
            try:
                words = shlex.split(line)
                script = words[1].replace('\\', '/').split('/')[-1]
                args = words[2:]
                if script == 'manager.py':
                    if args[:1] != ['execute']:
                        continue
                    tid = args[args.index('--tool')+1]
                    args = args[args.index('--')+1:]
                    if tid.startswith('workflow.'):
                        entry, prefix = 'toolbox.py', [tid.removeprefix('workflow.')]
                    else:
                        row = by_id[tid]
                        if row['kind'] != 'python':
                            continue
                        entry, prefix = row['entry'], row.get('prefix', [])
                elif script == 'toolbox.py':
                    if args[:2] == ['tools', 'run']:
                        row = by_id[args[2]]
                        if row['kind'] != 'python':
                            continue
                        entry, prefix = row['entry'], row.get('prefix', [])
                        args = args[4:] if args[3:4] == ['--'] else args[3:]
                    elif args[:1] in (['ops'], ['bench']):
                        entry = 'scripts/direct_ops.py' if args[0] == 'ops' else 'scripts/benchmark.py'
                        prefix, args = [], args[1:]
                    else:
                        entry, prefix = 'toolbox.py', []
                else:
                    continue
                # No values are forwarded. Resolve only fixed subcommands from help.
                help_text = help_for(entry, prefix)
                while args and not args[0].startswith('-'):
                    choices = set()
                    for group in re.findall(r'\{([\w,-]+)\}', help_text):
                        choices.update(group.split(','))
                    if args[0] not in choices:
                        if choices and not args[0].startswith('<'):
                            raise ValueError('Unknown example subcommand or choice: ' + args[0])
                        break
                    prefix = [*prefix, args[0]]
                    args = args[1:]
                    help_text = help_for(entry, prefix)
                advertised = {x.split('=')[0] for x in args if x.startswith('--') and x != '--'}
                accepted = set(re.findall(r'--[a-zA-Z][a-zA-Z0-9_-]*', help_text))
                for flag in sorted(advertised - accepted):
                    issues.append(f'{doc.relative_to(root)}:{number}: unsupported example option {flag}')
            except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
                issues.append(f'{doc.relative_to(root)}:{number}: {exc}')
    return issues
