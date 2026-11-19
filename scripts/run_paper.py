from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import run_once


if __name__ == "__main__":
    results = run_once()
    print(json.dumps(results, indent=2))
