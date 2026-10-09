import json
import pytest
from test_tools import ROOT
from toolbox_manager.service import Manager
from toolbox_manager.mcp import MCP
from toolbox_manager.policy import PolicyDenied

def manager(tmp_path):
 return Manager(tmp_path/'data',root=ROOT,home=tmp_path/'home')

def test_fresh_session_direct_discovery_without_experience(tmp_path):
 m=manager(tmp_path)
 assert not m.settings()['agent_execution_enabled']
 assert 'graphics_illustration_guide' in {n for n,_,_ in MCP(tmp_path/'rpc',root=ROOT,home=tmp_path/'rh').specs()}
 context=m.context()
 assert context['agent_capabilities']['illustration']['requires_experience_lookup'] is False
 assert 'graphics_illustration_guide' in context['startup_prompt']
 result=m.graphics('illustration_guide',{})
 assert set(result['steps'])=={'pen','selection'}
 assert result['automatic_execution'] is False
 assert len(json.dumps(result).encode())<1024*1024
 assert not list(tmp_path.rglob('*.pptx'))

@pytest.mark.parametrize('route',['pen','selection'])
def test_current_contracts_and_real_managed_entry(tmp_path,route):
 from toolbox_manager.graphics import SPECS
 from toolbox_manager.icons.contracts import SPECS as ICONS
 m=manager(tmp_path)
 result=m.graphics('illustration_guide',{'route':route})
 assert list(result['steps'])==[route]
 for step in result['steps'][route]:
  family,op=step['tool_id'].split('.')
  assert step['input_schema']==(SPECS if family=='graphics' else ICONS)[op][1]
  assert step['input_schema']==m.tool(step['tool_id'])['input_schema']
  assert step['managed_argv_prefix']==m.tool(step['tool_id'])['managed_argv_prefix']
  assert step['template_status']=='requires_real_inputs_not_ready_to_execute'

def test_disabled_and_cli(tmp_path):
 m=manager(tmp_path)
 m.toggle('tool','graphics.fit_paths',False)
 result=m.graphics('illustration_guide',{'route':'pen'})
 assert next(s for s in result['steps']['pen'] if s['tool_id']=='graphics.fit_paths')['enabled'] is False
 req=tmp_path/'request.json';req.write_text('{}',encoding='utf-8')
 assert m.execute('graphics.illustration_guide',['--json',str(req)])['format']=='illustration-agent-guide/1'
 m.toggle('tool','graphics.illustration_guide',False)
 assert m.context()['agent_capabilities']['illustration']['enabled'] is False
 with pytest.raises(PolicyDenied):m.graphics('illustration_guide',{})

def test_ui_and_documentation_shipping():
 ui=(ROOT/'toolbox_manager/web/graphics.js').read_text(encoding='utf-8')
 for value in ['illustration-route','illustration-copy',"api('graphics.illustration_guide'",'illustration-agent-guide.md']:
  assert value in ui
 assert 'graphics_illustration_guide' in (ROOT/'scripts/workflow.py').read_text(encoding='utf-8')
 registry=json.loads((ROOT/'toolbox/registry.json').read_text(encoding='utf-8'))
 assert 'toolbox_manager/illustration_guide.py' in registry['internal_modules']
 assert 'graphics.illustration_guide' in {t['id'] for t in registry['tools']}
