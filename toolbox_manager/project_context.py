"""Explicit project roots; no shared current-directory state or folder scanning."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .policy import plain_path, PolicyDenied

DEFAULT_PROJECTS_ROOT = str(Path.home() / 'Documents' / 'PPTToolbox' / 'Projects')
LAYOUT = {'inputs':'input','assets':'assets','versions':'runs','workflow':'workflow',
          'delivery':'delivery','logs':'logs/tool-calls','handoff':'HANDOFF.md'}


def toolbox_locations(manager):
    return {'toolbox_root':str(manager.root),'package_root':manager.package()['path'],
            'management_root':str(manager.data),'global_logs':str(manager.store.path),
            'cache_root':str(manager.data/'cache'),
            'default_projects_root':manager.settings()['projects_directory'] or DEFAULT_PROJECTS_ROOT}


class ProjectContext:
    def __init__(self, manager, project):
        if not isinstance(project,(str,Path)) or not Path(project).is_absolute():
            raise PolicyDenied('Project root must be an explicit absolute path')
        self.root=plain_path(project)
        for value in (manager.root,manager.package()['path'],manager.data):
            protected=plain_path(value)
            if self.root.is_relative_to(protected) or protected.is_relative_to(self.root):
                raise PolicyDenied('Project must be separate from code and manager data')
        if self.root.exists() and not self.root.is_dir():raise ValueError('Project root must be a directory')
        self.manager=manager

    def path(self, relative):
        if not isinstance(relative,str) or not relative or Path(relative).is_absolute():
            raise PolicyDenied('Expected a project-relative path')
        target=plain_path(self.root/relative)
        if not target.is_relative_to(self.root):raise PolicyDenied('Path leaves current project')
        return target

    def snapshot(self, read_state=True):
        result={'project_root':str(self.root),'project_id':None,'initialized':False,
                'paths':{key:str(self.path(value)) for key,value in LAYOUT.items()},
                'current_pptx':None,'current_scene':None,'current_run':None,'current_delivery':None}
        if read_state and self.path('workflow/state.json').is_file():
            state=json.loads(self.path('workflow/state.json').read_text(encoding='utf-8-sig'))
            run=state.get('run') or {}
            result.update(project_id=state['project_id'],initialized=True,revision=state['revision'],
                          workflow_status=state['status'],current_run=run.get('id'))
            for key,relative in [('current_pptx',(run.get('candidate') or {}).get('file')),
                                 ('current_scene',run['dir']+'/scene.json' if run.get('dir') else None),
                                 ('current_delivery',state.get('delivery'))]:
                if relative:result[key]=str(self.path(relative))
            from .project_inventory import lifecycle
            life = lifecycle(self.root)
            result['lifecycle'] = life
            if life['status'] == 'completed':
                result.update(current_pptx=str(self.path(life['delivery'])),
                              current_delivery=str(self.path(life['delivery']).parent))
                if life.get('history_cleaned'):
                    result.update(current_scene=None, current_run=None)
        from .material_policy import effective
        if read_state:
            from scripts.project_directory import inspect_directory
            result['initialization']=inspect_directory(self.root)
        result['material_policy'] = effective(self.manager, self.root)
        result['workbench_key'] = next((k for k,v in self.manager.store.get('workbench_projects',{}).items()
                                      if plain_path(v['path']) == self.root), None)
        return result


def can_read(manager, root):
    return any(os.path.normcase(k)==os.path.normcase(str(root)) and row.get('write') is True
               for k,row in manager.store.get('project_authorizations',{}).items())


def bind(manager, project=None, name=None):
    """Return a session binding. Binding is not a write grant and creates no files."""
    import uuid
    if project is not None and name is not None:raise ValueError('Supply project OR name')
    if project is None:
        if not isinstance(name,str) or not name.strip() or any(c in name for c in '<>:"/\\|?*') or any(ord(c)<32 for c in name):
            raise ValueError('Provide a project path or a new project folder name')
        root=Path(toolbox_locations(manager)['default_projects_root'])
        project=root/name
        if Path(project).exists():raise ValueError('Default task directory already exists; bind its explicit path to resume')
    context=ProjectContext(manager,project)
    return {**context.snapshot(can_read(manager,context.root)),'context_id':uuid.uuid4().hex}


def refresh(manager, binding):
    context=ProjectContext(manager,binding['project_root'])
    current=context.snapshot(can_read(manager,context.root))
    if binding.get('project_id') and current['project_id']!=binding['project_id']:
        raise PolicyDenied('Project moved, disappeared or changed identity; bind the project context again')
    return {**current,'context_id':binding['context_id']}


def resolve_call(manager, binding, args):
    """A stale request cannot silently follow a later session switch."""
    if not binding:raise PolicyDenied('Bind project context before using context_id')
    if args.get('context_id')!=binding['context_id']:
        raise PolicyDenied('Stale project context; read or bind the current context again')
    current=refresh(manager,binding)
    if args.get('project') and ProjectContext(manager,args['project']).root!=Path(current['project_root']):
        raise PolicyDenied('Project differs from current context; bind it before switching')
    return {**{k:v for k,v in args.items() if k!='context_id'},'project':current['project_root']},current
