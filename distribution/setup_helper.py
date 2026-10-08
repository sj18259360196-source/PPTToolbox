"""Backend for the per-user installer; reports errors without touching projects."""
from __future__ import annotations
import argparse,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from distribution.update_installed import install_new,upgrade,audit,discover
from distribution.install_local import controllers,no_reparse

def stop_idle(destination,uninstall=False):
    location=destination/"location.json"
    if not location.exists():return
    data=no_reparse(json.loads(location.read_text(encoding="utf-8"))["data_directory"])
    # The old idle controller may own a historical call. Ask it to exit before
    # inspecting PIDs; never turn a missing completion event into a permanent
    # upgrade block. Locks and queued/running resident tasks still block here.
    with sqlite3.connect(data/"manager.sqlite3") as db:audit(data,db,check_calls=False)
    if not controllers([destination,data]):
        with sqlite3.connect(data/"manager.sqlite3") as db:audit(data,db,quiescent=True)
        return
    signal=data/"UPDATE_REQUEST.json"
    signal.write_text(json.dumps({"data":str(data),"created":time.time(),'mode':'uninstall' if uninstall else 'upgrade'}),encoding="utf-8")
    try:
        until=time.monotonic()+12
        while time.monotonic()<until:
            if not controllers([destination,data]):
                with sqlite3.connect(data/"manager.sqlite3") as db:audit(data,db,quiescent=True)
                return
            time.sleep(.3)
        raise ValueError("旧版后台或 Agent 仍在运行。请从托盘退出工具箱，并停止其 MCP 服务后重试。当前任务和文件未被强制终止。")
    finally:signal.unlink(missing_ok=True)

def validate(destination):
    # Exercise delivered native dependencies without opening the fenced DB.
    r=subprocess.run([str(destination/"runtime/python.exe"),"-B","-I","-X","utf8",
                      str(destination/"app/distribution/runtime_probe.py"),"--bundle",str(destination)],
                     capture_output=True,text=True,encoding="utf-8",timeout=360,
                     creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if r.returncode:raise ValueError("新版本运行环境检查失败。"+r.stderr[-1200:])
    try:
        result=json.loads(r.stdout)
    except (TypeError,ValueError) as exc:
        raise ValueError("新版本运行环境检查没有返回有效结果") from exc
    if (not isinstance(result,dict) or result.get("status")!="passed"
            or result.get("checks")!={"scipy_fit":True,"scipy_filter":True,
                                    "svg_render":True,"geometry":True,
                                    "native_tool_entrypoints":True,"update_signature":True,"pdf_preview":True}):
        raise ValueError("新版本图形运行环境检查未通过")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--bundle",type=Path);p.add_argument("--destination",required=True,type=Path)
    p.add_argument("--data",type=Path);p.add_argument("--projects",type=Path)
    p.add_argument("--report",required=True,type=Path);p.add_argument("--uninstall-check",action="store_true")
    a=p.parse_args();a.report.parent.mkdir(parents=True,exist_ok=True)
    session=None
    try:
        destination=no_reparse(a.destination)
        if not a.uninstall_check and (destination/'location.json').exists():
            saved=json.loads((destination/'location.json').read_text(encoding='utf-8'))
            candidate=no_reparse(saved['data_directory'])/'UPDATE_SESSION.json'
            with candidate.open('x',encoding='utf-8') as stream:
                json.dump({'installer_pid':os.getpid(),'created':time.time()},stream)
            session=candidate
        stop_idle(destination,uninstall=a.uninstall_check)
        if a.uninstall_check:
            result={"status":"safe_to_uninstall","data_and_projects_preserved":True}
        elif (destination/"location.json").exists():
            result=upgrade(a.bundle.resolve(),destination,validate=validate)
        else:
            current=discover(os.environ["LOCALAPPDATA"])
            if current and current!=destination:raise ValueError("已发现另一处正式安装。请先更新该位置；更换位置使用工具箱中的安装与迁移。")
            result=install_new(a.bundle.resolve(),destination,a.data.resolve(),a.projects.resolve(),
                               Path(os.environ["LOCALAPPDATA"])/"PPTToolbox-installation.json",installer=True,validate=validate)
        a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as exc:
        a.report.write_text(str(exc),encoding="utf-8");return 1
    finally:
        if session is not None:session.unlink(missing_ok=True)
    return 0
if __name__=="__main__":raise SystemExit(main())
