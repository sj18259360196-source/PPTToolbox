"""Private contour worker with a finite request pipe, never the MCP input stream."""
import base64,io,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

def main():
    body=sys.stdin.buffer.read(32*1024*1024+1)
    sys.stdin.close()
    if len(body)>32*1024*1024:raise ValueError('Contour request exceeds budget')
    a=json.loads(body.decode('utf-8'))
    from PIL import Image
    from shape_construction import compare_contours
    def image(key):
        raw=base64.b64decode(a[key].split(',',1)[-1],validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>1_000_000:raise ValueError('Contour crop exceeds one million pixels')
            im.load();return im.copy()
    result=compare_contours(*[image(k) for k in ('reference','candidate','reference_mask','candidate_mask')],
                             image('exclude_mask') if a.get('exclude_mask') else None)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
