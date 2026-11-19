from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import build_discovery_context, build_services


def main() -> None:
    services = build_services()
    context = build_discovery_context(services.settings)
    evidence_items = services.discovery_service.discover(context)
    candidates = services.candidate_reducer.reduce(evidence_items)
    print(
        f"Backfilled {len(evidence_items)} discovery evidence item(s) "
        f"across {len(candidates)} merged candidate(s)"
    )


if __name__ == "__main__":
    main()
