"""Fail-closed evidence identity and coverage gate, not a visual/semantic truth oracle."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from common import read_json, sha256, write_json, STATUSES
from evidence_contract import (EVIDENCE_VERSION, nonempty, checked_file, reference_snapshot,
                               validate_render, validate_comparisons, required_review, indexed_rows)

REQUIRED = ['content_source', 'relationships', 'visual_full', 'visual_local', 'editable_behavior',
            'raster_scope', 'text_geometry', 'reproducibility']
ALWAYS = {'content_source', 'visual_full', 'editable_behavior', 'raster_scope', 'text_geometry', 'reproducibility'}


def verify(pptx: Path, audit_path: Path, render_path: Path | None, review_path: Path | None,
           comparison_path: Path | None = None, scene_path: Path | None = None):
    expected = sha256(pptx); issues = []; pending = []
    audit = read_json(audit_path); scene = None; comparisons = None; requirements = {}
    if audit.get('pptx_sha256') != expected:
        issues.append('Audit is for a different PPTX')
    if audit.get('checks', {}).get('package', {}).get('status') != 'passed':
        issues.append('Package audit did not pass')
    if audit.get('checks', {}).get('native_content', {}).get('status') != 'passed':
        pending.append('PPT-to-scene content/type check missing or failed')
    for name, check in audit.get('checks', {}).items():
        if check.get('status') == 'failed':
            issues.append('Failed automatic check: ' + name)
    if audit.get('checks', {}).get('chart_cache', {}).get('status') not in {'passed', 'not_applicable'}:
        pending.append('Chart cache audit incomplete')
    slide_count = len(audit.get('slides', [])); indices = set(range(1, slide_count + 1))
    if slide_count == 0:
        issues.append('Audit contains no slides')
    if scene_path and scene_path.is_file():
        try:
            scene, refs, _ = reference_snapshot(scene_path)
            if audit.get('scene_sha256') != sha256(scene_path):
                issues.append('Audit is for a different scene')
            if len(refs) != slide_count:
                issues.append('Reference/scene and audit slide counts differ')
            requirements = {i: required_review(s) for i, s in enumerate(scene['slides'], 1)}
        except Exception as exc:
            issues.append('Invalid scene/reference binding: ' + str(exc))
    else:
        pending.append('Current scene missing; supply --scene. Legacy evidence cannot bypass source validation')
    if render_path and render_path.is_file():
        try:
            validate_render(render_path, pptx, slide_count)
        except Exception as exc:
            issues.append('Invalid Office evidence: ' + str(exc))
    else:
        pending.append('PowerPoint render receipt missing')
    if comparison_path and comparison_path.is_file():
        if scene is not None and render_path and render_path.is_file():
            try:
                comparisons = validate_comparisons(comparison_path, scene_path, pptx, render_path)
            except Exception as exc:
                issues.append('Invalid comparison evidence: ' + str(exc))
        else:
            pending.append('Cannot validate comparison provenance without current scene and Office receipt')
    else:
        pending.append('Mandatory full-slide side-by-side comparison receipt missing')
    if review_path and review_path.is_file():
        review = read_json(review_path)
        if review.get('pptx_sha256') != expected:
            issues.append('Review is for a different PPTX')
        if scene is not None:
            if not review.get('scene_sha256'):
                pending.append('Review scene binding missing')
            elif review['scene_sha256'] != sha256(scene_path):
                issues.append('Review is for a different scene')
        if comparison_path and comparison_path.is_file():
            if not review.get('comparison_sha256'):
                pending.append('Review comparison binding missing; view the current comparisons before signing')
            elif review['comparison_sha256'] != sha256(comparison_path):
                issues.append('Review is for a different comparison receipt')
        if not nonempty(review.get('reviewer')):
            pending.append('Review author absent')
        needed_local = bool(comparisons and comparisons['local_paths']) or any(r['local_objects'] for r in requirements.values())
        needed_rel = {(idx, oid) for idx, r in requirements.items() for oid in r['relationship_objects']}
        for name in REQUIRED:
            check = review.get('checks', {}).get(name, {})
            status = check.get('status', 'not_run')
            if status not in STATUSES:
                issues.append('Invalid review status ' + name); continue
            if status == 'failed':
                issues.append('Failed review ' + name); continue
            if status not in {'passed', 'not_applicable'}:
                pending.append('Review incomplete ' + name); continue
            if status == 'not_applicable':
                if name in ALWAYS or name == 'visual_local' and needed_local or name == 'relationships' and needed_rel:
                    issues.append('Required review cannot be not_applicable: ' + name)
                if not nonempty(check.get('note')):
                    pending.append('No non-applicability reason ' + name)
                continue
            if not nonempty(check.get('note')) or not check.get('evidence'):
                pending.append('Passed review lacks evidence/note ' + name)
            slides = check.get('slides', [])
            if (not isinstance(slides, list) or any(type(i) is not int or i not in indices for i in slides)
                    or len(slides) != len(set(slides))):
                issues.append('Invalid/duplicate review slide coverage: ' + name)
            elif name in {'content_source', 'visual_full', 'raster_scope', 'text_geometry'} and set(slides) != indices:
                pending.append('Review does not cover all slides ' + name)
            files = set()
            if not isinstance(check.get('evidence', []), list):
                issues.append('Review evidence must be a list: ' + name); continue
            for item in check.get('evidence', []):
                try:
                    files.add(checked_file(review_path.parent, item.get('file'), item.get('sha256')))
                except Exception as exc:
                    issues.append(f'Invalid review evidence {name}: {exc}')
            if name == 'visual_full' and comparisons:
                if not set(comparisons['full_paths'].values()) <= files:
                    pending.append('Full visual review must cite all actual full side-by-side files')
            if name == 'visual_local' and comparisons:
                reviewed = {}; rows = check.get('regions', [])
                if not isinstance(rows, list):
                    issues.append('Local review regions must be a list'); rows = []
                for row in rows:
                    if not isinstance(row, dict) or type(row.get('index')) is not int or not nonempty(row.get('id')):
                        issues.append('Invalid local review region row'); continue
                    key = (row['index'], row['id'])
                    if key in reviewed or key not in comparisons['local_paths']:
                        issues.append('Unknown/duplicate local review region: ' + str(key)); continue
                    reviewed[key] = row
                    expected_region = comparisons['local_paths'][key]
                    ids = row.get('object_ids')
                    if (not isinstance(ids, list) or any(not nonempty(i) for i in ids) or len(ids) != len(set(ids))
                            or set(ids) != set(expected_region['object_ids'])):
                        issues.append('Local review object coverage differs: ' + str(key))
                    if not nonempty(row.get('note')):
                        pending.append('Local review missing object-level observation: ' + str(key))
                    if expected_region['file'] not in files:
                        pending.append('Local review does not cite its side-by-side image: ' + str(key))
                    if row['index'] not in slides:
                        pending.append('Local review slide coverage incomplete: ' + str(key))
                if set(reviewed) != set(comparisons['local_paths']):
                    pending.append('Not all requested/mandatory local regions have been reviewed')
            if name == 'relationships' and requirements:
                covered = set(); rows = check.get('objects', [])
                if not isinstance(rows, list):
                    issues.append('Relationship review objects must be a list'); rows = []
                for row in rows:
                    if not isinstance(row, dict) or type(row.get('index')) is not int or not nonempty(row.get('object_id')):
                        issues.append('Invalid relationship review row'); continue
                    key = (row['index'], row['object_id'])
                    if key in covered or key not in needed_rel:
                        issues.append('Unknown/duplicate relationship object: ' + str(key)); continue
                    covered.add(key)
                    if not nonempty(row.get('note')):
                        pending.append('Relationship object missing observation: ' + str(key))
                    if row['index'] not in slides:
                        pending.append('Relationship review slide coverage incomplete: ' + str(key))
                    if comparisons and not comparisons['relation_paths'].get(key, set()) & files:
                        pending.append('Relationship review lacks associated local side-by-side: ' + str(key))
                if covered != needed_rel:
                    pending.append('Relationship review missing required objects')
    else:
        pending.append('Source/visual/editability review missing')
    status = 'failed' if issues else 'blocked' if pending else 'passed'
    return {'evidence_version': EVIDENCE_VERSION, 'status': status, 'pptx_sha256': expected,
            'scene_sha256': sha256(scene_path) if scene_path and scene_path.is_file() else None,
            'issues': issues, 'pending': pending,
            'scope': 'Current-file identities and declared object/region coverage only. No proof of actual Office execution, honest review, or visual fidelity from receipts alone.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('pptx', type=Path); ap.add_argument('--scene', type=Path, required=True)
    ap.add_argument('--audit', type=Path, required=True); ap.add_argument('--render', type=Path)
    ap.add_argument('--review', type=Path); ap.add_argument('--comparison', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    try:
        result = verify(args.pptx, args.audit, args.render, args.review, args.comparison, args.scene)
        write_json(args.out, result); print(f"Delivery gate: {result['status']}")
        return {'passed': 0, 'failed': 1, 'blocked': 3}[result['status']]
    except Exception as exc:
        print(f'Gate failed: {exc}', file=sys.stderr); return 2

if __name__ == '__main__':
    raise SystemExit(main())
