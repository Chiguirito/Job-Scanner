from __future__ import annotations

from pathlib import Path

import vcr as vcrpy

CASSETTES_DIR = Path(__file__).parent / "cassettes"

# Match on method + URI only so cassettes are resilient to header differences
# across environments (User-Agent, Content-Length, etc.).
vcr = vcrpy.VCR(
    cassette_library_dir=str(CASSETTES_DIR),
    match_on=["method", "scheme", "host", "port", "path", "query"],
    record_mode="none",
)
