"""Read-only local evidence overlay, pinned by owner configuration, never tool arguments."""
import hashlib
import json
import platform
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment_matches(manager, recorded):
    """Passive reads only. An opaque stored assertion is not a live fingerprint."""
    inputs=manager.store.get("native_environment_inputs",{})
    if not inputs or recorded.get("identity_strength")!="pinned_binary_fonts_os":
        return False
    try:
        executable=Path(inputs["office_executable"])
        font_roots=[Path(p) for p in inputs["font_directories"]]
        if not font_roots or any(not p.is_dir() for p in font_roots):return False
        fonts={str(p.resolve()):sha(p) for root in font_roots for p in root.iterdir()
               if p.is_file() and p.suffix.casefold() in {".ttf",".ttc",".otf",".fon"}}
        return bool(fonts) and recorded=={
            "identity_strength":"pinned_binary_fonts_os","os_build":platform.version(),
            "office_binary_sha256":sha(executable),"font_files":fonts}
    except (OSError,KeyError,TypeError):
        return False


def lookup(manager, capability_id):
    sources=manager.store.get("native_evidence_sources",[])
    result=[]
    for source in sources:
        try:
            # Owner-configured root and index hash are not accepted in normal search requests.
            root=Path(source["root"]).resolve()
            index=Path(source["index"]).resolve()
            if not index.is_relative_to(root) or sha(index)!=source["sha256"]:
                raise ValueError("Pinned evidence index changed")
            manifest=json.loads(index.read_text(encoding="utf-8"))
            for row in manifest.get("entries",[]):
                if row.get("capability_id")!=capability_id:
                    continue
                refs=row.get("files",{})
                valid=bool(refs)
                for relative,digest in refs.items():
                    p=(root/relative).resolve()
                    if not p.is_relative_to(root) or not p.is_file() or sha(p)!=digest:
                        valid=False
                deps=row.get("dependencies",{})
                current=bool(deps) and all((manager.root/rel).resolve().is_relative_to(manager.root.resolve())
                        and (manager.root/rel).is_file() and sha(manager.root/rel)==h for rel,h in deps.items())
                # A version string is not an Office/environment fingerprint.
                environment=row.get("environment",{})
                env_match=environment_matches(manager,environment)
                status=("invalid" if not valid else "stale" if not current else
                        "needs_review" if not env_match else "recorded")
                result.append({"status":status,"capability_id":capability_id,
                    "implementation_current":current,"evidence_hashes_valid":valid,
                    "environment_match":env_match,"environment":environment,
                    "tested_scope":row.get("tested_scope",{}),"coverage":row.get("coverage",{}),
                    "uncovered":row.get("uncovered",[]),
                    "evidence":[str(root/r) for r in refs] if valid else [],
                    "note":"Hash binding authenticates recorded files, not the correctness of a visual verdict; no automatic qualification."})
        except (OSError,ValueError,KeyError,TypeError):
            result.append({"status":"invalid","capability_id":capability_id,
                           "note":"Missing or changed owner-pinned evidence; no promotion."})
    return result
