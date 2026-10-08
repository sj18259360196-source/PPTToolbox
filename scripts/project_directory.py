"""Initialize an explicitly chosen existing workspace without replacing user files."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import time

RESERVED=('input','assets','runs','workflow','delivery','HANDOFF.md')


def inspect_directory(project):
    """Read-only startup guidance; no file creation, merging or deletion."""
    project=Path(project)
    conflicts=[name for name in RESERVED if (project/name).exists() or (project/name).is_symlink()]
    status=('initializing' if (project/'.ppt-toolbox-initialize.lock').exists() else
            'initialized' if (project/'workflow/state.json').is_file() else
            'reserved_entries' if conflicts else 'unused_workspace' if project.exists() else 'new_directory')
    return {'status':status,'conflicts':conflicts,
        'next_action':{'initialized':'Read rebuild_status; preserve the existing workflow.',
            'initializing':'Inspect the initialization lock; do not delete or retry blindly.',
            'reserved_entries':'Use a new project folder and authorized reference inputs; existing entries will not be merged or removed.',
            'unused_workspace':'Use rebuild_start with in_place=true; do not precreate input/assets/runs.',
            'new_directory':'Call rebuild_start before creating managed output directories.'}[status]}


def publish_entry(child, destination):
    from workflow_store import WorkflowError
    for attempt in range(8):
        if destination.exists() or destination.is_symlink():
            raise WorkflowError('project_exists','Workspace changed during initialization; existing files were preserved')
        try:
            child.rename(destination)
            return
        except PermissionError as exc:
            if os.name != 'nt' or getattr(exc,'winerror',None) not in {5,32,33} or attempt==7:
                raise
            time.sleep(min(.05*(2**attempt),.5))


@contextmanager
def initialize_directory(project, in_place=False):
    from common import staged_directory
    from workflow_store import WorkflowError
    if not project.exists():
        with staged_directory(project) as stage:yield stage
        return
    if not in_place:
        raise WorkflowError('project_exists','Use a new project directory or explicit in-place initialization for an unused workspace; resume initialized projects.')
    if not project.is_dir():raise WorkflowError('project_exists','Project path is not a directory')
    preflight=inspect_directory(project)
    if preflight['status']=='initializing':
        exc=WorkflowError('writer_busy','Workspace initialization is active or interrupted; inspect its initialization lock',preflight['next_action'])
        exc.diagnostics=preflight
        raise exc
    if preflight['conflicts']:
        exc=WorkflowError('project_exists','Workspace contains reserved project entries: '+', '.join(preflight['conflicts']),preflight['next_action'])
        exc.diagnostics=preflight
        raise exc
    lock=project/'.ppt-toolbox-initialize.lock'
    try:descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise WorkflowError('writer_busy','Workspace initialization is active or interrupted; inspect its initialization lock')
    os.close(descriptor)
    committed=[];stage=None;published=False
    try:
        conflicts=[name for name in RESERVED if (project/name).exists()]
        if conflicts:raise WorkflowError('project_exists','Workspace contains reserved project entries; preserve them and resume an existing workflow if present: '+', '.join(conflicts))
        stage=Path(tempfile.mkdtemp(prefix='.ppt-toolbox-init-',dir=project))
        yield stage
        children=sorted(stage.iterdir(),key=lambda p:(p.name=='workflow',p.name))
        for child in children:
            destination=project/child.name
            publish_entry(child,destination)
            committed.append(destination)
        stage.rmdir()
        published=True
    except Exception as exc:
        # Never remove anything the user could have edited while committing.
        # Retain unpublished workflow metadata together with the recovery lock.
        if committed:
            raise WorkflowError('initialization_incomplete',
                'Some project folders were published; remaining staging files were preserved. Inspect the workspace before continuing',
                f'Staging: {stage.name}; cause: {type(exc).__name__}; winerror: {getattr(exc,"winerror",None)}') from exc
        raise
    finally:
        if stage is not None and not committed and stage.exists():
            resolved=stage.resolve()
            if (not stage.is_symlink() and resolved.is_relative_to(project.resolve())
                    and resolved.name.startswith('.ppt-toolbox-init-')):
                shutil.rmtree(resolved)
        if not committed or published:lock.unlink()
