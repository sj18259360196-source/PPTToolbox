"""One bounded, project-independent icon computation, no library or Office writes."""
import base64
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]


def main():
    raw=sys.stdin.buffer.read(8_500_001)
    if len(raw)>8_500_000:raise ValueError('Icon computation input too large')
    value=json.loads(raw);op=value['op'];args=value['arguments']
    if op!='trace_fragment':raise ValueError('Unsupported pure icon computation')
    from toolbox_manager.icons.contracts import validate
    from toolbox_manager.icons.service import image_bytes
    from toolbox_manager.icons.geometry import trace_mask_fragment
    validate(op,args)
    result=trace_mask_fragment(image_bytes(args['mask']),args['box'],args['prefix'],args.get('color','222222'),
        args['semantic_name'],args.get('smoothing','none'),args.get('simplify_error_px',0))
    output=json.dumps(result,ensure_ascii=False,allow_nan=False)
    if len(output.encode('utf-8'))>16_000_000:raise ValueError('Icon computation output too large')
    sys.stdout.buffer.write(output.encode('utf-8'))


if __name__=='__main__':main()
