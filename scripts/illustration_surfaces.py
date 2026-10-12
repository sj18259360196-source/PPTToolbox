"""Advisory fill topology and semantic fragment measurements."""


def surfaces(objects):
    rows, pending = [], [(o, []) for o in reversed(objects)]
    while pending:
        node, parents = pending.pop()
        if node.get('kind') == 'group':
            pending.extend((child, parents+[node['id']]) for child in reversed(node.get('children', [])))
            continue
        if node.get('kind') != 'path':
            continue
        commands = node.get('commands', [])
        paths, points, closed = [], [], False
        for command in commands:
            if command[0] == 'M':
                if points:
                    paths.append((points, closed))
                points, closed = [command[1:]], False
            elif command[0] in {'L', 'C'}:
                # Control-hull bounds are conservative, never exact Bezier area.
                points.extend([command[i:i+2] for i in range(1, len(command), 2)])
            elif command[0] == 'Z':
                closed = True
        if points:
            paths.append((points, closed))
        style = node.get('style', {})
        fill = style.get('fill')
        requested_fill = bool(style.get('gradient')) or fill not in (None, 'none', 'transparent')
        filled = bool(node.get('closed')) and requested_fill
        all_points = [p for segment, _ in paths for p in segment]
        bounds = None
        if all_points:
            xs, ys = zip(*all_points)
            bounds = [min(xs), min(ys), max(xs), max(ys)]
        row = {'id': node['id'], 'component_group': parents[-1] if parents else None,
               'parent_groups': parents, 'filled': filled, 'requested_fill': requested_fill,
               'declared_closed': bool(node.get('closed')),
               'closed_subpaths': sum(closed for _, closed in paths),
               'open_subpaths': sum(not closed for _, closed in paths),
               'control_hull_bbox_xyxy': bounds, 'fill': fill,
               'compound_interpretation': 'holes_or_disjoint_parts_require_review' if len(paths)>1 else None}
        rows.append(row)
    area_rows = [(r, (r['control_hull_bbox_xyxy'][2]-r['control_hull_bbox_xyxy'][0]) *
                 (r['control_hull_bbox_xyxy'][3]-r['control_hull_bbox_xyxy'][1]))
                 for r in rows if r['filled'] and r['control_hull_bbox_xyxy']]
    largest = max((a for _, a in area_rows), default=0)
    tiny = [r['id'] for r, area in area_rows if largest > 0 and area < largest*.001]
    groups = {}
    for row in rows:
        key = row['component_group'] or '__unassigned__'
        groups.setdefault(key, []).append(row['id'])
    return {'format': 'semantic-surfaces/1', 'path_count': len(rows),
            'filled_paths': len(area_rows), 'open_filled_path_ids': [r['id'] for r in rows if r['filled'] and r['open_subpaths']],
            'tiny_relative_hull_ids': tiny[:100], 'tiny_relative_hull_count': len(tiny),
            'tiny_hull_ratio': .001, 'component_groups': groups,
            'fill_disabled_path_ids': [r['id'] for r in rows if r['requested_fill'] and not r['declared_closed']],
            'repeated_hull_groups': _repeated(rows), 'paths': rows[:200],
            'paths_truncated': len(rows)>200,
            'scope': 'advisory_control_hulls_not_surface_area_or_semantic_certification',
            'automatic_acceptance': False,
            'limitations': 'Tiny parts may be legitimate. Compound paths may encode real holes. Open unfilled strokes and connectors are valid. Colors and object counts do not decide acceptance.'}


def _repeated(rows):
    groups = {}
    for row in rows:
        if row['filled'] and row['control_hull_bbox_xyxy']:
            key = tuple(row['control_hull_bbox_xyxy'])
            groups.setdefault(key, []).append(row['id'])
    return [ids for ids in groups.values() if len(ids)>1][:100]
