"""Exercise registered help commands via the current managed entry, never task arguments."""
import json
import subprocess


def check(manager, ids):
    rows=[]
    for tid in ids:
        tool=manager.tool(tid)
        if tool['kind']!='python':
            rows.append({'id':tid,'status':'unsupported','scope':'Python CLI help only'});continue
        try:
            run=subprocess.run([*tool['managed_argv_prefix'],'--help'],capture_output=True,
                text=True,encoding='utf-8',timeout=25,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            value=json.loads(run.stdout)
            rows.append({'id':tid,'status':value.get('command_status','failed'),
                         'returncode':value.get('returncode',run.returncode),
                         'output_directory':value.get('output_directory'),
                         'error':value.get('stderr','')[-1200:]})
        except subprocess.TimeoutExpired:
            rows.append({'id':tid,'status':'timed_out','scope':'Help probe only; check managed logs'})
        except (ValueError,OSError) as exc:rows.append({'id':tid,'status':'failed','error':str(exc)[:1200]})
    return {'items':rows,'passed':all(r['status']=='completed' and r['returncode']==0 for r in rows),
            'scope':'Registered managed CLI startup only; no Office or project acceptance'}
