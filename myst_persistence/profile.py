"""Project profile: `.myst/myst.toml` — identity + retrieval tuning.

The profile is small TOML, hand-editable:

    [project]
    name = "my-app"
    description = "short project description"

    [retrieval]
    half-life = 30            # days; Ebbinghaus-style decay half-life
    recency-weight = 1.0      # weight of recency component
    frequency-weight = 0.6     # weight of tag/topic frequency component
    pin-weight = 2.0          # boost for pinned entries
    default-budget = 2000     # tokens for `myst state` when --budget is absent

We parse TOML with a stdlib `tomllib` (3.11+) when available and otherwise
fall back to a micro-parser for the small subset above (nested tables and
key = value pairs, ints/floats/strings). Python 3.9/3.10 have no tomllib,
so the fallback matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import DataFormatError


@dataclass
class RetrievalTuning:
    half_life: float = 30.0
    recency_weight: float = 1.0
    frequency_weight: float = 0.6
    pin_weight: float = 2.0
    default_budget: int = 2000

    def validate(self) -> None:
        if self.half_life <= 0:
            raise ValueError("half_life must be > 0")
        for name in ("recency_weight", "frequency_weight", "pin_weight"):
            if getattr(self, name) < 0:
                raise ValueError("%s must be >= 0" % name)
        if self.default_budget < 100:
            raise ValueError("default_budget must be >= 100 tokens")


@dataclass
class ProjectProfile:
    name: str = ""
    description: str = ""
    schema_version: int = 2
    retrieval: RetrievalTuning = field(default_factory=RetrievalTuning)

    def validate(self) -> None:
        self.retrieval.validate()
        if self.schema_version != 2:
            raise ValueError("unsupported schema version: %r" % self.schema_version)

    # -- TOML (subset) serialization ---------------------------------------

    def to_toml(self) -> str:
        r = self.retrieval
        return (
            "# Myst project profile — hand-editable.\n"
            "schema_version = 2\n"
            "\n"
            "[project]\n"
            "name = %s\n"
            "description = %s\n"
            "\n"
            "[retrieval]\n"
            "half-life = %g\n"
            "recency-weight = %g\n"
            "frequency-weight = %g\n"
            "pin-weight = %g\n"
            "default-budget = %d\n"
        ) % (
            _toml_str(self.name or "project"),
            _toml_str(self.description),
            r.half_life, r.recency_weight, r.frequency_weight,
            r.pin_weight, r.default_budget,
        )

    @classmethod
    def from_toml(cls, text: str) -> "ProjectProfile":
        """Parse the profile TOML subset (or raise DataFormatError)."""
        try:
            data = _parse_toml(text)
        except ValueError as exc:
            raise DataFormatError("myst.toml: %s" % exc) from exc
        proj = data.get("project", {}) or {}
        ret = data.get("retrieval", {}) or {}
        profile = cls(
            name=str(proj.get("name", "")),
            description=str(proj.get("description", "")),
            schema_version=int(data.get("schema_version", 2)),
        )
        profile.retrieval = RetrievalTuning(
            half_life=_num(ret, "half-life", "half_life", 30.0),
            recency_weight=_num(ret, "recency-weight", "recency_weight", 1.0),
            frequency_weight=_num(ret, "frequency-weight", "frequency_weight", 0.6),
            pin_weight=_num(ret, "pin-weight", "pin_weight", 2.0),
            default_budget=int(_num(ret, "default-budget", "default_budget", 2000)),
        )
        try:
            profile.validate()
        except ValueError as exc:
            raise DataFormatError("myst.toml: %s" % exc) from exc
        return profile

    # -- persistence ---------------------------------------------------------

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_toml(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ProjectProfile":
        p = Path(path)
        if not p.exists():
            return cls()
        return cls.from_toml(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Micro-TOML parser (subset: tables, dotted keys not supported, values
# int/float/string/bool). Uses tomllib when available for robustness.
# ---------------------------------------------------------------------------

def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def _parse_toml(text: str) -> dict:
    try:  # Python 3.11+
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass
    data, current = {}, None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise ValueError("bad table name at line %d" % no)
            current = data.setdefault(name.strip(), {})
            continue
        m = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*(?:#.*)?$', line)
        if not m:
            raise ValueError("unparseable line %d: %r" % (no, raw))
        key, value = m.group(1), m.group(2)
        if current is None:
            raise ValueError("key before any table at line %d" % no)
        current[key] = _parse_value(value)
    return data


def _parse_value(text: str):
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d*", text):
        return float(text)
    raise ValueError("unsupported TOML value: %r" % text)


def _num(table: dict, dashed: str, underscored: str, default: float) -> float:
    if dashed in table:
        return float(table[dashed])
    if underscored in table:
        return float(table[underscored])
    return default
