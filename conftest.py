import sys
from pathlib import Path


ROOT_DIR = Path(__file__).parent.resolve()
LIB_DIR = ROOT_DIR / "lib"

for path in (ROOT_DIR, LIB_DIR):
    path_text = str(path)
    if path.exists() and path_text not in sys.path:
        sys.path.insert(0, path_text)
