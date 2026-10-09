"""Create labeled equal-scale comparison evidence. No automatic visual acceptance."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from common import read_json, sha256, staged_directory, write_json
from evidence_contract import EVIDENCE_VERSION, normalize_regions


def rgb(path):
    with Image.open(path) as src:
        image = src.convert('RGBA')
        bg = Image.new('RGBA', image.size, 'white')
        bg.alpha_composite(image)
        return bg.convert('RGB')


def _label_font():
    # Use local fonts only. No font files are copied or distributed.
    candidates = [Path('C:/Windows/Fonts/msyh.ttc'),
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), 16), True
            except OSError:
                pass
    return ImageFont.load_default(), False


def _labelled_side(a, b, left_label=None, right_label=None, display_scale=1):
    if type(display_scale) is not int or not 1 <= display_scale <= 8:
        raise ValueError('display_scale must be an integer from 1 to 8')
    if display_scale != 1:
        size = (a.width * display_scale, a.height * display_scale)
        a = a.resize(size, Image.Resampling.LANCZOS)
        b = b.resize(size, Image.Resampling.LANCZOS)
    font, cjk = _label_font()
    left_label = left_label or ('REFERENCE / 原设计稿' if cjk else 'REFERENCE')
    right_label = right_label or ('POWERPOINT / 可编辑成片' if cjk else 'POWERPOINT')
    header = max(34, round(a.height * .045)); gutter = max(10, round(a.width * .012))
    side = Image.new('RGB', (a.width * 2 + gutter, a.height + header), 'white')
    side.paste(a, (0, header)); side.paste(b, (a.width + gutter, header))
    # Confine labels to each column, so small test images cannot overwrite the other label.
    for start, label in [(0, left_label), (a.width + gutter, right_label)]:
        tile = Image.new('RGB', (a.width, header), 'white')
        ImageDraw.Draw(tile).text((8, max(2, (header - 20) // 2)), label, fill='black', font=font)
        side.paste(tile, (start, 0))
    x = a.width + gutter // 2
    ImageDraw.Draw(side).line((x, 0, x, side.height), fill=(140, 140, 140), width=max(1, gutter // 5))
    return side


def compare(reference: Path, rendered: Path, outdir: Path, regions=None, resize_render=False, region_scale=1, *, slide_index=None, left_label=None, right_label=None, include_source_crops=False):
    reference, rendered, outdir = Path(reference), Path(rendered), Path(outdir)
    if type(region_scale) is not int or not 1 <= region_scale <= 8:
        raise ValueError('region_scale must be an integer from 1 to 8')
    rh, oh = sha256(reference), sha256(rendered)
    ref = rgb(reference); out = rgb(rendered); original = out.size
    from region_contract import normalize_region_input
    clean_regions = normalize_region_input(regions, ref.size, slide_index)  # Validate ALL before any output.
    if ref.size != out.size:
        if not resize_render:
            raise ValueError(f'Image size mismatch {ref.size} != {out.size}; align exports explicitly, or use --resize-render and record it')
        out = out.resize(ref.size, Image.Resampling.LANCZOS)
    with staged_directory(outdir) as stage:
        reports = []
        def one(a, b, name, box, object_ids, scale=1):
            arr = np.asarray(a, dtype=np.float32); brr = np.asarray(b, dtype=np.float32)
            mae = float(np.abs(arr - brr).mean())
            paths = {'side_by_side': stage / f'{name}-side-by-side.png',
                     'overlay': stage / f'{name}-overlay.png',
                     'absolute_difference': stage / f'{name}-absolute-difference.png'}
            if include_source_crops:
                paths.update(reference_crop=stage/f'{name}-reference.png',rendered_crop=stage/f'{name}-rendered.png')
                a.save(paths['reference_crop'],compress_level=3);b.save(paths['rendered_crop'],compress_level=3)
            _labelled_side(a, b, left_label=left_label, right_label=right_label, display_scale=scale).save(paths['side_by_side'],compress_level=3)
            overlay = Image.blend(a, b, .5)
            difference = Image.fromarray(np.abs(arr - brr).clip(0, 255).astype('uint8'))
            if scale != 1:
                size = (a.width * scale, a.height * scale)
                overlay = overlay.resize(size, Image.Resampling.LANCZOS)
                difference = difference.resize(size, Image.Resampling.NEAREST)
            overlay.save(paths['overlay'],compress_level=3); difference.save(paths['absolute_difference'],compress_level=3)
            row = {'region': name, 'bbox': box, 'object_ids': object_ids,
                   'mae_rgb': mae, 'normalized_pixel_agreement': 1 - mae / 255,
                   'pixel_size': list(a.size), 'display_scale': scale}
            for key, path in paths.items():
                row[key] = path.name; row[key + '_sha256'] = sha256(path)
                with Image.open(path) as saved:
                    row[key + '_size'] = list(saved.size)
            return row
        reports.append(one(ref, out, 'full', [0, 0, *ref.size], [], 1))
        for region in clean_regions:
            box = region['bbox']
            reports.append(one(ref.crop(box), out.crop(box), region['id'], box, region['object_ids'], region_scale))
        if sha256(reference) != rh or sha256(rendered) != oh:
            raise ValueError('Source image changed during comparison; evidence was not published')
        result = {'evidence_version': EVIDENCE_VERSION, 'status': 'passed',
                  'scope': 'Comparison files produced only; no visual acceptance',
                  'reference_sha256': rh, 'render_sha256': oh, 'reference_size': list(ref.size),
                  'labels': {'left': left_label, 'right': right_label},
                  'render_original_size': list(original), 'resized_render': original != ref.size,
                  'regions': reports,
                  'warning': 'Raw RGB metrics are not fidelity grades. Agent must view the actual images.'}
        write_json(stage / 'comparison.json', result)
        lines = ['# Visual comparison evidence', '', 'Generated evidence, not visual acceptance.', '']
        for row in reports:
            lines += [f"## {row['region']}", f"- side-by-side: `{row['side_by_side']}`",
                      f"- overlay: `{row['overlay']}`", f"- difference: `{row['absolute_difference']}`", '']
        (stage / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('reference', type=Path); ap.add_argument('rendered', type=Path)
    ap.add_argument('--outdir', required=True, type=Path); ap.add_argument('--regions', type=Path)
    ap.add_argument('--slide', type=int, help='Select page for a shared deck regions file'); ap.add_argument('--right-label', help='Explicit renderer label for standalone comparisons');
    ap.add_argument('--resize-render', action='store_true'); ap.add_argument('--region-scale', type=int, default=1)
    ap.add_argument('--include-source-crops',action='store_true',help='Also emit separate reference/render crops; comparison evidence always retains both sides')
    args = ap.parse_args()
    try:
        compare(args.reference, args.rendered, args.outdir,
                read_json(args.regions) if args.regions else None, args.resize_render, args.region_scale, slide_index=args.slide, right_label=args.right_label,include_source_crops=args.include_source_crops)
    except Exception as exc:
        print(f'Compare failed: {exc}', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
