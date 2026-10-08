"""Shared source-pixel xyxy input for comparison and local-edit regression.

Accepts named comparison records, legacy four-integer boxes, and explicit deck
regions. No guessing xywh, coordinate scaling, or selecting one of many pages.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from common import read_json, write_json
from evidence_contract import normalize_regions


def select_region_rows(spec, slide_index=None):
    if slide_index is not None and (type(slide_index) is not int or slide_index < 1):
        raise ValueError('slide index must be a positive integer')
    if isinstance(spec, list) or spec is None:
        return spec
    if not isinstance(spec, dict):
        raise ValueError('Regions must be a list, {regions:[...]}, or {slides:[...]}')
    if 'slides' in spec:
        if set(spec) != {'slides'} or not isinstance(spec['slides'], list) or not spec['slides']:
            raise ValueError('Deck regions require a nonempty slides list only')
        pages = {}
        for row in spec['slides']:
            if not isinstance(row, dict) or set(row) != {'index', 'regions'}:
                raise ValueError('Deck region rows require index and regions')
            idx = row['index']
            if type(idx) is not int or idx < 1 or idx in pages:
                raise ValueError('Invalid or duplicate slide index in regions')
            if not isinstance(row['regions'], list):
                raise ValueError('Each page regions value must be a list')
            pages[idx] = row['regions']
        if slide_index is None:
            if len(pages) != 1:
                raise ValueError('Multiple pages in regions; pass --slide explicitly')
            slide_index = next(iter(pages))
        if slide_index not in pages:
            raise ValueError(f'No regions supplied for slide {slide_index}')
        return pages[slide_index]
    if 'regions' not in spec or set(spec) - {'regions', 'coordinate_format', 'units'}:
        raise ValueError('Region envelope keys: regions, coordinate_format, units')
    if spec.get('coordinate_format', 'xyxy') != 'xyxy':
        raise ValueError('Regions use xyxy, not xywh; convert explicitly')
    if spec.get('units', 'source_pixels') != 'source_pixels':
        raise ValueError('Regions use source_pixels; no automatic scaling')
    return spec['regions']


def normalize_region_input(spec, size, slide_index=None, require_nonempty=False):
    rows = select_region_rows(spec, slide_index)
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError('Regions must contain a list')
    converted = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, list):
            # The canonical validator checks integer types, bounds and positive area.
            converted.append({'id': f'region-{index:03}', 'bbox': row})
        else:
            converted.append(row)
    result = normalize_regions(converted, size)
    if require_nonempty and not result:
        raise ValueError('Explicit nonempty allowed edit regions are required')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--size', required=True, nargs=2, type=int, metavar=('WIDTH', 'HEIGHT'))
    p.add_argument('--slide', type=int)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        if min(a.size) <= 0:
            raise ValueError('Positive image dimensions required')
        result = normalize_region_input(read_json(a.spec), a.size, a.slide)
        if a.output.exists():
            raise ValueError('Choose a new output file; no overwrite')
        write_json(a.output, result)
        print(json.dumps({'status': 'completed', 'regions': result,
                          'coordinate_format': 'source_pixels_xyxy'}, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
