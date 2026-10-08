"""Charge post-plan managed Office exports to persistent repair budgets."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from common import read_json, write_json
from workflow_store import WorkflowError

PRE_RESERVED = ContextVar("calibration_exports_pre_reserved", default=False)


def project_for(path):
    for parent in Path(path).resolve().parents:
        if (parent/"workflow/state.json").is_file():
            return parent
    return None


@contextmanager
def pre_reserved():
    token = PRE_RESERVED.set(True)
    try:
        yield
    finally:
        PRE_RESERVED.reset(token)


@contextmanager
def track(project, destination, pages):
    """Caller holds the existing project writer lock. Never refund uncertain slots."""
    ledgers = [] if project is None or PRE_RESERVED.get() else sorted(
        (Path(project)/"calibrations").glob("episode-*.json"))
    if not ledgers:
        yield
        return
    rows = [(p, read_json(p)) for p in ledgers]
    for _, row in rows:
        if row["exports_reserved"]+pages > 40:
            raise WorkflowError("budget_exhausted", "Managed export exceeds cumulative calibration budget")
    destination = Path(destination)
    existing = set(destination.rglob("slide-*.png")) if destination.exists() else set()
    for path, row in rows:
        row["exports_reserved"] += pages
        row.setdefault("external_exports", []).append({"destination": str(destination), "reserved": pages,
                                                       "completed": 0, "status": "running"})
        write_json(path, row)
    complete = False
    try:
        yield
        complete = True
    finally:
        actual = len(set(destination.rglob("slide-*.png"))-existing)
        for path, _ in rows:
            row = read_json(path)
            row["exports_completed"] += actual
            record = row["external_exports"][-1]
            record.update(completed=actual, status="completed" if complete else "outcome_unknown")
            write_json(path, row)


def cli_export(tool, args):
    """Read fixed registered flags only, never execute caller-provided code."""
    values = {}
    i = 0
    while i < len(args):
        raw = args[i]
        flag, separator, inline = raw.partition(":")
        if raw.startswith("--"):
            flag, separator, inline = raw.partition("=")
        if flag.lower() in {"-pptx", "--pptx", "-outputdir", "--outdir", "--operations"}:
            values[flag.lower().lstrip("-")] = inline if separator else args[i+1]
            i += 1 if separator else 2
        else:
            i += 1
    if tool not in {"office.render", "office.edit-readback"} or "pptx" not in values:
        return None
    from pptx import Presentation
    pages = len(Presentation(values["pptx"]).slides)
    if tool == "office.edit-readback":
        pages = len({row["slide"] for row in read_json(Path(values["operations"]))})
    return Path(values.get("outputdir", values.get("outdir"))), pages
