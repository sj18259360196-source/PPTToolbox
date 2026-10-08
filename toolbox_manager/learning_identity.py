"""Shared dependency identity for learned recipes and the management view."""
import hashlib
import json
from pathlib import Path

DEPENDENCIES = (
    "scripts/skill_recipe.py", "scripts/skill_library.py", "scripts/build_pptx.py",
    "scripts/local_workflow.py", "scripts/local_edit.py", "scripts/workflow_scene.py",
    "scripts/workflow_evidence.py", "scripts/verify_delivery.py",
    "scripts/evidence_contract.py", "assets/schemas/scene.schema.json",
    "scripts/native_capabilities.py", "scripts/native_format.py",
    "scripts/native_recipes.py", "scripts/native_office_readback.py",
    "scripts/native_text_range.py", "scripts/native_topology.py",
    "scripts/native_extensions.py", "scripts/validate_scene.py", "scripts/inspect_pptx.py",
    "toolbox_manager/learning_identity.py",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def compatibility(root):
    return digest({name: hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()
                   for name in DEPENDENCIES})
