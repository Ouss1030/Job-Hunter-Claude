"""
LIFECYCLE TRACKER STEP 8F-A
DAILY RUN INTEGRATION INVENTORY — READ ONLY

Purpose:
Extract the exact current daily_run.py structure needed to build
the Lifecycle integration patch safely.

No execution of daily_run.py.
No main.py.
No network.
No DB writes.
No project file modifications.

Usage:
    python lifecycle_step8f_a_daily_run_inventory.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "daily_run.py"
LOG_DIR = ROOT / "exports" / "logs"

INTERESTING_FUNCTIONS = [
    "new_step_state",
    "create_manifest",
    "migrate_manifest",
    "load_manifest",
    "save_manifest",
    "validate_manifest",
    "step_delta",
    "step_handoff",
    "run_pipeline",
    "print_final_summary",
    "main_cli",
]

INTERESTING_ASSIGNMENTS = [
    "DAILY_RUN_VERSION",
    "SUPPORTED_MANIFEST_VERSIONS",
    "STEP_ORDER",
    "ARTIFACT_PATTERNS",
    "STEP_FUNCTIONS",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def source_segment(
    text: str,
    node: ast.AST,
) -> str:
    lines = text.splitlines()

    start = getattr(
        node,
        "lineno",
        None,
    )
    end = getattr(
        node,
        "end_lineno",
        None,
    )

    if start is None or end is None:
        return ""

    return "\n".join(
        lines[start - 1:end]
    )


def assignment_name(
    node: ast.AST,
) -> str | None:
    if isinstance(
        node,
        ast.Assign,
    ):
        if len(node.targets) != 1:
            return None

        target = node.targets[0]
        if isinstance(
            target,
            ast.Name,
        ):
            return target.id

    if isinstance(
        node,
        ast.AnnAssign,
    ):
        if isinstance(
            node.target,
            ast.Name,
        ):
            return node.target.id

    return None


def literal_value(
    node: ast.AST,
):
    value_node = None

    if isinstance(
        node,
        ast.Assign,
    ):
        value_node = node.value
    elif isinstance(
        node,
        ast.AnnAssign,
    ):
        value_node = node.value

    if value_node is None:
        return None

    try:
        return ast.literal_eval(
            value_node
        )
    except Exception:
        return None


def collect_assignments(
    tree: ast.Module,
    text: str,
):
    result = {}

    for node in tree.body:
        name = assignment_name(
            node
        )
        if (
            name
            not in INTERESTING_ASSIGNMENTS
        ):
            continue

        segment = source_segment(
            text,
            node,
        )

        result[name] = {
            "lineno":
                getattr(
                    node,
                    "lineno",
                    None,
                ),
            "end_lineno":
                getattr(
                    node,
                    "end_lineno",
                    None,
                ),
            "literal_value":
                literal_value(
                    node
                ),
            "source":
                segment,
            "sha256":
                sha256_text(
                    segment
                ),
        }

    return result


def collect_functions(
    tree: ast.Module,
    text: str,
):
    result = {}

    for node in tree.body:
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        if (
            node.name
            not in INTERESTING_FUNCTIONS
        ):
            continue

        segment = source_segment(
            text,
            node,
        )

        result[
            node.name
        ] = {
            "lineno":
                node.lineno,
            "end_lineno":
                node.end_lineno,
            "source":
                segment,
            "sha256":
                sha256_text(
                    segment
                ),
        }

    return result


def search_markers(
    text: str,
):
    markers = {
        "delta_done_guard":
            r'["\']delta["\'].*DONE|DONE.*["\']delta["\']',
        "handoff_step":
            r'def\s+step_handoff\s*\(',
        "delta_step":
            r'def\s+step_delta\s*\(',
        "resume":
            r'resume',
        "no_handoff":
            r'no[_-]handoff',
        "manifest_version":
            r'manifest.*version|version.*manifest',
        "final_summary":
            r'final.*summary|summary.*final',
        "artifact_patterns":
            r'ARTIFACT_PATTERNS',
    }

    result = {}

    lines = text.splitlines()

    for key, pattern in markers.items():
        hits = []

        rx = re.compile(
            pattern,
            re.IGNORECASE,
        )

        for index, line in enumerate(
            lines,
            start=1,
        ):
            if rx.search(
                line
            ):
                hits.append(
                    {
                        "line":
                            index,
                        "text":
                            line.strip(),
                    }
                )

        result[key] = hits[:100]

    return result


def main():
    print(
        "=" * 100
    )
    print(
        "LIFECYCLE TRACKER STEP 8F-A "
        "- DAILY RUN INTEGRATION INVENTORY"
    )
    print(
        "=" * 100
    )
    print(
        "Mode : READ_ONLY"
    )
    print()

    if not TARGET.exists():
        raise SystemExit(
            f"daily_run.py introuvable: {TARGET}"
        )

    text = TARGET.read_text(
        encoding="utf-8",
        errors="strict",
    )

    try:
        tree = ast.parse(
            text,
            filename=str(TARGET),
        )
    except SyntaxError as exc:
        raise SystemExit(
            f"daily_run.py syntax error: {exc}"
        )

    assignments = (
        collect_assignments(
            tree,
            text,
        )
    )

    functions = (
        collect_functions(
            tree,
            text,
        )
    )

    missing_assignments = [
        name
        for name
        in INTERESTING_ASSIGNMENTS
        if name
        not in assignments
    ]

    missing_functions = [
        name
        for name
        in INTERESTING_FUNCTIONS
        if name
        not in functions
    ]

    payload = {
        "generated_at":
            datetime.now().isoformat(
                timespec="seconds"
            ),
        "mode":
            "READ_ONLY",
        "target":
            str(TARGET),
        "target_bytes":
            TARGET.stat().st_size,
        "target_sha256":
            sha256_text(
                text
            ),
        "line_count":
            len(
                text.splitlines()
            ),
        "syntax_ok":
            True,
        "assignments":
            assignments,
        "functions":
            functions,
        "missing_assignments":
            missing_assignments,
        "missing_functions":
            missing_functions,
        "marker_hits":
            search_markers(
                text
            ),
        "integration_expectations":
            {
                "desired_version":
                    "1.2.0",
                "desired_step_order":
                    [
                        "main",
                        "preparation",
                        "refresh",
                        "recheck",
                        "final_pool",
                        "delta",
                        "lifecycle",
                        "handoff",
                    ],
                "lifecycle_after":
                    "delta",
                "lifecycle_before":
                    "handoff",
                "handoff_requires":
                    "lifecycle DONE",
                "no_handoff_policy":
                    (
                        "lifecycle still runs; "
                        "only handoff is skipped"
                    ),
                "applied_policy":
                    "USER_ONLY",
            },
    }

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    json_path = (
        LOG_DIR
        / (
            "lifecycle_step8f_a_daily_run_inventory_"
            f"{stamp}.json"
        )
    )

    txt_path = (
        LOG_DIR
        / (
            "lifecycle_step8f_a_daily_run_inventory_"
            f"{stamp}.txt"
        )
    )

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        (
            "LIFECYCLE TRACKER STEP 8F-A "
            "- DAILY RUN INTEGRATION INVENTORY"
        ),
        "=" * 100,
        "Mode : READ_ONLY",
        f"Target : {TARGET}",
        (
            "SHA256 : "
            f"{payload['target_sha256']}"
        ),
        (
            "Lines : "
            f"{payload['line_count']}"
        ),
        "Syntax : OK",
        "",
        "ASSIGNMENTS",
        "-----------",
    ]

    for name in (
        INTERESTING_ASSIGNMENTS
    ):
        info = assignments.get(
            name
        )

        if info:
            lines.extend(
                [
                    (
                        f"\n### {name} "
                        f"[L{info['lineno']}-"
                        f"L{info['end_lineno']}]"
                    ),
                    info["source"],
                ]
            )
        else:
            lines.append(
                f"\n### {name}: MISSING"
            )

    lines.extend(
        [
            "",
            "FUNCTIONS",
            "---------",
        ]
    )

    for name in (
        INTERESTING_FUNCTIONS
    ):
        info = functions.get(
            name
        )

        if info:
            lines.extend(
                [
                    (
                        f"\n### {name} "
                        f"[L{info['lineno']}-"
                        f"L{info['end_lineno']}]"
                    ),
                    info["source"],
                ]
            )
        else:
            lines.append(
                f"\n### {name}: MISSING"
            )

    lines.extend(
        [
            "",
            "MISSING ASSIGNMENTS",
            "-------------------",
            str(
                missing_assignments
            ),
            "",
            "MISSING FUNCTIONS",
            "-----------------",
            str(
                missing_functions
            ),
        ]
    )

    txt_path.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )

    print(
        "daily_run.py lines :",
        payload[
            "line_count"
        ],
    )
    print(
        "Assignments found  :",
        len(
            assignments
        ),
        "/",
        len(
            INTERESTING_ASSIGNMENTS
        ),
    )
    print(
        "Functions found    :",
        len(
            functions
        ),
        "/",
        len(
            INTERESTING_FUNCTIONS
        ),
    )
    print(
        "Missing assignments:",
        missing_assignments,
    )
    print(
        "Missing functions  :",
        missing_functions,
    )
    print()
    print(
        "JSON :",
        json_path,
    )
    print(
        "TXT  :",
        txt_path,
    )
    print()
    print(
        "Aucun fichier projet modifié."
    )
    print(
        "Aucun pipeline exécuté."
    )


if __name__ == "__main__":
    main()
