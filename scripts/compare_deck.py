"""Produce full/local comparisons bound to current scene, PPTX, references and Office PNGs."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from common import read_json, sha256, staged_directory, write_json
from compare_images import compare
from region_contract import normalize_region_input
from evidence_contract import (EVIDENCE_VERSION, reference_snapshot, validate_render, safe_file,
                               regions_by_index, normalize_regions, validate_local_coverage)


def compare_deck(scene_path: Path, render_receipt: Path, outdir: Path, regions_path: Path | None = None,
                 resize_render=False, region_scale=2, pptx_path: Path | None = None):
    if pptx_path is None:
        raise ValueError('Supply the actual candidate PPTX with --pptx; a receipt hash alone is insufficient')
    if type(region_scale) is not int or not 1 <= region_scale <= 8:
        raise ValueError('region_scale must be an integer from 1 to 8')
    scene_path, render_receipt, pptx_path = Path(scene_path), Path(render_receipt), Path(pptx_path)
    scene_hash, receipt_hash, pptx_hash = sha256(scene_path), sha256(render_receipt), sha256(pptx_path)
    region_hash = sha256(regions_path) if regions_path else None
    scene, refs, manifest_hash = reference_snapshot(scene_path)
    receipt, rendered = validate_render(render_receipt, pptx_path, len(refs))
    region_spec = regions_by_index(read_json(regions_path) if regions_path else None, len(refs))
    plans = []
    for ref, slide in zip(refs, scene['slides']):
        idx = ref['index']; row = rendered[idx]
        if ref['size'] != [row['width'], row['height']] and not resize_render:
            raise ValueError(f'Image size mismatch on slide {idx}; re-export at reference dimensions')
        regions = normalize_region_input(region_spec.get(idx, []), ref['size'])
        required = validate_local_coverage(scene, slide, ref['size'], regions)
        plans.append((ref, slide, row, regions, required))
    # Prevalidation of the entire deck finishes before writing any comparison image.
    with staged_directory(outdir) as stage:
        rows = []
        for ref, slide, rendered_row, regions, required in plans:
            idx = ref['index']
            reference = safe_file(scene_path.parent, ref['path'])
            render = safe_file(render_receipt.parent, rendered_row['file'])
            page_out = stage / f'slide-{idx:03}'
            result = compare(reference, render, page_out, regions, resize_render, region_scale)
            full = result['regions'][0]
            rows.append({'index': idx, 'slide_id': slide['id'],
                         'reference_sha256': ref['sha256'], 'render_sha256': rendered_row['sha256'],
                         'comparison_json': (page_out / 'comparison.json').relative_to(stage).as_posix(),
                         'comparison_json_sha256': sha256(page_out / 'comparison.json'),
                         'full_side_by_side': (page_out / full['side_by_side']).relative_to(stage).as_posix(),
                         'full_side_by_side_sha256': full['side_by_side_sha256'],
                         'local_regions': regions, 'required_review': required,
                         'resized_render': result['resized_render']})
        _, current_refs, current_manifest = reference_snapshot(scene_path)
        if (sha256(scene_path) != scene_hash or sha256(pptx_path) != pptx_hash
                or sha256(render_receipt) != receipt_hash or current_refs != refs or current_manifest != manifest_hash
                or regions_path and sha256(regions_path) != region_hash):
            raise ValueError('An input changed during deck comparison; no receipt published')
        validate_render(render_receipt, pptx_path, len(refs))
        report = {'evidence_version': EVIDENCE_VERSION, 'status': 'passed',
                  'scope': 'File identities and declared local object coverage; NOT visual acceptance',
                  'pptx_sha256': pptx_hash, 'scene_sha256': scene_hash,
                  'render_receipt_sha256': receipt_hash, 'reference_manifest_sha256': manifest_hash,
                  'regions_spec_sha256': region_hash, 'references': refs, 'slides': rows}
        write_json(stage / 'deck-comparison.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('scene', type=Path); ap.add_argument('--pptx', required=True, type=Path)
    ap.add_argument('--render', required=True, type=Path); ap.add_argument('--outdir', required=True, type=Path)
    ap.add_argument('--regions', type=Path); ap.add_argument('--resize-render', action='store_true')
    ap.add_argument('--region-scale', type=int, default=2)
    args = ap.parse_args()
    try:
        compare_deck(args.scene.resolve(), args.render.resolve(), args.outdir.resolve(),
                     args.regions.resolve() if args.regions else None, args.resize_render, args.region_scale,
                     args.pptx.resolve())
    except Exception as exc:
        print(f'Deck compare failed: {exc}', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
