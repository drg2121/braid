"""Structured account of what a merge did."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceReport:
    """Everything that happened while merging one source backup."""

    name: str
    device: str
    last_modified: str
    added: Counter = field(default_factory=Counter)
    reused: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    media_added: int = 0
    media_reused: int = 0
    media_renamed: list[tuple[str, str]] = field(default_factory=list)

    def conflict(self, table: str, detail: str, resolution: str) -> None:
        self.conflicts.append(
            {"table": table, "detail": detail, "resolution": resolution}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "device": self.device,
            "lastModified": self.last_modified,
            "added": dict(self.added),
            "reused": dict(self.reused),
            "updated": dict(self.updated),
            "skipped": dict(self.skipped),
            "mediaAdded": self.media_added,
            "mediaReused": self.media_reused,
            "mediaRenamed": [
                {"from": a, "to": b} for a, b in self.media_renamed
            ],
            "conflicts": self.conflicts,
        }


@dataclass
class MergeReport:
    """The result of merging a base backup with one or more sources."""

    base: str = ""
    base_device: str = ""
    output: str = ""
    schema_version: int = 0
    sources: list[SourceReport] = field(default_factory=list)
    totals_before: dict[str, int] = field(default_factory=dict)
    totals_after: dict[str, int] = field(default_factory=dict)
    integrity_errors: list[str] = field(default_factory=list)

    def add_source(self, name: str, device: str, last_modified: str) -> SourceReport:
        sr = SourceReport(name=name, device=device, last_modified=last_modified)
        self.sources.append(sr)
        return sr

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "baseDevice": self.base_device,
            "output": self.output,
            "schemaVersion": self.schema_version,
            "sources": [s.to_dict() for s in self.sources],
            "totalsBefore": self.totals_before,
            "totalsAfter": self.totals_after,
            "integrityErrors": self.integrity_errors,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"base    : {self.base}  [{self.base_device}]")
        for s in self.sources:
            lines.append("")
            lines.append(f"source  : {s.name}  [{s.device}]  modified {s.last_modified}")
            for label, counter in (
                ("added", s.added),
                ("updated", s.updated),
                ("reused", s.reused),
                ("skipped", s.skipped),
            ):
                if not counter:
                    continue
                detail = "  ".join(
                    f"{table}={n}" for table, n in sorted(counter.items()) if n
                )
                if detail:
                    lines.append(f"  {label:<8}{detail}")
            lines.append(
                f"  media   added={s.media_added}  reused={s.media_reused}"
                f"  renamed={len(s.media_renamed)}"
            )
            for c in s.conflicts:
                lines.append(f"  ! {c['table']}: {c['detail']} -> {c['resolution']}")

        lines.append("")
        lines.append("row counts (before -> after)")
        for table in sorted(set(self.totals_before) | set(self.totals_after)):
            before = self.totals_before.get(table, 0)
            after = self.totals_after.get(table, 0)
            flag = "" if after == before else f"  (+{after - before})"
            lines.append(f"  {table:<34}{before:>7} -> {after:>7}{flag}")

        if self.integrity_errors:
            lines.append("")
            lines.append("INTEGRITY ERRORS")
            lines.extend(f"  {e}" for e in self.integrity_errors)

        lines.append("")
        lines.append(f"output  : {self.output}")
        return "\n".join(lines)


__all__ = ["MergeReport", "SourceReport"]
