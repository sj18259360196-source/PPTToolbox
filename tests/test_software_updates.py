"""Update trust, interrupted transfers and owner-only installation boundaries."""
import base64
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from toolbox_manager.service import Manager
from toolbox_manager.software_updates import Updater, verified_manifest, safe_url, version, VERSION

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def update(tmp_path):
    manager=Manager(tmp_path/'data')
    key=Ed25519PrivateKey.generate()
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    cfg={'repository':'example/PPTToolbox','manifest':'PPTToolbox-update.json',
         'signature':'PPTToolbox-update.sig.json','trusted_keys':{'test':base64.b64encode(public).decode()}}
    next_version='.'.join(map(str,[*version(VERSION)[:2],version(VERSION)[2]+1]))
    payload=b'synthetic-installer-for-download-validation'*2000
    name=f'PPTToolbox-{next_version}-Setup.exe'
    url=f'https://github.com/example/PPTToolbox/releases/download/v{next_version}/{name}'
    manifest={'format':'ppttoolbox-update/1','product':'PPT Toolbox','version':next_version,
              'tag':'v'+next_version,'platform':'windows-x64','repository':cfg['repository'],
              'updater_version':1,'database_schema':{'minimum':1,'maximum':1},'notes':'Synthetic test release',
              'asset':{'name':name,'url':url,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}}
    def sign(value):
        raw=json.dumps(value).encode()
        return raw,json.dumps({'key_id':'test','signature':base64.b64encode(key.sign(raw)).decode()}).encode()
    raw,sig=sign(manifest)
    files={url:payload}
    prefix=f'https://github.com/example/PPTToolbox/releases/download/v{next_version}/'
    files[prefix+cfg['manifest']]=raw;files[prefix+cfg['signature']]=sig
    release={'tag_name':manifest['tag'],'draft':False,'prerelease':False,'assets':[
        {'name':name,'browser_download_url':u,'size':len(data),'digest':'sha256:'+hashlib.sha256(data).hexdigest()}
        for u,data in files.items() for name in [u.rsplit('/',1)[-1]]]}
    files['https://api.github.com/repos/example/PPTToolbox/releases/latest']=json.dumps(release).encode()
    class FakeTransport:
        def read(self,url):return files[url]
        def open(self,url):return io.BytesIO(files[url])
    launched=[]
    updater=Updater(manager,FakeTransport(),lambda *args:launched.append(args))
    updater.cfg=cfg
    updater._installed=lambda:True
    return updater,manifest,raw,sig,files,sign,launched


def finish(updater):
    updater.job.join(5)
    assert not updater.job.is_alive()
    return updater.status()


def ready(update):
    updater=update[0]
    updater.check();assert finish(updater)['phase']=='available'
    updater.download();assert finish(updater)['phase']=='ready'
    return updater


def test_download_reverify_and_install(update):
    updater=ready(update)
    assert updater.install()['phase']=='installing'
    assert len(update[-1])==1
    assert update[-1][0][0].read_bytes()==update[4][update[1]['asset']['url']]


def test_tampered_manifest_is_rejected_before_download(update):
    updater,manifest,raw,sig,_,_,_=update
    with pytest.raises(ValueError,match='签名'):
        verified_manifest(raw.replace(b'Synthetic',b'Malicious'),sig,updater.cfg)
    with pytest.raises(ValueError,match='签名'):
        verified_manifest(raw,json.dumps({'key_id':'unknown','signature':'x'}),updater.cfg)


@pytest.mark.parametrize('mutation',[
    {'platform':'linux'}, {'database_schema':{'minimum':2,'maximum':2}},
    {'repository':'attacker/toolbox'},{'updater_version':2},{'version':'1.21.0-beta'},
])
def test_signed_but_incompatible_metadata_is_rejected(update,mutation):
    updater,manifest,_,_,_,sign,_=update
    with pytest.raises(ValueError):verified_manifest(*sign({**manifest,**mutation}),updater.cfg)


@pytest.mark.parametrize('name',['../Setup.exe','C:/Setup.exe','PPTToolbox.exe:stream','other.exe'])
def test_signed_path_substitution_is_rejected(update,name):
    updater,manifest,_,_,_,sign,_=update
    changed={**manifest,'asset':{**manifest['asset'],'name':name}}
    with pytest.raises(ValueError):verified_manifest(*sign(changed),updater.cfg)


@pytest.mark.parametrize('url',['http://github.com/a/b','https://github.com.evil.test/a',
    'https://user:secret@github.com/a','https://127.0.0.1/private','https://github.com:8443/a'])
def test_redirect_boundary(url):
    with pytest.raises(ValueError):safe_url(url)


def test_download_corruption_removes_partial_file(update):
    updater,manifest,_,_,files,_,_=update
    updater.check();finish(updater)
    files[manifest['asset']['url']]=b'corrupt'
    updater.download();assert finish(updater)['phase']=='error'
    assert not list(updater.cache.glob('*.exe')) and not list(updater.cache.glob('*.part'))


def test_tampering_after_download_prevents_execution(update):
    updater=ready(update)
    (updater.cache/update[1]['asset']['name']).write_bytes(b'changed after validation')
    with pytest.raises(ValueError,match='变化'):updater.install()
    assert not update[-1]


def test_active_assistant_defers_installation_and_can_cancel(update):
    updater=ready(update)
    updater.manager.store.set('pptagent_tasks',[{'id':'active','status':'running'}])
    assert updater.install()['phase']=='deferred'
    assert not update[-1]
    assert updater.cancel()['phase']=='ready'
    updater.manager.store.set('pptagent_tasks',[])
    assert updater.install()['phase']=='installing'


def test_pending_project_call_prevents_installation(update):
    updater=ready(update)
    updater.manager.store.event('tool.started','Synthetic call',details={'call_id':'unfinished'})
    assert updater.install()['phase']=='deferred'
    assert not update[-1]


def test_higher_seen_version_prevents_rollback(update):
    updater=update[0]
    updater.manager.store.set('software_update_highest','99.0.0')
    updater.check();assert finish(updater)['phase']=='error'
    assert '降级' in updater.status()['error']


def test_github_asset_inventory_must_match_signed_manifest(update):
    updater,_,_,_,files,_,_=update
    url='https://api.github.com/repos/example/PPTToolbox/releases/latest'
    release=json.loads(files[url]);release['assets'][0]['size']+=1
    files[url]=json.dumps(release).encode()
    updater.check();assert finish(updater)['phase']=='error'


def test_network_failure_preserves_existing_project_and_settings(update):
    updater=update[0]
    settings=updater.manager.settings()
    updater.transport.read=lambda _: (_ for _ in ()).throw(OSError('offline'))
    updater.check();assert finish(updater)['phase']=='error'
    assert updater.manager.settings()==settings and not updater.cache.exists()


@pytest.mark.parametrize('identity',[None, 'different-process'])
def test_missing_or_reused_installer_process_allows_recovery(update,monkeypatch,identity):
    updater=ready(update)
    updater._set(phase='installing',install_started=time.time()-300,
                 install_helper={'pid':54321,'created':'original-process'})
    monkeypatch.setattr('toolbox_manager.software_updates.installer_process_identity',lambda _:identity)
    assert updater.status()['phase']=='error'
    assert '中断' in updater.status()['error']
    assert not update[-1]
    updater.check()
    assert finish(updater)['phase']=='available'


@pytest.mark.parametrize('identity',['original-process','unknown'])
def test_live_or_uninspectable_installer_is_not_restarted(update,monkeypatch,identity):
    updater=ready(update)
    updater._set(phase='installing',install_started=time.time()-300,
                 install_helper={'pid':54321,'created':'original-process'})
    monkeypatch.setattr('toolbox_manager.software_updates.installer_process_identity',lambda _:identity)
    assert updater.status()['phase']=='installing'
    with pytest.raises(ValueError,match='已有更新'):updater.check()
    assert not update[-1]


def test_crash_before_installer_pid_was_saved_is_recoverable(update):
    updater=ready(update)
    updater._set(phase='installing',install_started=time.time()-300,install_helper=None)
    assert updater.status()['phase']=='error'


def test_install_result_takes_precedence_over_exited_helper(update,monkeypatch):
    updater=ready(update)
    updater._set(phase='installing',install_started=time.time()-300,
                 install_helper={'pid':54321,'created':'original-process'})
    monkeypatch.setattr('toolbox_manager.software_updates.installer_process_identity',lambda _:None)
    (updater.cache/'install-result.json').write_text(json.dumps({'version':update[1]['version'],'exit_code':0}),encoding='utf-8')
    assert updater.status()['phase']=='installed'


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows helper process identity')
def test_current_process_has_stable_creation_identity():
    import os
    from toolbox_manager.software_updates import installer_process_identity
    first=installer_process_identity(os.getpid())
    assert first and first!='unknown'
    assert installer_process_identity(os.getpid())==first


def test_download_cancel_is_atomic(update):
    updater=update[0]
    updater.check();finish(updater)
    content=update[4][update[1]['asset']['url']]
    class Cancelling(io.BytesIO):
        def read(self,n=-1):
            chunk=super().read(n)
            updater.cancelled.set()
            return chunk
    updater.transport.open=lambda _:Cancelling(content)
    updater.download();assert finish(updater)['phase']=='cancelled'
    assert not list(updater.cache.glob('*.exe')) and not list(updater.cache.glob('*.part'))


def test_updater_not_exposed_to_agents_and_requires_owner_token(tmp_path):
    from toolbox_manager.server import LocalServer
    from toolbox_manager.mcp import MCP
    server=LocalServer(tmp_path/'ui')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        from types import SimpleNamespace
        assert all('software-update' not in name for name,_,_ in MCP.specs(SimpleNamespace(manager=server.manager)))
        for operation in ('status','install'):
            request=urllib.request.Request(server.origin+'/api/software-update.'+operation,
                data=b'{}' if operation=='install' else None,headers={'Content-Type':'application/json'})
            with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            assert error.value.code==401
        req=urllib.request.Request(server.origin+'/api/software-update.configure',data=b'{"automatic":false}',
            headers={'Content-Type':'application/json','Authorization':'Bearer '+server.token})
        assert json.load(urllib.request.urlopen(req))['result']['automatic'] is False
    finally:
        server.shutdown();server.server_close();thread.join(3)
