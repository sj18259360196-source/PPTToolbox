"""Managed-call policy, not an operating-system sandbox."""
from __future__ import annotations

import os
import stat
from pathlib import Path


class PolicyDenied(ValueError):
    code = "permission_denied"


def plain_path(value):
    if not isinstance(value, (str, Path)) or not str(value) or "\0" in str(value):
        raise PolicyDenied("Invalid path")
    raw = Path(value).expanduser().absolute()
    if os.name == "nt" and any(":" in part or part.endswith((" ", ".")) for part in raw.parts[1:]):
        raise PolicyDenied("Alternate streams and ambiguous Windows paths are not authorized")
    for p in (raw, *raw.parents):
        if p.exists() or p.is_symlink():
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise PolicyDenied("Symlink/reparse paths are not authorized")
    return raw.resolve()


def check_tree(root):
    root = plain_path(root)
    if not root.is_dir():
        return
    # Validate each directory entry once. Its ancestors were validated on descent;
    # resolving every ancestor again made large project logs quadratic in depth.
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if os.name == "nt" and (":" in entry.name or entry.name.endswith((" ", "."))):
                    raise PolicyDenied("Ambiguous Windows paths are not authorized")
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise PolicyDenied("Symlink/reparse paths are not authorized")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
                elif os.stat(entry.path, follow_symlinks=False).st_nlink > 1:
                    raise PolicyDenied("Hard-linked project files are not authorized")


def check_input(value, project, roots):
    p = plain_path(value if Path(value).is_absolute() else project/value)
    if not any(p.is_relative_to(r) for r in [project, *roots]):
        raise PolicyDenied("Input path is outside this project's authorization")
    if not p.is_file():
        raise ValueError("Input file is missing")
    return p


def authorize(manager, project):
    from .project_context import ProjectContext
    project = ProjectContext(manager,project).root
    from .project_inventory import lifecycle
    if lifecycle(project)["status"] == "completed":
        raise PolicyDenied("项目已完结。请在项目管理中重新开启；已清理制作历史的项目只能编辑成品或新建制作")
    p = manager.package()
    package_root = plain_path(p["path"])
    if (project.is_relative_to(package_root) or package_root.is_relative_to(project)
            or project.is_relative_to(manager.data) or manager.data.is_relative_to(project)):
        raise PolicyDenied("Project must be separate from code and manager data")
    row = next((v for k, v in manager.store.get("project_authorizations", {}).items()
                if os.path.normcase(k) == os.path.normcase(str(project))), None)
    if not isinstance(row, dict):
        raise PolicyDenied("Project not authorized by owner; no directories were added")
    if row.get("write") is not True:
        raise PolicyDenied("Project write authorization is unavailable")
    roots = [plain_path(r) for r in row.get("input_roots", [])]
    check_tree(project)
    return project, roots


class Policy:
    def __init__(self, envelope):
        required = {"format", "call_id", "parent_pid", "package_root", "project", "input_roots", "allowed", "command", "arguments"}
        if set(envelope) != required or envelope["format"] != "ppt-managed-call/1":
            raise PolicyDenied("Missing managed execution context")
        if envelope["call_id"] != os.environ.get("PPT_MANAGED_CALL_ID"):
            raise PolicyDenied("Managed execution identity mismatch")
        if envelope["parent_pid"] != os.getppid():
            raise PolicyDenied("Managed execution parent mismatch")
        if not isinstance(envelope["allowed"], list) or any(not isinstance(x, str) for x in envelope["allowed"]):
            raise PolicyDenied("Invalid capability snapshot")
        self.project = plain_path(envelope["project"])
        from .project_inventory import lifecycle
        if lifecycle(self.project)["status"] == "completed":
            raise PolicyDenied("Project completed by owner; managed writes are disabled")
        self.inputs = [plain_path(r) for r in envelope["input_roots"]]
        self.allowed = frozenset(envelope["allowed"])
        self.call_id = envelope["call_id"]

    def require(self, *capabilities):
        missing = sorted(set(capabilities) - self.allowed)
        if missing:
            raise PolicyDenied("Disabled or unavailable capabilities: " + ", ".join(missing))

    def input(self, value):
        return check_input(value, self.project, self.inputs)

    def result_paths(self, result, kind):
        result=dict(result)
        if kind == 'review_full' and 'additional_reviews' in result:
            result['additional_reviews'] = [
                {**row, 'result': self.result_paths(row['result'], 'review_local')}
                for row in result['additional_reviews']]
        fields = ["file"] if kind in {"candidate", "asset_material"} else ["receipt"] if kind == "office_render" else []
        for key in fields:
            p = self.input(result[key])
            result[key]=str(p)
            if key == "receipt":
                check_tree(p.parent)
        for key in ("viewed_files", "files"):
            if key in result:result[key]=[str(self.input(value)) for value in result[key]]
        return result
