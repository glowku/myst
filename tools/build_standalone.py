#!/usr/bin/env python3
"""build_standalone.py — generate `myst_standalone.py`, the single-file Myst.

Inlines every module of the myst_persistence package into one runnable
script (init / log / state / show / verify / consolidate / export /
import / doctor / status / migrate / hook / agent-file / server mcp),
so a project can adopt the layer by dropping *one file* in its repo —
no pip install, no PYTHONPATH, Python 3.9+ only.

Mechanism: each module's source is stored as a string and executed with
exec() into a per-module namespace; a tiny package-emulating loader
(`_load(name)`) resolves intra-package imports on demand. Module sources
are rewritten only where necessary:

    `from .errors import X`   → resolved via the loader (kept as-is
                                 textually and translated at exec time
                                 through the package proxy)

Simplest robust translation: rewrite `from .x import y` →
`from myst_ns.x import y` where `myst_ns` is a synthetic module object
whose attribute access executes and caches the inlined module. That
keeps the generated file honest Python with normal import semantics.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "myst_persistence"

# module name → inlined order (dependency order, __init__ excluded)
MODULES = [
    "errors",
    "timeutil",
    "paths",
    "tokens",
    "model",
    "miniyaml",
    "ledger",
    "profile",
    "semantic",
    "render",
    "terminal",
    "retrieval",
    "state",
    "consolidate",
    "migrate",
    "commands",
    "mcp_server",
    "cli",
]

BANNER = (
    "#!/usr/bin/env python3\n"
    "\"\"\"myst_standalone.py — single-file Myst: cognitive persistence "
    "for AI agents.\n"
    "\n"
    "AUTO-GENERATED from the myst_persistence package by "
    "tools/build_standalone.py.\n"
    "Do not edit by hand; edit the package and rebuild. "
    "Zero dependencies, Python 3.9+.\n"
    "\n"
    "    python myst_standalone.py init\n"
    "    python myst_standalone.py log \"title\" --kind decision --tags a,b\n"
    "    python myst_standalone.py state --budget 1500\n"
    "    python myst_standalone.py show\n"
    "    python myst_standalone.py verify\n"
    "    python myst_standalone.py consolidate --apply\n"
    "    python myst_standalone.py export backup.json\n"
    "    python myst_standalone.py import backup.json\n"
    "    python myst_standalone.py doctor\n"
    "    python myst_standalone.py status\n"
    "    python myst_standalone.py migrate v1\n"
    "    python myst_standalone.py hook post-commit | pre-push\n"
    "    python myst_standalone.py agent-file\n"
    "    python myst_standalone.py server mcp\n"
    "\"\"\"\n"
    "\n"
    "__version__ = \"2.0.0\"\n"
    "\n"
    "# ---------------------------------------------------------------------------\n"
    "# Inlined package emulation: modules stored as source, executed on demand.\n"
    "# ---------------------------------------------------------------------------\n"
    "\n"
    "import sys as _sys\n"
    "import types as _types\n"
    "\n"
    "_SOURCES = {}\n"
)

_MODULE_TEMPLATE = (
    "\n"
    "_myst_pkg = _types.ModuleType(\"myst_persistence\")\n"
    "_myst_pkg.__path__ = []          # mark as package for import machinery\n"
    "_myst_pkg.__version__ = __version__\n"
    "_sys.modules[\"myst_persistence\"] = _myst_pkg\n"
    "\n"
    "import importlib.machinery as _importlib\n"
    "\n"
    "class _MystFinder:\n"
    "    \"\"\"Import hook resolving myst_persistence.* from _SOURCES.\"\"\"\n"
    "\n"
    "    def find_spec(self, fullname, path=None, target=None):\n"
    "        if fullname == \"myst_persistence\":\n"
    "            return None  # already registered\n"
    "        if not fullname.startswith(\"myst_persistence.\"):\n"
    "            return None\n"
    "        short = fullname.split(\".\", 1)[1]\n"
    "        if short not in _SOURCES:\n"
    "            return None\n"
    "        return _importlib.ModuleSpec(fullname, self)\n"
    "\n"
    "    def create_module(self, spec):\n"
    "        return None  # default module creation is fine\n"
    "\n"
    "    def exec_module(self, module):\n"
    "        short = module.__name__.split(\".\", 1)[1]\n"
    "        code = compile(_SOURCES[short],\n"
    "                       \"myst_standalone.py:\" + short, \"exec\")\n"
    "        exec(code, module.__dict__)\n"
    "\n"
    "_sys.meta_path.insert(0, _MystFinder())\n"
    "\n"
    "# ─── begin inlined myst_persistence sources ───────────────────────────────\n"
)

FOOTER = (
    "\n"
    "# ─── end inlined myst_persistence sources ─────────────────────────────────\n"
    "\n"
    "from myst_persistence.cli import main as _main\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    raise SystemExit(_main())\n"
)


def _rewrite(source: str, module: str) -> str:
    """Rewrite intra-package imports for the inlined environment.

    - `from .x import y`        → kept textually, resolved by _MystFinder
      (the module executes as `myst_persistence.x`).
    - `from . import x`         → `from myst_persistence import x`
    - `from . import __version__` → dropped (lives on the package stub).
    - `from . import x as y`    → `from myst_persistence import x as y`.
    - `from .x import y` where x == "__init__" — not present; refuse.
    """
    tree = ast.parse(source)

    class _R(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 0:
                return node
            if node.module:
                node.module = "myst_persistence." + node.module
            else:
                node.module = "myst_persistence"
            node.level = 0
            return node

    tree = _R().visit(tree)
    tree = ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _drop_future(source: str) -> str:
    lines = [l for l in source.splitlines()
             if l.strip() != "from __future__ import annotations"]
    return "\n".join(lines)


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "myst_standalone.py"

    parts = [BANNER + _MODULE_TEMPLATE.lstrip("\n")]
    for name in MODULES:
        path = PKG / (name + ".py")
        if not path.exists():
            print("missing module: %s" % path, file=sys.stderr)
            return 1
        source = _drop_future(path.read_text(encoding="utf-8"))
        try:
            source = _rewrite(source, name)
        except SyntaxError as exc:
            print("cannot rewrite %s: %s" % (name, exc), file=sys.stderr)
            return 1
        # Embed the module source inside a triple-quoted string.
        # Backslashes are doubled so \n etc. in the source stay literal
        # text. Triple-quote clusters inside the source are broken with
        # an escaped third quote ('""\\"') so they can never terminate
        # the container prematurely.
        safe = source.replace("\\", "\\\\")
        safe = safe.replace('"""', '""\\"')
        parts.append('_SOURCES["%s"] = """\n%s"""\n' % (name, safe))

    parts.append(FOOTER)
    text = "".join(parts)

    # sanity: the generated file must parse
    ast.parse(text)

    out_path.write_text(text, encoding="utf-8")
    print("wrote %s (%d bytes, %d lines)"
          % (out_path, out_path.stat().st_size, len(text.splitlines())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
