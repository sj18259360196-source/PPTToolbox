import copy
from pathlib import Path
import sys

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from common import write_json
from native_practice import CANVAS, make_cases
from text_fit import _reference_ink, _shift, fit_ink, plan, evaluate


def test_translation_recovered_without_rescaling():
    a = np.zeros((25, 80), dtype=np.float32)
    a[8:18, 20:23] = 1
    a[15:18, 23:34] = .8
    shifted = _shift(a, 3, -2)
    assert fit_ink(a, shifted) == {"score": 1.0, "dx_px": -3, "dy_px": 2}


def test_empty_and_oversized_search_rejected():
    a = np.zeros((10, 10))
    with pytest.raises(ValueError, match="coverage"):
        fit_ink(a, a)
    with pytest.raises(ValueError, match="Bounded"):
        fit_ink(a, a, 13)


def test_solid_ink_and_colored_container_border():
    a = np.full((80, 130, 3), [247, 249, 252], dtype=np.uint8)
    a[7:73, 7:123] = [35, 136, 139]
    a[25:45, 30:34] = 255
    ink, color = _reference_ink(a, "FFFFFF")
    assert color == "FFFFFF"
    assert np.count_nonzero(ink) == 80
    assert ink[0, 0] == 0 and ink[30, 31] == 1


def test_low_contrast_is_not_fake_fit():
    a = np.full((30, 50, 3), 250, dtype=np.uint8)
    with pytest.raises(ValueError, match="contrast"):
        _reference_ink(a, "FFFFFF")


@pytest.mark.parametrize('background,foreground',[(250,0),(80,255)])
def test_small_background_noise_preserves_glyph_mask(background,foreground):
    rng=np.random.default_rng(912)
    a=np.clip(background+rng.integers(-4,5,size=(50,100,3)),0,255).astype(np.uint8)
    a[15:35,30:34]=foreground
    ink,color=_reference_ink(a,'000000' if foreground==0 else 'FFFFFF')
    assert color==('000000' if foreground==0 else 'FFFFFF')
    assert np.count_nonzero(ink)==80
    assert np.allclose(ink[15:35,30:34],1)


def test_wide_background_variation_remains_unmeasurable():
    rng=np.random.default_rng(912)
    a=rng.integers(90,240,size=(50,100,3),dtype=np.uint8)
    a[15:35,30:34]=0
    with pytest.raises(ValueError,match='non-flat'):
        _reference_ink(a,'000000')


def fixture(tmp_path):
    slide = make_cases()[5][0]
    scene = {"version": "1.0", "canvas": CANVAS, "slides": [slide]}
    write_json(tmp_path/"scene.json", scene)
    Image.new("RGB", (960, 540), "#F7F9FC").save(tmp_path/"ref.png")
    refs = {slide["id"]: str(tmp_path/"ref.png")}
    return scene, refs


def test_plan_is_bounded_and_does_not_modify_source(tmp_path):
    scene, refs = fixture(tmp_path)
    result = plan(tmp_path/"scene.json", refs, tmp_path/"plan", [-.5, 0, .5])
    assert result == {"targets": 5, "skipped": 1, "page_exports_planned": 3}
    import json
    assert json.loads((tmp_path/"scene.json").read_text(encoding="utf-8")) == scene
    with pytest.raises(FileExistsError):
        plan(tmp_path/"scene.json", refs, tmp_path/"plan", [0])


@pytest.mark.parametrize("deltas", [[], [True], [3], [0, 0], [float("nan")]])
def test_invalid_probe_grid_rejected(tmp_path, deltas):
    _, refs = fixture(tmp_path)
    with pytest.raises(ValueError, match="deltas"):
        plan(tmp_path/"scene.json", refs, tmp_path/"plan", deltas)


def test_fake_office_receipt_rejected(tmp_path):
    _, refs = fixture(tmp_path)
    plan(tmp_path/"scene.json", refs, tmp_path/"plan", [0])
    write_json(tmp_path/"office/office-render.json", {"status": "passed", "renderer": "fixture"})
    with pytest.raises(ValueError, match="real Office"):
        evaluate(tmp_path/"plan", tmp_path/"office", tmp_path/"result.json")
    assert not (tmp_path/"result.json").exists()
