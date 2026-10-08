"""Explicit LibreOffice preview lane, separate from the Microsoft PowerPoint gate.

Local execution only. Uses an isolated LibreOffice profile and task-owned source
copy, then rasterizes a local PDF with PDFium. No installation/network/model API.
Receipts describe preview evidence; they never grant final Office acceptance.
"""
from __future__ import annotations
import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image
from common import read_json, write_json, sha256, staged_directory
from evidence_contract import (EVIDENCE_VERSION, reference_snapshot, indexed_rows,
    checked_file, safe_file, image_size, regions_by_index, validate_local_coverage,
    validate_comparison_chain)
from region_contract import normalize_region_input
from compare_images import compare

FORMAT = 'ppt-preview-render/1'
COMPARE_FORMAT = 'ppt-preview-comparison/1'
RENDERER = 'LibreOffice'
PREVIEW_LABEL = 'LIBREOFFICE PREVIEW / Office未验证'


def validate_preview_render(receipt_path, pptx, count, scene_path=None):
    receipt_path, pptx = Path(receipt_path), Path(pptx)
    report = read_json(receipt_path)
    expected = {'format': FORMAT, 'renderer': RENDERER, 'status': 'rendered_preview',
                'office_validation': 'not_run', 'accepted_for_office_gate': False,
                'pptx_sha256': sha256(pptx)}
    if scene_path is not None:
        expected['scene_sha256'] = sha256(scene_path)
    for key, value in expected.items():
        if report.get(key) != value:
            raise ValueError('Invalid/stale preview receipt: ' + key)
    rows = indexed_rows(report.get('slides'), count, 'Preview render')
    used = set()
    for row in rows.values():
        path = checked_file(receipt_path.parent, row.get('file'), row.get('sha256'), image=True)
        if path.as_posix().casefold() in used:
            raise ValueError('Preview pages reuse the same image')
        used.add(path.as_posix().casefold())
        if type(row.get('width')) is not int or type(row.get('height')) is not int:
            raise ValueError('Preview dimensions must be integers')
        if image_size(path, png_only=True) != [row['width'], row['height']]:
            raise ValueError('Preview dimensions mismatch')
    return report, rows


def render_preview(pptx, scene_path, outdir, executable=None, timeout=180):
    pptx, scene_path, outdir = Path(pptx).resolve(), Path(scene_path).resolve(), Path(outdir).resolve()
    if pptx.suffix.lower() != '.pptx':
        raise ValueError('Only PPTX input is supported')
    if type(timeout) is not int or not 10 <= timeout <= 600:
        raise ValueError('timeout must be an integer from 10 to 600 seconds')
    # Lazy import: PDFium and LibreOffice are not required for normal Office work.
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ValueError('Preview needs pypdfium2; no automatic install was attempted') from exc
    exe = str(executable) if executable else shutil.which('libreoffice') or shutil.which('soffice')
    if not exe or not Path(exe).is_file():
        raise ValueError('LibreOffice executable not found; supply --executable with an actual path')
    _, refs, _ = reference_snapshot(scene_path)
    ph, sh = sha256(pptx), sha256(scene_path)
    with staged_directory(outdir) as stage:
        with tempfile.TemporaryDirectory(prefix='ppt-local-preview-') as temp:
            temp = Path(temp)
            source = temp / 'candidate.pptx'
            shutil.copyfile(pptx, source)
            export = temp / 'export'; export.mkdir()
            profile = (temp / 'profile').as_uri()
            # Windows first-run LibreOffice may block an unprofiled --version call.
            # Use the same isolated profile as the real conversion and let the PDF
            # export, rather than a launcher banner, prove the renderer works.
            args = [exe, '-env:UserInstallation=' + profile, '--headless', '--convert-to',
                    'pdf:impress_pdf_Export', '--outdir', str(export), str(source)]
            completed = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', timeout=timeout, shell=False)
            pdf = export / 'candidate.pdf'
            if completed.returncode or not pdf.is_file():
                raise ValueError('LibreOffice preview export failed: ' +
                                 (completed.stderr or completed.stdout)[-2000:])
            rows = []
            with pdfium.PdfDocument(pdf) as doc:
                if len(doc) != len(refs):
                    raise ValueError('Preview PDF page count differs from reference list')
                for i, (page, ref) in enumerate(zip(doc, refs), 1):
                    w, h = ref['size']
                    bitmap = page.render(scale=max(w/page.get_width(), h/page.get_height()))
                    im = bitmap.to_pil().convert('RGB')
                    bitmap.close()
                    page.close()
                    raster_size = list(im.size)
                    if im.size != (w, h):
                        if abs(im.width-w) > 1 or abs(im.height-h) > 1:
                            raise ValueError('Unexpected PDF raster dimensions')
                        # Only compensate explicitly recorded one-pixel raster rounding.
                        im = im.resize((w, h), Image.Resampling.LANCZOS)
                    name = f'slide-{i:03}.png'; im.save(stage/name)
                    rows.append({'index': i, 'file': name, 'sha256': sha256(stage/name),
                                 'width': w, 'height': h, 'raster_original_size': raster_size,
                                 'rounding_resized': raster_size != [w, h]})
            report = {'format': FORMAT, 'status': 'rendered_preview', 'renderer': RENDERER,
                      'renderer_version': 'validated by isolated PDF conversion', 'rasterizer': 'PDFium ' + str(pdfium.PDFIUM_INFO),
                      'office_validation': 'not_run', 'accepted_for_office_gate': False,
                      'pptx_sha256': ph, 'scene_sha256': sh, 'slides': rows,
                      'pdf_sha256': sha256(pdf), 'method': 'PPTX copy -> LibreOffice PDF -> PNG',
                      'scope': 'Local preview only. Different font/effect rendering is possible; not Office validation.'}
            (stage/'render-command.log').write_text(
                json.dumps({'argv': args, 'returncode': completed.returncode,
                            'stdout': completed.stdout, 'stderr': completed.stderr},
                           ensure_ascii=False, indent=2), encoding='utf-8')
        if sha256(pptx) != ph or sha256(scene_path) != sh:
            raise ValueError('Source changed during preview; no receipt published')
        write_json(stage/'preview-render.json', report)
        validate_preview_render(stage/'preview-render.json', pptx, len(refs), scene_path)
    return report


def import_preview(receipt_path, pptx, scene_path, destination):
    scene, refs, _ = reference_snapshot(scene_path)
    report, rows = validate_preview_render(receipt_path, pptx, len(refs), scene_path)
    report = copy.deepcopy(report)
    with staged_directory(destination) as stage:
        new = []
        for idx, row in sorted(rows.items()):
            name = f'slide-{idx:03}.png'
            shutil.copyfile(safe_file(Path(receipt_path).parent, row['file']), stage/name)
            new.append({**row, 'file': name})
        report['slides'] = new
        report['import_scope'] = 'File identity checked; remote execution itself is not independently attested.'
        write_json(stage/'preview-render.json', report)
        validate_preview_render(stage/'preview-render.json', pptx, len(refs), scene_path)
    return Path(destination)/'preview-render.json'


def compare_preview(scene_path, pptx, render_path, regions_path, outdir):
    scene_path, pptx, render_path, outdir = map(Path, (scene_path, pptx, render_path, outdir))
    scene, refs, mh = reference_snapshot(scene_path)
    _, rows = validate_preview_render(render_path, pptx, len(refs), scene_path)
    original_hashes = [sha256(p) for p in (scene_path, pptx, render_path, regions_path)]
    spec = regions_by_index(read_json(regions_path), len(refs))
    plans = []
    for ref, slide in zip(refs, scene['slides']):
        row = rows[ref['index']]
        if ref['size'] != [row['width'], row['height']]:
            raise ValueError('Preview must be rendered at reference dimensions; no silent resizing')
        regions = normalize_region_input(spec.get(ref['index'], []), ref['size'])
        required = validate_local_coverage(scene, slide, ref['size'], regions)
        plans.append((ref, slide, row, regions, required))
    with staged_directory(outdir) as stage:
        pages = []
        for ref, slide, row, regions, required in plans:
            idx = ref['index']; page_dir = stage/f'slide-{idx:03}'
            result = compare(safe_file(scene_path.parent, ref['path']),
                             safe_file(render_path.parent, row['file']), page_dir, regions,
                             right_label=PREVIEW_LABEL)
            full = result['regions'][0]
            pages.append({'index': idx, 'slide_id': slide['id'],
                          'reference_sha256': ref['sha256'], 'render_sha256': row['sha256'],
                          'comparison_json': (page_dir/'comparison.json').relative_to(stage).as_posix(),
                          'comparison_json_sha256': sha256(page_dir/'comparison.json'),
                          'full_side_by_side': (page_dir/full['side_by_side']).relative_to(stage).as_posix(),
                          'full_side_by_side_sha256': full['side_by_side_sha256'],
                          'local_regions': regions, 'required_review': required, 'resized_render': False})
        if [sha256(p) for p in (scene_path, pptx, render_path, regions_path)] != original_hashes:
            raise ValueError('Input changed during preview comparison')
        _, current_refs, current_mh = reference_snapshot(scene_path)
        if refs != current_refs or mh != current_mh:
            raise ValueError('Reference changed during preview comparison')
        report = {'format': COMPARE_FORMAT, 'evidence_version': EVIDENCE_VERSION,
                  'status': 'prepared_preview', 'renderer': RENDERER,
                  'office_validation': 'not_run', 'accepted_for_office_gate': False,
                  'pptx_sha256': sha256(pptx), 'scene_sha256': sha256(scene_path),
                  'render_receipt_sha256': sha256(render_path), 'reference_manifest_sha256': mh,
                  'references': refs, 'slides': pages, 'regions_sha256': sha256(regions_path),
                  'scope': 'Preview files prepared; actual visual review still required. Not a final acceptance.'}
        write_json(stage/'deck-preview.json', report)
        validate_preview_comparisons(stage/'deck-preview.json', scene_path, pptx, render_path, regions_path)
    return report


def validate_preview_comparisons(comparison_path, scene_path, pptx, render_path, regions_path=None):
    scene, refs, mh = reference_snapshot(scene_path)
    _, rows = validate_preview_render(render_path, pptx, len(refs), scene_path)
    expected = {'format': COMPARE_FORMAT, 'evidence_version': EVIDENCE_VERSION,
                'status': 'prepared_preview', 'renderer': RENDERER,
                'office_validation': 'not_run', 'accepted_for_office_gate': False,
                'pptx_sha256': sha256(pptx), 'scene_sha256': sha256(scene_path),
                'render_receipt_sha256': sha256(render_path), 'reference_manifest_sha256': mh,
                'references': refs}
    if regions_path:
        expected['regions_sha256'] = sha256(regions_path)
    result = validate_comparison_chain(Path(comparison_path), scene, refs, rows, expected)
    for page in result['receipt']['slides']:
        detail = read_json(safe_file(Path(comparison_path).parent, page['comparison_json']))
        if detail.get('labels', {}).get('right') != PREVIEW_LABEL:
            raise ValueError('Preview comparison is not labelled with the actual renderer')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for cmd in ('render', 'compare'):
        ap = sub.add_parser(cmd)
        ap.add_argument('--scene', required=True, type=Path)
        ap.add_argument('--pptx', required=True, type=Path)
        ap.add_argument('--outdir', required=True, type=Path)
        if cmd == 'render':
            ap.add_argument('--executable', type=Path)
            ap.add_argument('--timeout', type=int, default=180)
        else:
            ap.add_argument('--render', required=True, type=Path)
            ap.add_argument('--regions', required=True, type=Path)
    a = p.parse_args()
    try:
        report = (render_preview(a.pptx, a.scene, a.outdir, a.executable, a.timeout)
                  if a.command == 'render' else compare_preview(a.scene, a.pptx, a.render, a.regions, a.outdir))
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    except Exception as exc:
        print(json.dumps({'status': 'preview_failed', 'office_validation': 'not_run',
                          'error': str(exc)}, ensure_ascii=False)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
