#!/usr/bin/env python3
"""Verify target outcomes without changing the Renovate or Review writer jobs."""

import argparse
import json
from pathlib import Path
import sys


TARGETS = frozenset({"joshyorko/codex-action-server", "joshyorko/mcp-tunnel-kit"})


def verify_target_records(records):
    extracted = {}
    finished = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("malformed Renovate JSON log record")
        repo = record.get("repository")
        if repo not in TARGETS:
            continue
        message = record.get("msg", "")
        config_error = record.get("configError", {})
        if message in {
            "Repository has invalid config", "Found errors in inherited configuration.",
            "Found errors in presets inside the inherited configuration.",
        } or (isinstance(config_error, dict) and config_error.get("message") in {
            "config-validation", "config-inherit-not-found", "config-inherit-parse-error",
        }):
            raise ValueError(f"{repo}: configuration rejected")
        if message == "Dependency extraction complete":
            total = record.get("stats", {}).get("total", {})
            counts = (total.get("fileCount"), total.get("depCount"))
            if not all(type(value) is int and value > 0 for value in counts):
                raise ValueError(f"{repo}: no positive dependency extraction")
            extracted[repo] = total
        if message == "Repository finished":
            if (record.get("result") != "done" or record.get("enabled") is not True
                    or record.get("onboarded") is not True):
                raise ValueError(f"{repo}: repository did not complete successfully")
            finished.add(repo)
    missing = TARGETS - (finished & extracted.keys())
    if missing:
        raise ValueError("targets not processed and extracted: " + ", ".join(sorted(missing)))
    return extracted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    try:
        if args.log.stat().st_size > 16_777_216:
            raise ValueError("Renovate target log exceeds 16 MiB")
        records = []
        with args.log.open() as stream:
            for line in stream:
                if len(line) > 1_048_576:
                    raise ValueError("Renovate log record exceeds 1 MiB")
                if line.strip():
                    records.append(json.loads(line))
        results = verify_target_records(records)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else type(error).__name__
        print(f"::error title=Patchraptor target readiness failed::{message}", file=sys.stderr)
        return 1
    for repo in sorted(results):
        print(f"{repo}: dependency extraction and repository completion verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
