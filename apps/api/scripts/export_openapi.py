"""Write the OpenAPI spec to packages/shared/openapi.json (input for the typed TS client)."""

import json
from pathlib import Path

from app.main import app

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[3] / "packages" / "shared" / "openapi.json"
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {out} ({len(app.openapi()['paths'])} paths)")
