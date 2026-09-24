"""Licensed upstream source, artificial mutations; not historical upstream issues."""

import hashlib
import json
from pathlib import Path

from .pilot_catalog import family
from .tasks import case as c, public_task


def source():
    return json.loads(Path(__file__).with_name("boltons_source.json").read_text())


def external_specs():
    upstream = source()
    reference = {
        "clipping.py": upstream["functions"]["clamp"],
        "rounding.py": "from math import ceil as _ceil, floor as _floor\nimport bisect\n"
        + upstream["functions"]["ceil"]
        + "\n"
        + upstream["functions"]["floor"],
        "service.py": """from clipping import clamp
from rounding import ceil, floor
def run(request):
    value=clamp(request["value"],request["lower"],request["upper"])
    options=request.get("options")
    if request["mode"] == "ceil":
        return ceil(value, options)
    if request["mode"] == "floor":
        return floor(value, options)
    raise ValueError("unknown mode")
""",
    }
    q = lambda v, lo, hi, mode, options=None: {
        "value": v,
        "lower": lo,
        "upper": hi,
        "mode": mode,
        "options": options,
    }
    return family(
        "external_boltons_math",
        "external",
        reference,
        "Source-derived artificial repair task, not an upstream reported bug. Adapted Boltons mathutils clamp/ceil/floor are BSD-3-Clause (Mahmoud Hashemi), immutable revision 4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d. Original function bodies and notices are supplied. First clamp finite numeric value into [lower,upper], rejecting upper<lower with ValueError. Then mode=ceil/floor rounds using math.ceil/floor if options is null, or the smallest option >=value / largest option <=value after sorting provided numeric options. Raise ValueError if no such option or unknown mode. Do not mutate request or options. Adapter, artificial faults and all checks are independently newly authored for this pilot (not independently reviewed).",
        [
            (
                "clipping.py",
                "return min(max(x, lower), upper)",
                "return max(min(x, lower), upper)",
            ),
            (
                "rounding.py",
                "i = bisect.bisect_left(options, x)",
                "i = bisect.bisect_right(options, x)",
            ),
            (
                "service.py",
                'if request["mode"] == "ceil":',
                'if request["mode"] == "floor":',
            ),
        ],
        [
            c("exact option", q(4, 0, 10, "ceil", [2, 4, 8]), 4),
            c("clamped low", q(-2, 0, 10, "ceil"), 0),
            c("fraction floor", q(3.8, 0, 10, "floor"), 3),
        ],
        [
            c("verify sorted", q(3, 0, 10, "ceil", [8, 2, 4]), 4),
            c("verify inverted", q(2, 4, 1, "floor"), error="ValueError"),
        ],
        [
            c("hidden upper", q(15, 0, 10, "floor", [1, 4, 9, 12]), 9),
            c("hidden missing", q(8, 0, 10, "ceil", [1, 4]), error="ValueError"),
            c("hidden exact floor", q(-2, -5, 5, "floor", [-4, -2, 1]), -2),
            c("hidden negative", q(-2.5, -5, 5, "ceil"), -2),
            c("hidden empty", q(2, 0, 5, "floor", []), error="ValueError"),
            c("hidden mode", q(1, 0, 2, "round"), error="ValueError"),
        ],
    )


def external_manifest():
    upstream = source()
    return {
        "track": "source_derived_mutations_descriptive_only",
        "upstream": upstream["upstream"],
        "revision": upstream["revision"],
        "source_path": upstream["path"],
        "source_sha256": upstream["source_sha256"],
        "license": upstream["license"],
        "license_sha256": upstream["license_sha256"],
        "vendored_snapshot_sha256": hashlib.sha256(
            Path(__file__).with_name("boltons_source.json").read_bytes()
        ).hexdigest(),
        "review": {
            "redistribution": "BSD-3-Clause source redistribution permitted with retained copyright/conditions/disclaimer; notices embedded in every extracted source function.",
            "modifications": "Functions extracted into flat modules; math/bisect imports reconstructed; new service adapter and synthetic fault mutations. No upstream tests copied.",
            "exclusions": "Bits class/binascii host-incompatible constructs excluded without broadening executor. Not a complete upstream test-suite run.",
            "contamination": "Widely public upstream source may occur in model training; contamination not measured.",
            "claims": "No upstream endorsement, real-world bug-fix, independently authored grader, or SWE-bench claim.",
        },
        "tasks": [
            {
                **public_task(s.task, include_cases=True),
                "reference_files": s.task.reference_files,
                "hidden_cases": s.task.hidden_cases,
                "verification_cases": s.verification_cases,
            }
            for s in external_specs()
        ],
    }
