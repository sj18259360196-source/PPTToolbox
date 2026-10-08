"""Local, versioned editable icon assets. No network or Office at import time."""
from pathlib import Path
import sys

# Pinned, licensed wheels ship with the desktop package; no global installation.
VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'icons'
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
