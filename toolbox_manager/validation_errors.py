"""Structured schema errors without copying private result text or task tokens."""
from jsonschema.exceptions import best_match


def relevant_errors(error):
    """Expand only a uniquely identified variant; never report other variants' fields."""
    if error.validator in {'oneOf','anyOf'} and isinstance(error.instance,dict):
        branches=error.schema[error.validator]
        selected=[]
        for field in ('action','recipe','kind'):
            if field in error.instance:
                selected=[i for i,branch in enumerate(branches)
                          if branch.get('properties',{}).get(field,{}).get('const')==error.instance[field]]
            elif field=='action' and any('action' in b.get('properties',{}) for b in branches):
                selected=[i for i,branch in enumerate(branches) if 'action' not in branch.get('properties',{})]
            if len(selected)==1:
                children=[c for c in error.context if c.schema_path and c.schema_path[0]==selected[0]]
                if children:
                    for child in children:yield from relevant_errors(child)
                    return
        # Full/local review batches share additional_reviews. Select by the entire
        # envelope shape only when exactly one variant can contain these fields.
        selected=[i for i,branch in enumerate(branches) if branch.get('properties')
                  and set(error.instance)<=set(branch['properties'])]
        if len(selected)==1:
            children=[c for c in error.context if c.schema_path and c.schema_path[0]==selected[0]]
            if children:
                for child in children:yield from relevant_errors(child)
                return
    yield best_match([error])


def diagnostics(errors, prefix='', limit=30):
    rows = []
    for error in (leaf for original in errors for leaf in relevant_errors(original)):
        path = '/'.join(str(x).replace('~','~0').replace('/','~1') for x in error.absolute_path)
        row = {'path':prefix + ('/'+path if path else ''), 'constraint':str(error.validator),
               'rule':'schema.'+str(error.validator), 'object_id':None, 'next_action':'correct_result',
               'actual_type':type(error.instance).__name__,
               'repair':'Correct this field using the current task template; do not replay accepted work.'}
        if error.validator == 'required' and isinstance(error.instance, dict):
            row['missing'] = [k for k in error.validator_value if k not in error.instance]
        elif error.validator in {'enum','const','type','pattern','minimum','maximum','minItems','maxItems'}:
            row['expected'] = error.validator_value
        elif error.validator == 'additionalProperties':
            allowed = set(error.schema.get('properties', {}))
            row['unexpected'] = sorted(set(error.instance)-allowed)[:20]
        row['message'] = 'Field does not satisfy '+str(error.validator)
        rows.append(row)
        if limit is not None and len(rows) == limit:break
    return rows


class ContractError(ValueError):
    def __init__(self, message, errors, prefix=''):
        super().__init__(message)
        self.code = 'invalid_submission' if prefix == '/result' else 'invalid_arguments'
        self.diagnostics = diagnostics(errors, prefix, limit=None)
        self.not_checked = ['semantic_checks'] if prefix == '/result' else []
