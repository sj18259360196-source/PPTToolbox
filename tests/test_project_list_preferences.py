from types import SimpleNamespace
from toolbox_manager.storage import Store
from toolbox_manager.projects import list_preferences

def test_default_and_persistence_across_manager_restart(tmp_path):
    manager=SimpleNamespace(store=Store(tmp_path/'data'))
    assert list_preferences(manager)=={'sort':'updated','category':'','only_delivery':False}
    expected={'sort':'oldest','category':'agent','only_delivery':True}
    assert list_preferences(manager,expected)==expected
    assert list_preferences(SimpleNamespace(store=Store(tmp_path/'data')))==expected
    assert list_preferences(manager,{'sort':'manual'})['sort']=='manual'

def test_invalid_preferences_fall_back_safely(tmp_path):
    manager=SimpleNamespace(store=Store(tmp_path/'data'))
    assert list_preferences(manager,{'sort':'unknown','category':[],'only_delivery':'false'})=={'sort':'updated','category':'','only_delivery':False}
