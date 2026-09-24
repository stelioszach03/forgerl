#!/usr/bin/env python3
"""Print the development-only v0.3 plan. No credentials, providers or paid path."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forgerl.bench.v03 import draft_plan

if __name__ == "__main__":
    print(json.dumps(draft_plan(), indent=2))
