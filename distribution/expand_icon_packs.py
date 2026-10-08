"""Maintainer-only pinned SVG ingestion. Never fetches on application startup."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time
import urllib.request
import re

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/codex/icon-expansion-20260928"
EVIDENCE = ROOT / "checks/icon-expansion-20260928"
SOURCES = json.loads((ROOT / "distribution/expanded-icon-sources.json").read_text(encoding="utf-8"))

def download(spec):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    target = SCRATCH / (spec["id"] + (".json" if spec.get("format") == "iconify" else ".tgz"))
    url = spec.get("url") or f"https://codeload.github.com/{spec['repo']}/tar.gz/{spec['revision']}"
    if not target.exists():
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PPTToolbox"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read(500_000_001)
                if len(data) > 500_000_000:
                    raise ValueError("Archive exceeds 500 MB")
                # Validate before persisting, never extract archive paths.
                import io
                if spec.get("format") == "iconify":
                    json.loads(data)
                else:
                    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                        archive.getmembers()
                target.write_bytes(data)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)
    return {"id": spec["id"], "url": url, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size}

def downloads():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(download, spec): spec for spec in SOURCES}
        for task in concurrent.futures.as_completed(tasks):
            spec = tasks[task]
            try:
                result = task.result()
            except Exception as exc:
                result = {"id": spec["id"], "error": str(exc)}
            results.append(result)
            print(json.dumps(result), flush=True)
    (EVIDENCE / "downloads.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

def reactome_names(refresh=False):
    """Use published category captions; do not infer biology from opaque IDs."""
    from lxml import html
    target = EVIDENCE / "reactome-names.json"
    if target.exists() and not refresh:
        return json.loads(target.read_text(encoding="utf-8"))
    categories = ["arrow", "background", "cell_element", "cell_type", "compound", "human_tissue",
                  "protein", "receptor", "therapeutic", "transporter"]
    def fetch(category, page_number=1):
        url = "https://reactome.org/icon-lib/" + category
        if page_number>1:
            url += "?page="+str(page_number)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PPTToolbox"})
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
        page = html.fromstring(raw)
        last=max([1]+[int(x) for href in page.xpath('//a/@href') for x in re.findall(r'\?page=(\d+)',href)])
        return ({Path(e.get("src")).stem: {"name": e.get("alt"), "category": category}
                for e in page.xpath('//img[contains(@src,"R-ICO-")][@alt]')}, last)
    names = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        first=list(pool.map(fetch, categories))
        for category,(result,last) in zip(categories,first):
            names.update(result)
        jobs=[(category,n) for category,(_,last) in zip(categories,first) for n in range(2,last+1)]
        futures=[pool.submit(fetch,category,n) for category,n in jobs]
        for future in concurrent.futures.as_completed(futures):
            result,_=future.result()
            names.update(result)
    target.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
    return names

TRANSLATIONS = {
    "heart":"心脏 心 血液 循环", "brain":"大脑 脑 神经", "cell":"细胞", "protein":"蛋白 蛋白质",
    "receptor":"受体", "transporter":"转运体", "compound":"化合物", "arrow":"箭头 流程",
    "background":"背景", "tissue":"组织", "therapeutic":"治疗 药物", "dna":"DNA 核酸 遗传",
    "rna":"RNA 核酸", "blood":"血液", "lung":"肺 呼吸", "liver":"肝脏", "kidney":"肾脏",
    "bacteria":"细菌", "bacterium":"细菌", "virus":"病毒", "bottle":"瓶", "flask":"烧瓶 实验",
    "test":"测试 实验", "tube":"试管 管", "microscope":"显微镜", "animal":"动物", "human":"人体",
    "medical":"医疗 医学", "pill":"药片 药物", "syringe":"注射器", "hospital":"医院",
    "person":"人物 人", "people":"人物 人群", "user":"用户", "file":"文件", "folder":"文件夹",
    "search":"搜索", "home":"主页 房屋", "house":"房屋", "gear":"齿轮 设置", "settings":"设置",
    "calendar":"日历", "clock":"时钟 时间", "chart":"图表", "graph":"图表", "data":"数据",
    "cloud":"云", "computer":"电脑", "device":"设备", "phone":"电话 手机", "database":"数据库",
    "flower":"花", "leaf":"叶片 植物", "tree":"树 植物", "plant":"植物", "water":"水",
    "drop":"水滴", "sun":"太阳", "moon":"月亮", "star":"星", "light":"光 灯", "book":"书",
    "graduation":"毕业 教育", "school":"学校 教育", "education":"教育", "check":"勾选 完成",
    "warning":"警告", "error":"错误", "info":"信息", "lock":"锁", "shield":"盾 安全",
    "beaker":"烧杯 实验", "atom":"原子", "magnet":"磁铁", "battery":"电池", "energy":"能源",
    "network":"网络", "link":"链接", "linkage":"连接", "membrane":"膜", "neuron":"神经元",
    "synapse":"突触", "antibody":"抗体", "immune":"免疫", "muscle":"肌肉", "bone":"骨",
}

def tags_for(name, category=""):
    words = re.split(r"[^a-z0-9]+", (name+" "+category).lower())
    tags = list(dict.fromkeys([category.replace("_", " "), *words]))
    for word in words:
        for term in TRANSLATIONS.get(word, TRANSLATIONS.get(word.rstrip("s"), "")).split():
            if term not in tags:
                tags.append(term)
    return [t for t in tags if t]

def items_for(spec, names):
    ident = spec["id"]
    if ident == "material":
        data = json.loads((SCRATCH / "material.json").read_text(encoding="utf-8"))
        for name, icon in data["icons"].items():
            # Outlined family, default weight; omit rounded/sharp and their duplicates.
            if name.endswith(("-rounded", "-sharp")):
                continue
            if not name.endswith("-outline") and name+"-outline" in data["icons"]:
                continue
            w, h = icon.get("width", data.get("width", 24)), icon.get("height", data.get("height", 24))
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">{icon["body"]}</svg>'
            yield name, svg, "outline", spec["license"], "material symbols"
        return
    with tarfile.open(SCRATCH / (ident+".tgz")) as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith(".svg") or member.size > 400000:
                continue
            path = member.name.split("/", 1)[-1]
            if ident == "phosphor" and not path.startswith("assets/regular/"):
                continue
            if ident == "fluent" and not (path.startswith("assets/") and "/SVG/" in path and path.endswith("_24_regular.svg")):
                continue
            if ident == "iconoir" and not path.startswith("icons/regular/"):
                continue
            if ident == "bootstrap" and not path.startswith("icons/"):
                continue
            if ident == "servier" and not (path.startswith("static/icons/cc-by-3.0/") and "/Servier/" in path):
                continue
            style = "multicolor" if ident in {"servier", "reactome"} else "outline"
            if ident == "bootstrap" and Path(path).stem.endswith("-fill"):
                style = "filled"
            category = path.split("/")[-3] if ident == "servier" else ""
            license_id = "CC-BY-3.0" if ident == "servier" else spec["license"]
            yield path, archive.extractfile(member).read().decode("utf-8-sig"), style, license_id, category

def check_item(item):
    sys.path.insert(0, str(ROOT))
    from toolbox_manager.icons.geometry import compile_svg, svg_from_ir, render
    from PIL import Image
    import numpy as np
    import io
    try:
        ir = compile_svg(item["svg"])
        png = render(svg_from_ir(ir))
        source = render(item["svg"])
        images = [Image.open(io.BytesIO(b)).convert("RGBA").resize((256,256)) for b in (png, source)]
        differences = []
        for color in ("white", "black"):
            a, b = [Image.new("RGBA", (256,256), color) for _ in range(2)]
            a.alpha_composite(images[0]); b.alpha_composite(images[1])
            differences.append(float(np.abs(np.array(a,dtype=float)-np.array(b,dtype=float)).mean()/255))
        if max(differences) > .025:
            raise ValueError("SVG conversion pixel MAE exceeds 0.025: "+str(differences))
        return {"ok": True, "mae": max(differences)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def build():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    names = reactome_names()
    reactome_revision = hashlib.sha256((SCRATCH/"reactome.tgz").read_bytes()).hexdigest()
    summary = []
    for spec in SOURCES:
        out = ROOT / ("assets/icon-packs/expanded-"+spec["id"]+".json")
        report = EVIDENCE / (spec["id"]+"-import.json")
        if out.exists() and report.exists() and not (
            spec["id"]=="reactome" and (EVIDENCE/"reactome-names.json").stat().st_mtime>out.stat().st_mtime):
            summary.append(json.loads(report.read_text(encoding="utf-8"))["summary"])
            continue
        items = []
        for path, svg, style, license_id, category in items_for(spec, names):
            name = Path(path).stem
            if spec["id"] == "reactome":
                descriptor = names.get(name, {})
                name = descriptor.get("name") or name
                category = descriptor.get("category", "")
                source_url = "https://reactome.org/content/detail/"+Path(path).stem
                revision = reactome_revision
            else:
                source_url = spec.get("url") if spec["id"] == "material" else f"https://github.com/{spec['repo']}/blob/{spec['revision']}/{urllib.request.quote(path)}"
                revision = spec["revision"]
            name = re.sub(r"^ic_fluent_|_24_regular$", "", name).replace("_", " ").replace("-", " ")
            items.append({"svg":svg, "metadata":{"name":name, "aliases":[Path(path).stem],
                "tags":tags_for(name,category), "collection":spec["collection"], "style":style,
                "author":spec["author"], "license":license_id, "source_url":source_url,
                "source_revision":revision, "origin":"library",
                "notes":"Original upstream SVG; native conversion checked, Office and semantic review still required."
                    + (" SVG edition distributed by Bioicons under CC BY 3.0; attribution to Servier Medical Art, https://smart.servier.com/." if spec["id"]=="servier" else "")}})
        accepted, rejected = [], []
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            for index, (item, result) in enumerate(zip(items, pool.map(check_item,items,chunksize=16))):
                if result["ok"]:
                    accepted.append(item)
                else:
                    rejected.append({"name":item["metadata"]["name"],"source_url":item["metadata"]["source_url"],"reason":result["error"]})
                if (index+1)%500 == 0:
                    print(spec["id"],index+1,"checked",len(accepted),"accepted",flush=True)
        entry = {"id":spec["id"],"collection":spec["collection"],"selected":len(items),"accepted":len(accepted),"rejected":len(rejected)}
        report.write_text(json.dumps({"summary":entry,"rejected":rejected},ensure_ascii=False,indent=2),encoding="utf-8")
        if not accepted:
            raise RuntimeError("No native assets accepted for "+spec["id"])
        out.write_text(json.dumps({"id":"expanded-"+spec["id"]+"-20260928","items":accepted},ensure_ascii=False),encoding="utf-8")
        summary.append(entry)
        print(json.dumps(entry),flush=True)
    (EVIDENCE/"import-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")

if __name__ == "__main__":
    if "--names" in sys.argv:
        print("Reactome names",len(reactome_names(refresh=True)),flush=True)
    elif "--build" in sys.argv:
        build()
    else:
        downloads()
