from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force the safest runtime mode for local verification.
os.environ.setdefault("TRADING_MODE", "research_only")
os.environ.setdefault("ENABLE_LIVE_TRADING", "false")

from app.main import run_once


def main() -> None:
    results = run_once()
    print("Research-only cycle complete")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
