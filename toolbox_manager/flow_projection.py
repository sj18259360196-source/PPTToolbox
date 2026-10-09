"""Connected suggested routes for old journals without authored dependencies.

Every generated link is labelled as a suggestion or grouping. Tool observations
remain observations; a useful diagram must not invent an execution dependency.
"""
from scripts.project_flow import STEP_TYPES, STAGES


def checkpoint_nodes(checkpoints):
    import hashlib
    kinds={'replan':'revision_plan','resume':'resume','blocked':'recovery','pause':'recovery'}
    templates={t['id']:t for t in STEP_TYPES}
    selected=[c for c in checkpoints if c.get('event') in kinds][-6:]
    result=[]
    for c in selected:
        identifier=c.get('checkpoint_id')
        if not identifier:continue
        kind=kinds[c['event']]; t=templates[kind]
        result.append({'id':'checkpoint-'+hashlib.sha256(identifier.encode()).hexdigest()[:12],
            'kind':kind,'title':t['title'],'stage':c.get('stage',t['stage']),
            'status':'observed','status_label':'已记录调整','source':'checkpoint','after':[],
            'detail':c.get('result_summary',''),'result':c.get('result_summary',''),
            'next_action':c.get('next_action',''),'evidence_ids':[identifier]})
    return result


def connect_suggestions(nodes, *, continuations=True):
    templates = {t['id']:t for t in STEP_TYPES}
    # These continuations explain where a composition goes even before an Agent
    # registers a complete graph. They are never represented as completed work.
    if continuations and any(n.get('kind')=='compose' for n in nodes):
        for kind in ('preview','visual_review','edit_verify'):
            if not any(n.get('kind')==kind for n in nodes):
                t=templates[kind]
                nodes.append({'id':'suggested-'+kind,'kind':kind,'title':t['title'],
                    'stage':t['stage'],'status':'planned','status_label':'建议后续',
                    'source':'suggested','after':[],
                    'detail':'预设的后续检查，尚无该步骤的执行记录。具体路径由制作 Agent 按项目需要登记。'})

    def connect(node, parents, label, relation='suggested'):
        node['after']=list(dict.fromkeys(parents))
        node['links']=[{'from':p,'relation':relation,'basis':'suggested','label':label} for p in node['after']]

    previous=[]
    for stage in STAGES:
        anchor=next(n for n in nodes if n['id']==stage)
        connect(anchor,previous,'建议进入下一阶段')
        group=[n for n in nodes if n.get('stage')==stage and n['id']!=stage]
        if not group:
            previous=[stage];continue
        # Branches are parallel unless a preset continuation below explains a
        # possible join. Existing asset decision chains already have evidence.
        routes=[n for n in group if n.get('route_job')]
        regular=[n for n in group if not n.get('route_job')]
        tails=[]
        for n in regular:
            connect(n,[stage],'阶段内步骤','grouping')
            tails.append(n['id'])
        changes=[n for n in regular if n.get('source')=='checkpoint']
        for before,after in zip(changes,changes[1:]):
            after['after']=[before['id']]
            after['links']=[{'from':before['id'],'relation':'sequence','basis':'recorded',
                'label':'调整记录先后','evidence_ids':before['evidence_ids']+after['evidence_ids']}]
            tails.remove(before['id'])
        if routes:
            route_parents={p for n in routes for p in n['after']}
            tails.extend(n['id'] for n in routes if n['id'] not in route_parents)
            for n in routes:
                n['links']=[{'from':p,'relation':'decision' if n.get('kind')=='generation' else 'dependency',
                    'basis':'agent','label':'素材路线已登记'} for p in n['after']]
        order = (['compose'] if stage=='production' else
                 ['preview','visual_review','detail_review','review','repair','recheck','edit_verify','reproducibility']
                 if stage=='revision' else [])
        ordered=[n for kind in order for n in regular if n.get('kind')==kind]
        if ordered:
            ordered_ids={n['id'] for n in ordered}
            frontier=[p for p in tails if p not in ordered_ids] or [stage]
            for n in ordered:
                connect(n,frontier,'建议汇合后继续' if len(frontier)>1 else '建议后续检查' if stage=='revision' else '建议整页合成')
                frontier=[n['id']]
            tails=frontier
        previous=tails or [stage]
    return nodes
