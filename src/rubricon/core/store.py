"""JSONL-backed artifact store.

Deliberately boring. An evaluation program's data layer should be greppable,
diffable, and readable by someone with no access to your code. JSONL on disk
under a run directory satisfies all three; a database does not.

Every write records a manifest entry with a content hash so a report can assert
"these numbers came from these exact bytes".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .schema import content_hash


@dataclass
class Store:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.root / name

    # -- jsonl -------------------------------------------------------------

    def write_jsonl(self, name: str, rows: Iterable[Any]) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with p.open("w", encoding="utf-8") as fh:
            for row in rows:
                obj = row.to_dict() if hasattr(row, "to_dict") else row
                fh.write(json.dumps(obj, sort_keys=True, default=str) + "\n")
                n += 1
        self._manifest(name, n)
        return p

    def read_jsonl(self, name: str) -> Iterator[dict]:
        p = self.path(name)
        if not p.exists():
            return iter(())

        def _gen() -> Iterator[dict]:
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield json.loads(line)

        return _gen()

    # -- json --------------------------------------------------------------

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = obj.to_dict() if hasattr(obj, "to_dict") else obj
        p.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        self._manifest(name, 1)
        return p

    def read_json(self, name: str) -> Any:
        p = self.path(name)
        if not p.exists():
            raise FileNotFoundError(p)
        return json.loads(p.read_text(encoding="utf-8"))

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    # -- text --------------------------------------------------------------

    def write_text(self, name: str, text: str) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self._manifest(name, 1)
        return p

    # -- manifest ----------------------------------------------------------

    def _manifest(self, name: str, n_records: int) -> None:
        mp = self.root / "_manifest.json"
        man = {}
        if mp.exists():
            try:
                man = json.loads(mp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                man = {}
        target = self.path(name)
        man[name] = {
            "records": n_records,
            "bytes": target.stat().st_size if target.exists() else 0,
            "sha256_12": content_hash(target.read_text(encoding="utf-8"))
            if target.exists()
            else None,
        }
        mp.write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")

    def manifest(self) -> dict:
        mp = self.root / "_manifest.json"
        if not mp.exists():
            return {}
        return json.loads(mp.read_text(encoding="utf-8"))


def default_root() -> Path:
    return Path(os.environ.get("RUBRICON_RESULTS", "results"))


__all__ = ["Store", "default_root"]
