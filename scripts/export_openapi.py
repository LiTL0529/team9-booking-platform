"""Regenerate contracts/openapi/<service>.json from the service code.

The contract tests fail when the running API and the committed document differ, so an API
change is always a visible, reviewed diff of the contract.

  python scripts/export_openapi.py            # all services
  python scripts/export_openapi.py booking    # one service
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVICES = ["merchant", "catalogue", "availability", "booking", "notification"]
SNIPPET = """
import json, sys
from app.main import create_app
spec = create_app().openapi()
sys.stdout.write(json.dumps(spec, indent=2, sort_keys=True) + "\\n")
"""


def export(service: str) -> None:
    env = dict(os.environ, DATABASE_URL="postgresql+psycopg://x:x@localhost:1/x", SERVICE_VERSION="dev")
    out = subprocess.run(
        [sys.executable, "-c", SNIPPET], cwd=REPO / "services" / service, env=env, check=True, capture_output=True
    ).stdout
    target = REPO / "contracts" / "openapi" / f"{service}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out.replace(b"\r\n", b"\n"))
    print(f"wrote {target.relative_to(REPO)}")


if __name__ == "__main__":
    for name in sys.argv[1:] or SERVICES:
        export(name)
