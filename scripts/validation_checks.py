"""Collect independent contract failures without inventing observations or repairs."""
from __future__ import annotations


class ValidationIssues(ValueError):
    code = 'invalid_submission'

    def __init__(self, rows, not_checked=()):
        self.diagnostics = rows
        self.not_checked = list(not_checked)
        super().__init__('; '.join(row['message'] for row in rows))


class Checks:
    def __init__(self):
        self.errors = []
        self.not_checked = set()

    def add(self, message, path, rule, object_id=None, next_action='correct_result'):
        self.errors.append({'path': path, 'constraint': 'semantic', 'rule': rule,
                            'object_id': object_id, 'message': str(message)[:1200],
                            'next_action': next_action,
                            'repair': ('Use rebuild_revise to update the affected plan before changing this decision.'
                                       if next_action == 'revise' else
                                       'Correct this field on the current task; preserve accepted work and actual observations.')})

    def run(self, callback, path, rule, object_id=None, next_action='correct_result'):
        try:
            return callback()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            if getattr(exc, 'code', None) == 'permission_denied':
                raise
            nested = getattr(exc, 'diagnostics', None)
            self.not_checked.update(getattr(exc,'not_checked',[]))
            if nested:
                for row in nested:
                    child = row.get('path', '')
                    # Child validators use local JSON pointers, rebased at the call site.
                    self.errors.append({**row, 'path': path+child,
                                        'object_id': row.get('object_id') or object_id})
            else:
                self.add(str(exc), path, rule, object_id, next_action)

    def finish(self, not_checked=()):
        if self.errors:
            raise ValidationIssues(self.errors, sorted(self.not_checked | set(not_checked)))


def prefixed(exc, prefix='/result'):
    rows = getattr(exc, 'diagnostics', None)
    if rows:
        return [{**row, 'path': prefix+row.get('path', '')} for row in rows]
    checks = Checks()
    checks.add(str(exc), prefix, 'task_contract')
    return checks.errors
