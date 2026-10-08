"""Offline application update retaining the exact installed data identity."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from datetime import datetime, timezone

from distribution.install_local import controllers, no_reparse
from toolbox_manager import storage_fence


def discover(local):
    local=Path(local)
    pointer=local/"PPTToolbox-installation.json"
    if pointer.exists():
        value=json.loads(pointer.read_text(encoding="utf-8"))
        root=Path(value["installation"])
        if not root.is_absolute():
            raise ValueError("安装记录中的目录必须为绝对路径")
        if not (root/"location.json").is_file():
            raise ValueError("已有安装记录失效，请通过安装与迁移修复，不能建立另一份默认数据")
        return no_reparse(root)
    root=local/"Programs/PPTToolbox"
    return no_reparse(root) if (root/"location.json").is_file() else None


def verify(bundle):
    bundle = no_reparse(bundle)
    manifest=json.loads((bundle/"FILES.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("发行包清单必须为对象")
    required={"PPTToolbox.exe","portable.py","runtime/python.exe","app/PRODUCT.json"}
    if not required<=set(manifest):
        raise ValueError("发行包清单不完整")
    seen = set()
    for name,expected in manifest.items():
        parts = PurePosixPath(name).parts
        if (not parts or name != PurePosixPath(name).as_posix() or name.startswith("/")
                or "\\" in name or ":" in name or ".." in parts
                or any(p.endswith((".", " ")) for p in parts)
                or name.casefold() in seen):
            raise ValueError("发行包路径无效 " + name)
        seen.add(name.casefold())
        if (name.casefold() in {"files.json", "location.json", "update_pending.json", "install_pending.json"}
                or parts[0].casefold() == "data" or name.casefold().startswith("app/data/")):
            raise ValueError("发行包不能包含安装状态或管理数据 " + name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("发行包哈希无效 " + name)
        p=no_reparse(bundle/name)
        if not p.is_relative_to(bundle) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError("发行包校验失败 "+name)
    return manifest


def audit(data, db):
    schema=db.execute("SELECT value FROM kv WHERE key='schema_version'").fetchone()
    if schema and json.loads(schema[0]) != 1:
        raise ValueError('管理数据库版本不兼容，不能更新或回退到此版本')
    if any((data/n).exists() for n in ("RETIRED.json","MIGRATION_PENDING.json","office-writer.lock")):
        raise ValueError("管理数据正在迁移、已退役或存在 Office 写入锁")
    active={}
    for action,body in db.execute("SELECT action,details FROM events ORDER BY id"):
        value=json.loads(body);key=value.get("call_id")
        if not key:continue
        if action in ("tool.finished","tool.reconciled"):active.pop(key,None)
        elif action in ("tool.started","tool.authorized","tool.launched"):active[key]=value
    if active:raise ValueError("存在未决调用，请先核对结果再更新")
    row=db.execute("SELECT value FROM kv WHERE key='pptagent_tasks'").fetchone()
    tasks=json.loads(row[0]) if row else []
    tasks=tasks.values() if isinstance(tasks,dict) else tasks
    if any(task.get('status') in {'queued','running'} for task in tasks):
        raise ValueError('驻留 PPTAgent 仍有待执行或正在执行的任务')
    row=db.execute("SELECT value FROM kv WHERE key='workbench_projects'").fetchone()
    for item in (json.loads(row[0]) if row else {}).values():
        if (Path(item["path"])/"workflow/writer.lock").exists():
            raise ValueError("项目仍有写入锁，请完成当前任务后更新")


def upgrade(bundle, destination, process_check=controllers, validate=None):
    bundle,destination=map(no_reparse,(bundle,destination))
    if bundle==destination:return {"status":"already_installed"}
    if bundle.is_relative_to(destination) or destination.is_relative_to(bundle):
        raise ValueError("更新来源与正式安装目录不能互相包含")
    location_raw=(destination/"location.json").read_bytes()
    data=Path(json.loads(location_raw)["data_directory"])
    if not data.is_absolute():raise ValueError("安装数据位置必须为绝对路径")
    data=no_reparse(data)
    if data.is_relative_to(destination) or destination.is_relative_to(data):
        raise ValueError("正式管理数据必须独立于安装目录，请先通过迁移功能整理")
    if (destination/"UPDATE_PENDING.json").exists():
        raise ValueError("上次更新未完成，请依据更新备份恢复后继续")
    manifest=verify(bundle)
    incoming=json.loads((bundle/"app/PRODUCT.json").read_text(encoding="utf-8"))
    current=json.loads((destination/"app/PRODUCT.json").read_text(encoding="utf-8"))
    if incoming.get("product")!="PPT Toolbox" or current.get("product")!="PPT Toolbox":
        raise ValueError("目标目录不是 PPT Toolbox")
    def version(p):
        return tuple(int(x) for x in p["version"].split("-")[0].split("."))
    if version(incoming)<version(current):
        return {"status":"newer_installed","installation":str(destination)}
    if incoming.get("source_sha256")==current.get("source_sha256") and all(
        (destination/n).is_file() and hashlib.sha256((destination/n).read_bytes()).hexdigest()==h
        for n,h in manifest.items()):
        return {"status":"already_current","installation":str(destination)}
    active=process_check([destination,data])
    if active:
        raise ValueError("请从工具箱托盘退出旧后台，并停止其 Agent 服务，再重新打开新版。占用进程 "+str(active))
    db=data/"manager.sqlite3"
    owner=storage_fence.acquire(db,lambda c:audit(data,c))
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # Backups are persistent upgrade recovery assets, not temporary scratch.
    backup=data/"application-updates"/stamp
    pending=destination/"UPDATE_PENDING.json"
    changed=[]
    try:
        backup.mkdir(parents=True)
        with sqlite3.connect(db) as source,sqlite3.connect(backup/"manager.sqlite3") as target:
            source.backup(target)
        (backup/"location.json").write_bytes(location_raw)
        pending.write_text(json.dumps({"backup":str(backup),"version":incoming["version"]}),encoding="utf-8")
        if process_check([destination,data]):raise ValueError("更新期间后台重新启动，请退出后重试")
        # Private bundled experience belongs to this installation. When a public
        # build replaces it with an empty catalog, retain it in the data library.
        library={'status':'unchanged'}
        old_sources=destination/'app/assets/experience/knowledge/sources.json'
        new_sources=bundle/'app/assets/experience/knowledge/sources.json'
        if (incoming.get('public_distribution') and old_sources.is_file() and new_sources.is_file()
                and json.loads(old_sources.read_text('utf-8')) and not json.loads(new_sources.read_text('utf-8'))):
            from scripts.experience_library import import_snapshot
            library=import_snapshot(destination/'app',bundle/'app',data/'experience-library')
        # Only files declared in the verified release can be replaced.
        for name in [*manifest,"FILES.json"]:
            if name in {"location.json","UPDATE_PENDING.json"} or name.startswith(("data/","app/data/")):
                raise ValueError("发行包不能覆盖管理数据或安装位置")
            source=bundle/name;target=no_reparse(destination/name)
            if not target.is_relative_to(destination):raise ValueError("安装目标越界")
            previous=target.read_bytes() if target.exists() else None
            content=source.read_bytes()
            if previous==content:continue
            if previous is not None:
                saved=backup/"files"/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(previous)
            changed.append((name,previous is not None))
            (backup/"changed.json").write_text(json.dumps(changed),encoding="utf-8")
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(content)
            if target.read_bytes()!=content:raise ValueError("更新文件读回失败 "+name)
        if (destination/"location.json").read_bytes()!=location_raw:
            raise ValueError("安装位置配置发生变化")
        if validate:validate(destination)
        report={"status":"updated","version":incoming["version"],"installation":str(destination),
                "data_directory":str(data),"backup":str(backup),"changed_files":len(changed),
                "settings_preserved":True,"mcp_path_preserved":True,"experience_library":library}
        (backup/"receipt.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        pending.unlink()
        return report
    except BaseException:
        for name,existed in reversed(changed):
            target=destination/name
            if existed:shutil.copyfile(backup/"files"/name,target)
            elif target.exists():target.unlink()
        pending.unlink(missing_ok=True)
        raise
    finally:
        storage_fence.release(db,owner)


def copy_new_program(bundle, destination, manifest, validate=None):
    """Rollback only files and empty directories created by this copy attempt."""
    created, directories = [], []
    try:
        for name in [*manifest, "FILES.json"]:
            target = no_reparse(destination / name)
            if not target.is_relative_to(destination):
                raise ValueError("安装目标越界")
            missing = []
            parent = target.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                directories.append(parent)
            with target.open("xb") as output:
                created.append(target)
                with (bundle / name).open("rb") as source:
                    shutil.copyfileobj(source, output)
            if name in manifest and hashlib.sha256(target.read_bytes()).hexdigest() != manifest[name]:
                raise ValueError("安装文件读回失败 " + name)
        if validate:
            validate(destination)
    except BaseException:
        for target in reversed(created):
            no_reparse(target).unlink(missing_ok=True)
        for directory in reversed(directories):
            try:
                directory.rmdir()
            except OSError:
                pass  # Never remove another process's files.
        raise


def install_new(bundle,destination,data,projects,active_pointer=None,codex_config=None,process_check=controllers,installer=False,validate=None):
    """First install only; existing data always goes through migration/update."""
    from distribution.install_local import codex_patch
    from toolbox_manager.service import Manager
    paths=(bundle,destination,data,projects)
    if any(not Path(p).is_absolute() for p in paths):raise ValueError("请选择绝对路径")
    bundle,destination,data,projects=map(no_reparse,paths)
    for path in (destination,data):
        import re
        occupied=path.exists() and (not path.is_dir() or any(
            not (installer and path==destination and re.fullmatch(r"unins\d+\.(exe|dat|msg)",p.name))
            for p in path.iterdir()))
        if occupied:
            raise ValueError("首次安装目标必须为空，已有安装请使用更新或迁移")
    for a,b in ((destination,data),(destination,projects),(data,projects),(bundle,destination),(bundle,data),(bundle,projects)):
        if a.is_relative_to(b) or b.is_relative_to(a):raise ValueError("程序、管理数据和项目目录必须相互独立")
    if process_check([destination,data]):raise ValueError("目标目录存在运行中的控制器")
    manifest=verify(bundle)
    change=codex_patch(codex_config,destination) if codex_config else None
    pointer = None
    if active_pointer is not None:
        if not Path(active_pointer).is_absolute():
            raise ValueError("安装索引必须为绝对路径")
        pointer = no_reparse(active_pointer)
        if any(pointer.is_relative_to(p) for p in (bundle,destination,data,projects)):
            raise ValueError("安装索引必须位于程序及数据目录之外")
        if pointer.exists():
            raise ValueError("已有安装索引，请先核对原安装")
    # Validate the exact verified runtime before publishing installation identity
    # or creating a management database. A missing dependency is retryable.
    if validate:
        validate(bundle)
    copy_new_program(bundle, destination, manifest, validate=validate)
    manager=Manager(data,root=destination/"app")
    settings=manager.settings()
    projects.mkdir(parents=True,exist_ok=True)
    manager.save_settings({"revision":settings["revision"],"values":{"projects_directory":str(projects)}})
    location={"data_directory":str(data),"projects_directory":str(projects),
              "installed_at":datetime.now(timezone.utc).isoformat()}
    (destination/"location.json").write_text(json.dumps(location,indent=2),encoding="utf-8")
    if change:
        config=Path(codex_config)
        if (config.read_text(encoding="utf-8") if config.exists() else "")!=change[0]:
            raise ValueError("接入配置发生变化，安装文件已保留，请核对接入")
        config.parent.mkdir(parents=True,exist_ok=True)
        config.write_text(change[1],encoding="utf-8")
    report={"status":"installed","installation":str(destination),**location}
    if pointer is not None:
        pointer.parent.mkdir(parents=True,exist_ok=True)
        with pointer.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
    return report
