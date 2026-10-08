"""Installer source guards; real interactive acceptance is recorded separately."""
import json

from distribution import build_setup


def test_page_skip_does_not_expand_uninitialized_app(tmp_path, monkeypatch):
    bundle = tmp_path/"bundle"
    (bundle/"app").mkdir(parents=True)
    (bundle/"app/PRODUCT.json").write_text(json.dumps({"version": "1.10.1"}), encoding="utf-8")
    monkeypatch.setattr(build_setup, "verify", lambda _: {"PPTToolbox.exe": "fixture"})
    calls = []
    monkeypatch.setattr(build_setup.subprocess, "run", lambda argv, **kw: calls.append(argv))
    output = build_setup.build(bundle, tmp_path/"ISCC.exe", tmp_path/"scratch", tmp_path/"output")
    script = (tmp_path/"scratch/setup.iss").read_text(encoding="utf-8-sig")
    callback = script.split("function ShouldSkipPage(PageID: Integer): Boolean;", 1)[1].split(
        "function InstallPayload: String;", 1)[0]
    assert "{app}" not in callback
    assert "if PathsPage = nil then exit;" in callback
    assert callback.index("if PageID <> PathsPage.ID then exit;") < callback.index("FileExists(")
    assert "AddBackslash(WizardDirValue)" in callback
    assert output.name == "PPTToolbox-1.10.1-Setup.exe"
    assert len(calls) == 1
    assert 'DefaultDirName={localappdata}\\Programs\\PPTToolbox' in script
    assert "ExpandConstant('{app}')" in script, "Installation itself must retain the chosen destination"
