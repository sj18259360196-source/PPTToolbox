"""Owner-controlled client configuration and evidence-based MCP onboarding."""
from __future__ import annotations
import copy,hashlib,json,os,re,secrets,subprocess,sys,time,tomllib
from pathlib import Path
from .policy import plain_path

SERVER="ppt_toolbox_manager"
HOSTS={"codex":"Codex","cursor":"Cursor","antigravity":"Antigravity","generic":"其他 MCP 客户端"}

def server_name(value,host):
    servers=value.get("mcp_servers" if host=="codex" else "mcpServers",{})
    if host=="antigravity" and "ppt-toolbox-manager" in servers:
        if SERVER in servers:raise ValueError("存在两个工具箱 MCP 条目，请先保留一个再配置")
        return "ppt-toolbox-manager"
    return SERVER

def sha(raw):return hashlib.sha256(raw).hexdigest()

def connection_digest(p,host):
    # Bind verification to this server's semantic configuration only. Full-file
    # hashes remain mandatory for plan/apply's concurrent-write protection.
    _,_,entry=read_config(p,host)
    return sha(json.dumps(entry,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8"))

def connection(m):
    bundle=m.root.parent
    bridge=bundle/"agent_bridge.py"
    if (bundle/"location.json").is_file() and bridge.is_file():
        return {"command":str(bundle/"runtime/python.exe"),"args":["-B",str(bridge)]}
    return {"command":sys.executable,"args":["-B",str(m.root/"manager.py"),"--data-dir",str(m.data),"mcp"]}

def target(m,host,path=None):
    if host not in HOSTS:raise ValueError("请选择支持的 Agent")
    if host=="generic":return None
    if path:
        p=Path(path).expanduser()
        if not p.is_absolute():raise ValueError("配置文件需要完整路径")
    elif host=="codex":
        p=Path(os.environ.get("CODEX_HOME",str(m.home/".codex")))/"config.toml"
    elif host=="antigravity":
        p=m.home/".gemini/config/mcp_config.json"
        legacy=m.home/".gemini/antigravity/mcp_config.json"
        if not p.exists() and legacy.exists():p=legacy
    else:p=m.home/".cursor/mcp.json"
    p=plain_path(p)
    if p.suffix.lower()!=(".toml" if host=="codex" else ".json"):raise ValueError("配置文件类型不匹配")
    if p.exists() and (not p.is_file() or p.stat().st_nlink>1):raise ValueError("配置目标必须是普通文件")
    return p

def snippet(m,host,name=SERVER):
    server=connection(m)
    if host=="codex":
        return f"[mcp_servers.{SERVER}]\ncommand = {json.dumps(server['command'],ensure_ascii=False)}\nargs = {json.dumps(server['args'],ensure_ascii=False)}\nenabled = true\n"
    return json.dumps({"mcpServers":{name:server}},ensure_ascii=False,indent=2)

def read_config(p,host):
    raw=p.read_bytes() if p and p.exists() else b""
    if len(raw)>2_000_000:raise ValueError("配置文件过大，请手动检查")
    value=(tomllib.loads(raw.decode("utf-8-sig")) if host=="codex" else json.loads(raw.decode("utf-8-sig"))) if raw else {}
    if not isinstance(value,dict):raise ValueError("配置文件格式不正确")
    servers=value.get("mcp_servers" if host=="codex" else "mcpServers",{})
    if not isinstance(servers,dict):raise ValueError("MCP 配置结构不正确")
    return raw,value,servers.get(server_name(value,host))

def status(m,host="codex",path=None):
    p=target(m,host,path);expected=connection(m);error=None;entry=None;raw=b"";name=SERVER
    try:
        if p:
            raw,value,entry=read_config(p,host);name=server_name(value,host)
    except Exception as exc:error=str(exc)
    matches=isinstance(entry,dict) and entry.get("command")==expected["command"] and entry.get("args")==expected["args"] and entry.get("enabled",True) is not False and entry.get("disabled",False) is not True
    verified=m.store.get("agent_connection_verified",{})
    identity=m.instance()
    digest=connection_digest(p,host) if not error else None
    valid=bool(not error and verified and verified.get("host")==host and verified.get("connection_sha256")==digest and verified.get("config_path")== (str(p) if p else None) and
               verified.get("app_dir")==str(m.root) and verified.get("data_dir")==str(m.data) and
               verified.get("source_sha256")== (m.distribution() or {}).get("source_sha256") and verified.get("version")==(m.distribution() or {}).get("version") and (matches or host=="generic"))
    probe=m.store.get("agent_probe",{})
    probe_valid=probe.get("passed") is True and probe.get("source_sha256")== (m.distribution() or {}).get("source_sha256") and probe.get("connection")==expected and probe.get("version")==(m.distribution() or {}).get("version")
    state="verified" if valid else "configured" if matches else "manual" if host=="generic" else "missing"
    return {"host":host,"hosts":HOSTS,"target":str(p) if p else "",
            "state":state,"configured":matches,"config_error":error,"snippet":snippet(m,host,name),
            "connection":expected,"probe":probe if probe_valid else None,
            "host_verification":verified if valid else None,"instance":identity,
            "execution_enabled":m.settings()["agent_execution_enabled"],
            "note":"本机自检不代表宿主已加载。请在 Agent 中完成连接验证调用。",
            "instructions":["写入配置或复制到客户端的 MCP 设置。","在客户端刷新 MCP 或重新启动客户端。",
                            "复制验证提示词，在 Agent 对话中发送。","回到此页检查宿主验证结果。"]}

def plan(m,a):
    host=a.get("host","codex");p=target(m,host,a.get("path"))
    if p is None:raise ValueError("通用客户端请复制配置到其 MCP 设置")
    raw,value,old=read_config(p,host);wanted=connection(m);name=server_name(value,host)
    if old is not None and not isinstance(old,dict):raise ValueError("已有同名配置格式异常")
    if old and old.get("command")!=wanted["command"]:
        command=Path(old.get("command",""))
        product=command.parent.parent/"app/PRODUCT.json"
        if not product.is_file() or json.loads(product.read_text(encoding="utf-8")).get("product")!="PPT Toolbox":
            raise ValueError("同名 MCP 配置指向其他程序，请先手动核对")
    if host=="codex":
        text=raw.decode("utf-8-sig")
        if re.search(r"(?m)^\s*\[mcp_servers\.ppt_toolbox_manager\.",text):
            raise ValueError("已有同名配置包含自定义子表，请手动合并")
        text=re.sub(r"(?ms)^\[mcp_servers\.ppt_toolbox_manager\][^\n]*\n.*?(?=^\[|\Z)","",text)
        proposed=text.rstrip()+"\n\n"+snippet(m,host)
        check=tomllib.loads(proposed)
        before=copy.deepcopy(value);after=copy.deepcopy(check)
        for d in (before,after):d.setdefault("mcp_servers",{}).pop(SERVER,None)
        if before!=after:raise ValueError("无法仅修改本工具箱条目，请手动配置")
    else:
        value.setdefault("mcpServers",{})[name]=wanted
        proposed=json.dumps(value,ensure_ascii=False,indent=2)+"\n"
    token=secrets.token_urlsafe(24)
    m.pending[token]={"type":"agent_setup","host":host,"path":str(p),"sha":sha(raw),"text":proposed,"created":time.time()}
    return {"confirm_id":token,"target":str(p),"snippet":snippet(m,host,name),"replaces_own_entry":bool(old),
            "note":"仅写入本工具箱的 MCP 条目，并备份原配置。写入后仍需在宿主中刷新并验证。"}

def apply(m,a):
    p=m.pending.pop(a.get("confirm_id"),None)
    if not p or p.get("type")!="agent_setup" or time.time()-p["created"]>600:raise ValueError("配置预览已失效，请重新预览")
    dest=target(m,p["host"],p["path"]);raw=dest.read_bytes() if dest.exists() else b""
    if sha(raw)!=p["sha"]:raise ValueError("配置文件已变化，请重新预览")
    dest.parent.mkdir(parents=True,exist_ok=True)
    backup=None
    if dest.exists():
        backup=dest.with_name(dest.name+".ppt-toolbox-"+secrets.token_hex(6)+".bak")
        backup.write_bytes(raw)
    staged=dest.with_name(dest.name+".ppt-toolbox-"+secrets.token_hex(6)+".tmp")
    try:
        staged.write_text(p["text"],encoding="utf-8")
        if sha(dest.read_bytes() if dest.exists() else b"")!=p["sha"]:raise ValueError("配置文件已变化")
        os.replace(staged,dest)
    finally:staged.unlink(missing_ok=True)
    m.store.event("agent.configured","已写入工具箱 MCP 配置",details={"host":p["host"],"path":str(dest)})
    return {"status":"configured","backup":str(backup) if backup else None,"target":str(dest),"host_verified":False}

def probe(m):
    cfg=connection(m)
    requests=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"PPTToolbox local probe","version":"1"}}},
              {"jsonrpc":"2.0","id":2,"method":"tools/list"},
              {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"toolbox_context","arguments":{}}}]
    env=os.environ.copy();env["PPT_TOOLBOX_CONNECTION_PROBE"]="1"
    proc=subprocess.run([cfg["command"],*cfg["args"]],input="".join(json.dumps(r)+"\n" for r in requests),
                        capture_output=True,text=True,encoding="utf-8",timeout=45,env=env,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if proc.returncode:raise ValueError("MCP 启动失败，请检查安装及数据目录")
    replies={r["id"]:r for r in (json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{"))}
    tools=replies[2]["result"]["tools"]
    context=replies[3]["result"].get("structuredContent")
    if not context or context.get("instance",{}).get("data_dir")!=str(m.data) or context["instance"].get("app_dir")!=str(m.root):
        raise ValueError("MCP 与当前界面使用的程序或数据目录不一致")
    result={"passed":True,"connection":cfg,"source_sha256":(m.distribution() or {}).get("source_sha256"),"version":(m.distribution() or {}).get("version"),
            "checked_at":time.time(),"tool_count":len(tools),"instance":context["instance"],
            "scope":"local_probe_only"}
    m.store.set("agent_probe",result)
    return result

def challenge(m,a):
    host=a.get("host","codex");p=target(m,host,a.get("path"))
    digest=connection_digest(p,host)
    token=secrets.token_urlsafe(18)
    m.store.set("agent_connection_challenge",{"token":token,"expires":time.time()+600,"host":host,
                "config_path":str(p) if p else None,"connection_sha256":digest,"instance":m.instance()})
    return {"prompt":"请使用已接入的 PPT 工具箱 MCP 调用 toolbox_verify_connection，参数为 "+
            json.dumps({"challenge":token},ensure_ascii=False)+"。再调用 toolbox_context，报告程序目录、数据目录和可用工具。此次只验证连接，不创建 PPT 或修改执行权限。",
            "expires_in_seconds":600}

def verify_connection(m,token,client,local_probe=False):
    if local_probe:raise ValueError("本机自检不能完成外部 Agent 验证")
    with m.store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT value FROM kv WHERE key='agent_connection_challenge'").fetchone()
        c=json.loads(row[0]) if row else None
        if not c or c["expires"]<time.time() or not secrets.compare_digest(c["token"],token):
            raise ValueError("验证口令已失效，请在设置页重新生成")
        identity=c.get("instance",{})
        if identity.get("app_dir")!=str(m.root) or identity.get("data_dir")!=str(m.data) or identity.get("distribution")!=m.distribution():
            raise ValueError("工具箱版本或位置已变化，请重新生成验证")
        if "connection_sha256" not in c:raise ValueError("验证口令来自旧版本，请在设置页重新生成")
        p=target(m,c["host"],c.get("config_path"))
        if connection_digest(p,c["host"])!=c["connection_sha256"]:raise ValueError("工具箱 MCP 配置已变化，请重新生成验证")
        result={"host":c["host"],"client":{k:str(client.get(k,""))[:120] for k in ("name","version")},
                "verified_at":time.time(),"app_dir":str(m.root),"data_dir":str(m.data),
                "source_sha256":(m.distribution() or {}).get("source_sha256"),"version":(m.distribution() or {}).get("version"),"connection_sha256":c["connection_sha256"],"config_path":c.get("config_path")}
        db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",("agent_connection_verified",json.dumps(result)))
        db.execute("DELETE FROM kv WHERE key='agent_connection_challenge'")
    return {"verified":True,"instance":m.instance(),"scope":"MCP connection verified; project execution remains separately authorized"}

def call(m,op,args):
    a=args or {}
    if op=='onboarding-prompt':
        from .agent_onboarding import prompt
        return prompt(m,a)
    if op=='live':
        from .agent_presence import status as live_status
        return live_status(m)
    if op=="status":return status(m,a.get("host","codex"),a.get("path"))
    if op=="plan":return plan(m,a)
    if op=="apply":return apply(m,a)
    if op=="probe":return probe(m)
    if op=="challenge":return challenge(m,a)
    raise ValueError("未知 Agent 接入操作")
