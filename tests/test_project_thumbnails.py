import io
import shutil
from types import SimpleNamespace
import pytest
from PIL import Image
from toolbox_manager.storage import Store
from toolbox_manager import project_thumbnails as covers

@pytest.fixture
def fixture(tmp_path):
    root = tmp_path/'project'
    (root/'input').mkdir(parents=True)
    source = root/'input'/'slide-001.png'
    Image.new('RGB', (2400, 1350), 'red').save(source)
    manager = SimpleNamespace(data=tmp_path/'data', store=Store(tmp_path/'data'))
    manager.store.set('workbench_projects', {'p': {'path': str(root), 'project_id': 'identity'}})
    return manager, root, source

def test_small_durable_cache_survives_missing_project_and_restart(fixture, monkeypatch):
    manager, root, _ = fixture
    result = covers.image(manager, 'p')
    im = Image.open(io.BytesIO(result))
    assert im.width <= 320 and im.height <= 200 and len(result) < 25000
    shutil.rmtree(root)
    covers._checked.clear()
    # A restarted manager can serve the persisted bytes with no project state.
    assert covers.image(SimpleNamespace(data=manager.data, store=manager.store), 'p') == result

def test_update_and_corruption_keep_last_good_image(fixture):
    manager, _, source = fixture
    before = covers.image(manager, 'p')
    Image.new('RGB', (1000, 800), 'blue').save(source)
    covers.refresh(manager, 'p', force=True)
    after = covers.image(manager, 'p')
    assert before != after
    source.write_bytes(b'broken image')
    covers.refresh(manager, 'p', force=True)
    assert covers.image(manager, 'p') == after

def test_unchanged_source_does_not_decode_again(fixture, monkeypatch):
    manager, _, _ = fixture
    expected = covers.image(manager, 'p')
    monkeypatch.setattr(Image, 'open', lambda *args: pytest.fail('decoded unchanged source'))
    covers.refresh(manager, 'p', force=True)
    assert covers.image(manager, 'p') == expected

def test_identity_isolation_and_no_reference(fixture, tmp_path):
    manager, _, _ = fixture
    assert covers.image(manager, 'p')
    manager.store.set('workbench_projects', {'p': {'path': str(tmp_path/'different'), 'project_id': 'identity'}})
    assert covers.image(manager, 'p') is None
    with pytest.raises(ValueError): covers.image(manager, '../p')

def test_transparency_composited_on_white(fixture):
    manager, _, source = fixture
    Image.new('RGBA', (320, 200), (0, 0, 0, 0)).save(source)
    im = Image.open(io.BytesIO(covers.image(manager, 'p')))
    assert min(im.getpixel((0, 0))) > 250

def test_http_auth_and_cached_missing_source(fixture):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from toolbox_manager.server import Handler
    manager, root, _ = fixture
    expected = covers.image(manager, 'p')
    shutil.rmtree(root)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.manager = manager; server.token = 'fixture'; server.origin = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        url = server.origin + '/api/project.thumbnail?project=p'
        with pytest.raises(HTTPError) as denied: urlopen(url)
        assert denied.value.code == 401
        with urlopen(Request(url, headers={'Authorization': 'Bearer fixture'})) as response:
            assert response.headers['Content-Type'] == 'image/jpeg'
            assert response.read() == expected
    finally:
        server.shutdown(); server.server_close(); thread.join()
