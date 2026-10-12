"""Review grouping from explicit ownership; never infer components from proximity."""
if __package__:
    from .common import walk_objects
else:
    from common import walk_objects

COMPONENT_SCHEMA={'type':'object','additionalProperties':False,'required':['id','object_ids'],
    'properties':{'id':{'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'},
                  'object_ids':{'type':'array','minItems':1,'uniqueItems':True,
                                'items':{'type':'string','minLength':1}}}}
OBJECT_CHECK_SCHEMA={'type':'object','additionalProperties':False,'required':['object_id','status','note'],
    'properties':{'object_id':{'type':'string','minLength':1},
                  'status':{'enum':['passed','needs_changes','blocked']},
                  'note':{'type':'string','minLength':1}}}


def components(slide):
    from jsonschema import Draft202012Validator
    lookup={o['id']:o for o in walk_objects(slide.get('objects',[]))}
    declared=slide.get('review_requirements',{}).get('components',[])
    if not isinstance(declared,list):raise ValueError('Review components must be a list')
    result=[];used=set();names=set()
    def expand(ids):
        missing=set(ids)-lookup.keys()
        if missing:raise ValueError('Review component names unknown objects: '+', '.join(sorted(missing)))
        return {o['id'] for oid in ids for o in walk_objects([lookup[oid]])}
    for row in declared:
        if not Draft202012Validator(COMPONENT_SCHEMA).is_valid(row):raise ValueError('Invalid review component id/object_ids')
        ids=expand(row['object_ids'])
        if row['id'] in names or ids & used:raise ValueError('Review components have duplicate IDs or overlapping object ownership')
        result.append({'id':row['id'],'object_ids':sorted(ids),'source':'review_requirements'})
        names.add(row['id']);used.update(ids)
    scope=slide.get('element_scope',{});units={u['id']:u for u in scope.get('units',[])}
    groups={}
    for binding in scope.get('bindings',[]):
        uid=binding['unit_id'];chain=set()
        while uid in units and units[uid].get('owner_id'):
            if uid in chain:raise ValueError('Review component ownership cycle')
            chain.add(uid);uid=units[uid]['owner_id']
        if uid not in units:raise ValueError('Review component owner missing from scope')
        groups.setdefault(uid,set()).update(expand(binding['object_ids']))
    for uid,ids in groups.items():
        # Explicit components take precedence. Ambiguous overlap stays in existing ROIs.
        if len(ids)>1 and not ids & used:
            result.append({'id':'scope-'+uid,'object_ids':sorted(ids),'source':'element_scope'})
            used.update(ids)
    return result


def context(slide, object_ids):
    selected=set(object_ids)
    rows=[row for row in components(slide) if set(row['object_ids']) <= selected]
    return {'review_components':rows,'object_check_ids':sorted({oid for row in rows for oid in row['object_ids']})}


def validate_checks(result, context):
    if __package__:
        from .validation_checks import Checks
    else:
        from validation_checks import Checks
    checks=Checks();rows=result.get('object_checks',[]);names=[]
    allowed=set(context.get('object_ids',[]));required=set(context.get('object_check_ids',[]))
    for i,row in enumerate(rows):
        oid=row['object_id'];names.append(oid)
        if oid not in allowed:checks.add('Object is outside this issued component','/object_checks/'+str(i)+'/object_id','object_coverage',oid)
        if not row['note'].strip():checks.add('Record the actual observation','/object_checks/'+str(i)+'/note','object_observation',oid)
        if result['status']=='passed' and row['status']!='passed':
            checks.add('A negative object observation cannot have an overall passed result','/status','object_status',oid)
    if len(names)!=len(set(names)):checks.add('Each object may be checked once','/object_checks','object_coverage')
    for oid in sorted(required-set(names)):
        checks.add('Record this component object observation','/object_checks','object_coverage',oid)
    checks.finish()
