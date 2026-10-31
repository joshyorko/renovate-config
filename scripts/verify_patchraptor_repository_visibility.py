#!/usr/bin/env python3
"""Fail clearly when Patchraptor cannot see the repositories it must manage."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from json import JSONDecodeError, load


REQUIRED_TARGETS = frozenset(
    {
        "joshyorko/codex-action-server",
        "joshyorko/mcp-tunnel-kit",
    }
)


def missing_targets(visible_names: Iterable[str]) -> tuple[str, ...]:
    visible = {name.strip() for name in visible_names if name.strip()}
    return tuple(sorted(REQUIRED_TARGETS - visible))


def repository_names(payload: object) -> tuple[str, ...]:
    pages = payload if isinstance(payload, list) else [payload]
    names: list[str] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(
            page.get("repositories"), list
        ):
            raise ValueError("GitHub returned an unexpected installation repository response")
        for item in page["repositories"]:
            if not isinstance(item, dict) or not isinstance(
                item.get("full_name"), str
            ):
                raise ValueError("GitHub returned a malformed installation repository")
            names.append(item["full_name"])
    return tuple(names)


def main() -> int:
    try:
        names = repository_names(load(sys.stdin))
    except (JSONDecodeError, ValueError):
        print(
            "::error title=Patchraptor App visibility check failed::Could not parse the installation repository response.",
            file=sys.stderr,
        )
        return 2

    missing = missing_targets(names)
    if missing:
        targets = ", ".join(missing)
        print(
            f"::error title=Patchraptor App access missing::{targets}",
            file=sys.stderr,
        )
        print(
            "Install Patchraptor on the missing target repositories, then rerun.",
            file=sys.stderr,
        )
        return 1

    print("Patchraptor App visibility is verified for both target repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
