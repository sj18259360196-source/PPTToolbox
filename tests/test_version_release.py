"""Release identity and extension switching use isolated metadata and stores."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.release_info import VERSION, check_release, sync_release
from toolbox_manager import VERSION as MANAGER_VERSION, API_VERSION
from toolbox_manager.service import Manager
from toolbox_manager.storage import Store
from toolbox_manager import releases
from toolbox_manager.packages import compatibility

ROOT=Path(__file__).resolve().parents[1]


def test_release_identity_shared_by_packaging_runtime_and_plugin():
    from scripts.common import VERSION as CORE_VERSION
    from distribution.build_portable import PRODUCT_VERSION, release_contract
    assert check_release(ROOT)['version']==VERSION==CORE_VERSION==MANAGER_VERSION==PRODUCT_VERSION
    contract=release_contract(ROOT)
    assert contract['core_version']==contract['manager_version']==VERSION
    assert json.loads((ROOT/'.codex-plugin/plugin.json').read_text('utf-8'))['version']==VERSION
    assert API_VERSION=='ppt-toolbox-manager/1'


def test_stale_metadata_rejected_before_packaging_and_sync_is_explicit(tmp_path):
    (tmp_path/'release.json').write_text(json.dumps({'product':'PPT Toolbox','version':'9.8.7'}),encoding='utf-8')
    (tmp_path/'SKILL.md').write_text('---\nmetadata:\n  version: "1.3.1"\n---\nKeep this body.\n',encoding='utf-8')
    plugin=tmp_path/'.codex-plugin/plugin.json';plugin.parent.mkdir()
    plugin.write_text('{"name":"fixture","version":"1.4.1"}',encoding='utf-8')
    with pytest.raises(ValueError,match='stale'):check_release(tmp_path)
    sync_release(tmp_path)
    assert check_release(tmp_path)['version']=='9.8.7'
    assert (tmp_path/'SKILL.md').read_text('utf-8').endswith('Keep this body.\n')
    assert json.loads(plugin.read_text('utf-8'))=={'name':'fixture','version':'9.8.7'}


def test_software_history_separate_deduplicated_and_records_return_to_old_build(tmp_path):
    store=Store(tmp_path/'data')
    releases.observe(store,None)
    assert releases.history(store)==[]
    old={'version':'1.20.4','source_sha256':'a'*64}
    new={'version':VERSION,'source_sha256':'b'*64}
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:releases.observe(store,old),range(8)))
    assert len(releases.history(store))==1
    releases.observe(store,new);releases.observe(store,old)
    assert [h['version'] for h in releases.history(store)]==['1.20.4',VERSION,'1.20.4']
    assert releases.history(store)[-1]['kind']=='first_observed'
    with store.db() as db:assert db.execute('SELECT count(*) FROM activations').fetchone()[0]==0


def test_unchanged_software_startup_needs_no_writer(tmp_path):
    import sqlite3
    store=Store(tmp_path/'data');info={'version':VERSION,'source_sha256':'a'*64}
    releases.observe(store,info)
    with sqlite3.connect(store.path,timeout=0) as db:
        db.execute('BEGIN IMMEDIATE')
        releases.observe(store,info)
        db.rollback()


def test_source_preview_does_not_claim_software_install(tmp_path):
    manager=Manager(tmp_path/'data',root=ROOT)
    result=manager.versions()
    assert result['product_version']==VERSION and result['software_history']==[]
    assert manager.package()['version']==VERSION


@pytest.mark.parametrize('requirements,expected',[
    ({},'undeclared'),
    ({'compatibility':{'manager_api':API_VERSION}},'compatible'),
    ({'compatibility':{'manager_api':'ppt-toolbox-manager/99'}},'incompatible'),
    ({'compatibility':{'min_product_version':VERSION}},'compatible'),
    ({'compatibility':{'max_product_version_exclusive':VERSION}},'incompatible'),
    ({'compatibility':{'min_product_version':'99.0.0'}},'incompatible'),
])
def test_extension_compatibility(requirements,expected):
    assert compatibility(requirements)['status']==expected


@pytest.mark.parametrize('value',[{},[],{'typo':'x'},{'manager_api':[]},{'min_product_version':'new'},
                                     {'min_product_version':'3.0.0','max_product_version_exclusive':'2.0.0'}])
def test_invalid_extension_constraints_rejected(value):
    with pytest.raises(ValueError):compatibility({'compatibility':value})


def test_incompatible_extension_cannot_be_activated(tmp_path):
    from test_manager import package_bytes
    manager=Manager(tmp_path/'data',root=ROOT)
    plan=manager.prepare_import(package_bytes())
    plan_id=plan['confirm_id']
    manager.pending[plan_id]['compatibility']={'status':'incompatible','message':'incompatible fixture'}
    with pytest.raises(ValueError,match='incompatible'):manager.commit_import(plan_id)
    assert len(manager.packages())==1


def test_extension_activation_rechecks_compatibility_after_software_change(tmp_path,monkeypatch):
    import io,zipfile
    from test_manager import package_bytes
    from toolbox_manager import packages
    original=package_bytes();out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(out,'w') as target:
        for name in source.namelist():
            data=source.read(name)
            if name.endswith('MANIFEST.json'):
                value=json.loads(data);value['compatibility']={'max_product_version_exclusive':'2.0.0'}
                data=json.dumps(value).encode()
            target.writestr(name,data)
    manager=Manager(tmp_path/'data',root=ROOT)
    plan=manager.prepare_import(out.getvalue());assert plan['compatibility']['status']=='compatible'
    package=manager.commit_import(plan['confirm_id'])
    manager.trust(package['id'],True);manager.toggle('package','',True,package['id'])
    monkeypatch.setattr(packages,'VERSION','2.0.0')
    with pytest.raises(ValueError,match='不兼容'):manager.activate(package['id'])
    assert manager.package()['id']=='builtin'


def test_old_builtin_overrides_survive_version_refresh(tmp_path):
    manager=Manager(tmp_path/'data',root=ROOT)
    manager.save_settings({'revision':0,'values':{'theme':'dark'}})
    original=manager.document('SKILL.md')
    manager.save_document('SKILL.md',original['content']+'\nPreserved user text.\n',0)
    with manager.store.db() as db:db.execute('UPDATE packages SET version=? WHERE id=?',('1.3.1','builtin'))
    newer=Manager(tmp_path/'data',root=ROOT)
    assert newer.package()['version']==VERSION
    assert newer.settings()['theme']=='dark'
    assert newer.document('SKILL.md')['content'].endswith('Preserved user text.\n')
