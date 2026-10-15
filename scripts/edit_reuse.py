"""Conservative package-level impact proof for sampled edit checks only."""
import hashlib
import re
from zipfile import ZipFile
from lxml import etree

if __package__:
    from .review_impact import digest
else:
    from review_impact import digest


def signature(path):
    """Any shared dependency change invalidates every slide, intentionally.

    Slide XML includes text layout, grouping, z-order and geometry. Per-slide
    relationships include media bindings. All other parts (even unused shared
    assets) are checked together. External links cannot establish equivalence.
    """
    shared, slides = {}, {}
    with ZipFile(path) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate package entries cannot support reuse')
        for name in names:
            data = package.read(name)
            if name.endswith('.rels'):
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                if any(r.get('TargetMode', '').lower() == 'external' for r in root):
                    return {'available': False, 'reason': 'external_relationship'}
            value = hashlib.sha256(data).hexdigest()
            match = re.fullmatch(r'ppt/slides/(?:_rels/)?slide(\d+)\.xml(?:\.rels)?', name)
            if match:
                slides.setdefault(int(match[1]), {})[name] = value
            else:
                shared[name] = value
        # Presentation order can differ from part number. Bind the actual slide
        # part at each index, as well as every global presentation relationship.
        from pptx import Presentation
        deck = Presentation(path)
        order = [str(s.part.partname).lstrip('/') for s in deck.slides]
        hashes = {}
        for index, part in enumerate(order, 1):
            match = re.fullmatch(r'ppt/slides/slide(\d+)\.xml', part)
            if not match:
                return {'available': False, 'reason': 'unsupported_slide_part'}
            hashes[index] = digest(slides[int(match[1])])
    return {'available': True, 'shared_sha256': digest(shared), 'slides': hashes}


def equivalence(before, after, slide, cache=None):
    cache = cache if cache is not None else {}
    def read(path):
        if str(path) not in cache:
            cache[str(path)] = signature(path)
        return cache[str(path)]
    old, new = read(before), read(after)
    return (old.get('available') and new.get('available')
            and old['shared_sha256'] == new['shared_sha256']
            and old['slides'].get(slide) is not None
            and old['slides'].get(slide) == new['slides'].get(slide))
