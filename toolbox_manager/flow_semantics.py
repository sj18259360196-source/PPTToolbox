"""Read-only task ownership and version/feedback projection from local evidence.

No graph operation here changes a workflow, acceptance, or model request budget.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from datetime import datetime


def moment(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def identifier(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def lifecycle(manager, workflow):
    """Only exact workflow events and version-scoped consent establish milestones."""
    items=[]; round_no=1; previous_version=None
    revisions={'region_reopened','imported_region_reopened','candidate_replaced'}
    for event in workflow.get('history', []):
        kind=event.get('event'); detail=event.get('detail') or {}
        if kind not in revisions|{'delivery_created'}:
            continue
        if kind in revisions:
            round_no+=1
        version=str(detail.get('dir','')).replace('\\','/').rstrip('/').split('/')[-1] if kind=='delivery_created' else None
        item={'id':'life-'+identifier((workflow.get('project_id'),event.get('revision'),kind)),
              'event':kind,'at':event.get('at'),'round':round_no,'revision':event.get('revision'),
              'version':version,'input_version':previous_version,
              'evidence_id':'workflow-'+str(event.get('revision'))}
        items.append(item)
        if version:previous_version=version
    # Retrospective records are immutable and scoped by project AND output run.
    with manager.store.db() as db:
        rows=db.execute("SELECT value FROM kv WHERE key LIKE 'retrospective:%' AND json_extract(value,'$.source.project_id')=?",
                        (workflow.get('project_id'),)).fetchall()
    for row in rows:
        record=json.loads(row[0]); source=record.get('source',{})
        if not workflow.get('project_id') or source.get('project_id')!=workflow.get('project_id'):continue
        delivery=next((i for i in items if i.get('version')==source.get('run_id')),None)
        if not delivery:continue
        delivery['presented']='presented' in record
        delivery['accepted']='accept' in record
        delivery['consent_source']=next((a.get('consent_basis') for a in record.get('audit',[]) if a.get('action')=='accept'),None)
        delivery['accepted_at']=next((a.get('at') for a in record.get('audit',[]) if a.get('action')=='accept'),None)
    return {'round':round_no,'items':items,'workflow_status':workflow.get('status'),
            'current_version':(workflow.get('run') or {}).get('id'),
            'limitations':'只依据本项目已记录的返修、交付与确认。未登记的宿主聊天不可见。'}


def order(node):
    ids=[int(e[6:]) for e in node.get('evidence_ids',[]) if re.fullmatch(r'audit-\d+',e)]
    return min(ids) if ids else None


def hydrate(manager, root, nodes):
    """Recover old node timing from its own scoped audit IDs, without rewriting it."""
    nodes=copy.deepcopy(nodes)
    ids={int(e[6:]) for n in nodes if n.get('source')=='pptagent'
         for e in n.get('evidence_ids',[]) if re.fullmatch(r'audit-\d+',e)}
    if not ids:return nodes
    with manager.store.db() as db:
        rows=db.execute("SELECT id,time,action,details FROM events WHERE json_extract(details,'$.project')=? AND id IN ("+
                        ','.join('?' for _ in ids)+") ORDER BY id",(str(root),*sorted(ids))).fetchall()
    records={r['id']:r for r in rows}
    for n in nodes:
        selected=[records[int(e[6:])] for e in n.get('evidence_ids',[]) if re.fullmatch(r'audit-\d+',e) and int(e[6:]) in records]
        selected.sort(key=lambda r:r['id'])
        if n.get('source')!='pptagent' or not selected:continue
        first=selected[0];detail=json.loads(first['details'] or '{}')
        n.setdefault('first_at',first['time'])
        if n.get('workflow_revision') is None:n['workflow_revision']=detail.get('revision_before')
        started=[r['time'] for r in selected if r['action'].endswith(('.started','.launched'))]
        finished=[r['time'] for r in selected if r['action'].endswith(('.finished','.reconciled'))]
        if started:n.setdefault('started_at',started[0])
        if finished:n.setdefault('finished_at',finished[-1])
    return nodes


def assign(nodes, life=None):
    """Add ownership without adding a dependency or claiming parallel execution."""
    life=life or {}; boundaries=[i for i in life.get('items',[]) if i['event']!='delivery_created']
    for n in nodes:
        at=moment(n.get('first_at'))
        if n.get('source')=='pptagent' and (n['id'].startswith('auto-') or order(n) is not None):
            revision=n.get('workflow_revision')
            known=[i for i in boundaries if (isinstance(revision,int) and isinstance(i.get('revision'),int) and i['revision']<=revision)
                   or (revision is None and at is not None and moment(i.get('at')) is not None and moment(i['at'])<=at)]
            # Old nodes with no event timestamp cannot be assigned to the latest round.
            if at is not None or isinstance(revision,int):n['round']=max([1]+[i['round'] for i in known])
        tasks=n.get('task_ids') or []
        round_label='第 '+str(n['round'])+' 轮' if n.get('round') else '轮次待确认'
        owner='任务 '+tasks[0] if tasks else ('交付与反馈' if n.get('source')=='lifecycle' else '关系待确认')
        n['group_id']='group-'+identifier((n.get('round'),owner))
        n['group_label']=round_label+' · '+owner
        n['ownership']='task' if tasks else 'lifecycle' if n.get('source')=='lifecycle' else 'unresolved'
    return nodes


def connect_recorded(nodes):
    """Connect unlinked calls within a task by audit order, never as dependencies.

    Explicit branches/joins survive; overlapping calls do not become serial work.
    """
    groups={}; by_id={n['id']:n for n in nodes}
    for n in nodes:
        if n.get('source')=='pptagent' and order(n) is not None:
            groups.setdefault((n.get('round'),tuple(n.get('task_ids') or [])),[]).append(n)
    def ancestor(start,target):
        todo=[start];seen=set()
        while todo:
            value=todo.pop()
            if value==target:return True
            if value in seen:continue
            seen.add(value);todo.extend(by_id.get(value,{}).get('after',[]))
        return False
    for group in groups.values():
        group.sort(key=order)
        for before,after in zip(group,group[1:]):
            if after.get('after') or ancestor(before['id'],after['id']):continue
            start=moment(after.get('started_at')); end=moment(before.get('finished_at'))
            if before.get('status') in {'running','outcome_unknown'}:continue
            if start is not None and (end is None or end>start):continue
            after['after']=[before['id']]
            after['links']=[{'from':before['id'],'relation':'sequence','basis':'recorded',
                            'label':'调用记录先后，不表示执行依赖',
                            'evidence_ids':list(dict.fromkeys(before.get('evidence_ids',[])+after.get('evidence_ids',[])))[-12:]}]
    return nodes


def project(nodes, life=None):
    """Projection is reproducible, bounded, and never persisted as an approval."""
    nodes=copy.deepcopy(nodes); life=life or {}
    # Keep historic stage grouping outside the execution graph.
    for n in nodes:
        grouping={l['from'] for l in n.get('links',[]) if l.get('relation')=='grouping'}
        if grouping:
            n['membership_ids']=sorted(grouping)
            n['after']=[p for p in n.get('after',[]) if p not in grouping]
            n['links']=[l for l in n.get('links',[]) if l.get('relation')!='grouping']
    assign(nodes,life);connect_recorded(nodes)
    def would_cycle(parent,target):
        by_id={n['id']:n for n in nodes}; todo=[parent];seen=set()
        while todo:
            value=todo.pop()
            if value==target:return True
            if value in seen:continue
            seen.add(value);todo.extend(by_id.get(value,{}).get('after',[]))
        return False
    previous=None
    for item in life.get('items',[])[-16:]:
        delivery=item['event']=='delivery_created';rid=item['id']
        if any(n['id']==rid for n in nodes):continue
        n={'id':rid,'kind':'delivery' if delivery else 'revision_plan','stage':'delivery' if delivery else 'revision',
           'title':('交付 '+str(item.get('version'))) if delivery else '开始第 '+str(item['round'])+' 轮修改',
           'status':'observed','status_label':'已输出版本' if delivery else '返修已登记','source':'lifecycle',
           'round':item['round'],'after':[],'links':[],'evidence_ids':[item['evidence_id']],
           'version':item.get('version'),'input_version':item.get('input_version'),
           'detail':'来自工作流持久记录。返修来源可能为检查失败或用户反馈，未记录时不推定。',
           'actions':['files','calls']}
        if previous:
            n['after']=[previous];n['links']=[{'from':previous,'relation':'sequence' if delivery else 'revision','basis':'recorded','label':'交付与返修记录先后'}]
        same=[p for p in nodes if p.get('round')==item['round'] and p.get('source')=='pptagent']
        if delivery:
            parents={v for p in same for v in p.get('after',[])}
            tails=[p for p in same if p['id'] not in parents and moment(p.get('first_at') or p.get('updated_at')) is not None
                   and moment(item.get('at')) is not None and moment(p.get('first_at') or p.get('updated_at'))<=moment(item['at'])]
            for tail in tails[-10:]:
                n['after'].append(tail['id']);n['links'].append({'from':tail['id'],'relation':'sequence','basis':'recorded','label':'本轮调用之后输出版本，不代表全部检查通过'})
        nodes.append(n);previous=rid
        if delivery:
            wait={'id':rid+'-feedback','kind':'acceptance','stage':'delivery','source':'lifecycle','round':item['round'],
                  'title':('用户已认可 ' if item.get('accepted') else '等待用户反馈 ' if item.get('presented') else '等待展示与反馈 ')+str(item.get('version')),
                  'status':'done' if item.get('accepted') else 'planned','status_label':'已记录认可' if item.get('accepted') else '等待反馈' if item.get('presented') else '等待展示',
                  'after':[rid],'links':[{'from':rid,'relation':'sequence','basis':'recorded','label':'输出后进入反馈环节'}],
                  'version':item.get('version'),'evidence_ids':[item['evidence_id']],
                  'detail':'认可只适用于此交付版本。后续修改保留旧版记录。未登记的用户聊天不可见。',
                  'exit_reason':'accepted' if item.get('accepted') else 'awaiting_feedback','actions':['files','calls']}
            nodes.append(wait);previous=wait['id']
        else:
            for target in same:
                if not target.get('after'):
                    if would_cycle(rid,target['id']):
                        target['relation_issue']='现有跨轮关系与返修入口冲突，保留原图并待核对。'
                    else:
                        target['after']=[rid];target['links']=[{'from':rid,'relation':'sequence','basis':'recorded','label':'本轮返修后的调用'}]
    assign(nodes,life)
    parents={v for n in nodes for v in n.get('after',[])}
    for n in nodes:
        if n['id'] not in parents and not n.get('exit_reason'):
            n['exit_reason']=({'running':'running','failed':'failed','outcome_unknown':'unknown','skipped':'skipped','replaced':'replaced'}.get(n.get('status')) or 'relation_pending')
    return nodes
