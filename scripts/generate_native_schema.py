"""Generate the native-format scene schema from its sole typed manifest."""
import json
from pathlib import Path
from native_capabilities import FORMAT


def generate():
    path = Path(__file__).resolve().parents[1]/"assets/schemas/scene.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["$defs"]["style"]["properties"]["native_format"] = FORMAT
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
