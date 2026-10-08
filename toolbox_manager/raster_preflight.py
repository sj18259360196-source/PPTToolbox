"""Conservative local glyph-row candidates, not OCR or automatic image editing."""
from PIL import Image


def text_candidates(path):
    with Image.open(path) as source:
        original=source.size
        if source.width*source.height>40000000:return []
        im=source.convert('RGBA');im.thumbnail((1000,1000))
    width,height=im.size;pixels=im.load();seen=set();components=[]
    def dark(x,y):
        r,g,b,a=pixels[x,y]
        return a>180 and max(r,g,b)<165
    for y in range(height):
        for x in range(width):
            if (x,y) in seen or not dark(x,y):continue
            stack=[(x,y)];seen.add((x,y));left=right=x;top=bottom=y;count=0
            while stack:
                cx,cy=stack.pop();count+=1
                left=min(left,cx);right=max(right,cx);top=min(top,cy);bottom=max(bottom,cy)
                for nx,ny in ((cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)):
                    if 0<=nx<width and 0<=ny<height and (nx,ny) not in seen and dark(nx,ny):
                        seen.add((nx,ny));stack.append((nx,ny))
            w=right-left+1;h=bottom-top+1
            if 4<=h<=48 and 1<=w<=max(48,h*2) and 4<=count<=w*h*.95:
                components.append((left,top,right+1,bottom+1))
    rows=[]
    for box in sorted(components,key=lambda b:(b[3],b[0])):
        row=next((r for r in rows if abs(r[0][3]-box[3])<=max(3,(box[3]-box[1])*.25)),None)
        if row is None:rows.append([box])
        else:row.append(box)
    result=[];sx=original[0]/width;sy=original[1]/height
    for row in rows:
        if len(row)<3:continue
        row.sort();near=sum(1 for a,b in zip(row,row[1:]) if 0<=b[0]-a[2]<=2*max(a[3]-a[1],b[3]-b[1]))
        if near<2:continue
        result.append([round(min(b[0] for b in row)*sx),round(min(b[1] for b in row)*sy),
                       round(max(b[2] for b in row)*sx),round(max(b[3] for b in row)*sy)])
    return result[:20]
