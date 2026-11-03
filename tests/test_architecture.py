"""The module boundaries declared in docs/architecture.json, checked against the source tree.

Static: it parses the package with `ast` and never imports it. The rules are pure functions over
source text so each one is shown to fail on a synthetic tree, not only to pass on the real one.
"""

import ast
import json
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "bom_warnings"
MODEL_FILE = ROOT / "docs" / "architecture.json"
PACKAGE = "custom_components.bom_warnings"

type Model = dict[str, Any]


@dataclass(frozen=True)
class Import:
    source: str
    # The module file inside the package that this import reaches, or None for anything outside it.
    target: str | None
    # The dotted module as written, relative imports keeping their leading dots.
    dotted: str
    # The name pulled out of the module by a `from` import.
    name: str | None
    type_only: bool


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _resolve(source: str, level: int, module: str | None, name: str, files: set[str]) -> str | None:
    base = PurePosixPath(source).parent
    for _ in range(level - 1):
        base = base.parent
    if module is None:
        # `from . import x`: x is a submodule when a file of that name exists, else a name in the
        # package's own __init__.
        candidates = [base / f"{name}.py", base / "__init__.py"]
    else:
        path = base.joinpath(*module.split("."))
        candidates = [path.with_name(f"{path.name}.py"), path / "__init__.py"]
    return next((c.as_posix() for c in candidates if c.as_posix() in files), None)


def imports_of(source: str, text: str, files: set[str]) -> list[Import]:
    found: list[Import] = []

    def walk(nodes: Iterable[ast.AST], type_only: bool) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                found.extend(Import(source, None, a.name, None, type_only) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                dotted = "." * node.level + (node.module or "")
                for alias in node.names:
                    target = (
                        _resolve(source, node.level, node.module, alias.name, files)
                        if node.level
                        else None
                    )
                    found.append(Import(source, target, dotted, alias.name, type_only))
            elif isinstance(node, ast.If) and _is_type_checking(node.test):
                # Only the guarded branch is erased at runtime; an `else` still imports.
                walk(node.body, True)
                walk(node.orelse, type_only)
            else:
                walk(ast.iter_child_nodes(node), type_only)

    walk(ast.parse(text).body, False)
    return found


class _Builds(ast.NodeVisitor):
    """Every call that builds `cls`, with the name of the function it sits in."""

    def __init__(self, cls: str) -> None:
        self.cls = cls
        self.stack: list[str] = []
        self.sites: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == self.cls:
            self.sites.append(self.stack[-1] if self.stack else "module scope")
        self.generic_visit(node)


def violations(model: Model, sources: dict[str, str]) -> list[str]:
    """Every way the sources break the model, each as a stable one-line id."""
    files = set(sources)
    rank = {layer: i for i, layer in enumerate(model["layers"])}
    owners = {
        path: [
            d for d, spec in model["domains"].items() if any(fnmatch(path, g) for g in spec["owns"])
        ]
        for path in sources
    }

    def layer_of(path: str) -> str | None:
        return model["domains"][owners[path][0]]["layer"] if len(owners[path]) == 1 else None

    found: set[str] = set()
    for path, domains in owners.items():
        if not domains:
            found.add(f"owner: {path} is owned by no domain")
        elif len(domains) > 1:
            found.add(f"owner: {path} is owned by {len(domains)} domains ({', '.join(domains)})")

    for path, text in sources.items():
        layer = layer_of(path)
        for imp in imports_of(path, text, files):
            if not imp.dotted.startswith(".") and imp.dotted.startswith(PACKAGE):
                found.add(f"absolute-import: {path} imports {imp.dotted}, use a relative import")
            if imp.dotted.split(".")[0] == "homeassistant" and layer in model["homeassistantFree"]:
                found.add(f"homeassistant: {path} ({layer}) imports {imp.dotted}")
            if imp.target is None or imp.target == path:
                continue
            target_layer = layer_of(imp.target)
            if (
                not imp.type_only
                and layer is not None
                and target_layer is not None
                and rank[target_layer] < rank[layer]
            ):
                found.add(f"layer: {path} ({layer}) imports {imp.target} ({target_layer})")
            if imp.name and imp.name.startswith("_") and not imp.name.startswith("__"):
                found.add(f"private-import: {path} imports {imp.target}:{imp.name}")

        tree = ast.parse(text)
        for rule in model["constructedOnlyIn"]:
            builds = _Builds(rule["class"])
            builds.visit(tree)
            for function in builds.sites:
                if (path, function) != (rule["module"], rule["function"]):
                    found.add(f"construct: {path} builds {rule['class']} in {function}")
    return sorted(found)


@pytest.fixture(scope="module")
def model() -> Model:
    loaded: Model = json.loads(MODEL_FILE.read_text())
    return loaded


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return {p.relative_to(PACKAGE_DIR).as_posix(): p.read_text() for p in PACKAGE_DIR.rglob("*.py")}


def test_model_is_well_formed(model: Model) -> None:
    layers = set(model["layers"])
    assert set(model["homeassistantFree"]) <= layers
    assert {spec["layer"] for spec in model["domains"].values()} <= layers
    assert all(spec["purpose"] and spec["owns"] for spec in model["domains"].values())
    assert all(entry["reason"] for entry in model["allow"])


def test_no_unlisted_violations(model: Model, sources: dict[str, str]) -> None:
    allowed = {entry["violation"] for entry in model["allow"]}
    new = sorted(set(violations(model, sources)) - allowed)
    assert not new, (
        "Module boundaries in docs/architecture.json are broken. Fix the import, or edit the model "
        "if the structure really changed:\n  " + "\n  ".join(new)
    )


def test_allowlist_has_no_stale_entries(model: Model, sources: dict[str, str]) -> None:
    stale = sorted(
        {entry["violation"] for entry in model["allow"]} - set(violations(model, sources))
    )
    assert not stale, "No longer a violation, so delete it from `allow`:\n  " + "\n  ".join(stale)


TINY: Model = {
    "layers": ["top", "low"],
    "homeassistantFree": ["low"],
    "domains": {
        "a": {"layer": "top", "purpose": "p", "owns": ["a.py"]},
        "b": {"layer": "low", "purpose": "p", "owns": ["b.py"]},
    },
    "constructedOnlyIn": [{"class": "Client", "module": "b.py", "function": "make"}],
    "allow": [],
}


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        pytest.param({"a.py": "from .b import x\n", "b.py": "x = 1\n"}, [], id="downward"),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "from .a import x\n"},
            ["layer: b.py (low) imports a.py (top)"],
            id="upward",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "from . import a\n"},
            ["layer: b.py (low) imports a.py (top)"],
            id="upward-through-from-dot",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "if TYPE_CHECKING:\n    from .a import x\n"},
            [],
            id="upward-guarded-by-type-checking",
        ),
        pytest.param(
            {
                "a.py": "x = 1\n",
                "b.py": "if TYPE_CHECKING:\n    pass\nelse:\n    from .a import x\n",
            },
            ["layer: b.py (low) imports a.py (top)"],
            id="upward-in-type-checking-else",
        ),
        pytest.param(
            {"a.py": "from homeassistant.core import HomeAssistant\n", "b.py": "x = 1\n"},
            [],
            id="homeassistant-in-a-layer-that-allows-it",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "from homeassistant.core import HomeAssistant\n"},
            ["homeassistant: b.py (low) imports homeassistant.core"],
            id="homeassistant-from-import",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "import homeassistant.core\n"},
            ["homeassistant: b.py (low) imports homeassistant.core"],
            id="homeassistant-plain-import",
        ),
        pytest.param(
            {"a.py": "from .b import _hidden\n", "b.py": "_hidden = 1\n"},
            ["private-import: a.py imports b.py:_hidden"],
            id="private-name",
        ),
        pytest.param(
            {"a.py": "from .b import __version__\n", "b.py": "__version__ = 1\n"},
            [],
            id="dunder-name-is-not-private",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "x = 1\n", "c.py": "x = 1\n"},
            ["owner: c.py is owned by no domain"],
            id="unowned-module",
        ),
        pytest.param(
            {"a.py": "from custom_components.bom_warnings.b import x\n", "b.py": "x = 1\n"},
            [
                "absolute-import: a.py imports custom_components.bom_warnings.b, "
                "use a relative import"
            ],
            id="absolute-import-of-own-package",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "def make():\n    return Client()\n"},
            [],
            id="built-where-allowed",
        ),
        pytest.param(
            {"a.py": "x = Client()\n", "b.py": "x = 1\n"},
            ["construct: a.py builds Client in module scope"],
            id="built-in-another-module",
        ),
        pytest.param(
            {"a.py": "x = 1\n", "b.py": "def other():\n    return Client()\n"},
            ["construct: b.py builds Client in other"],
            id="built-in-another-function",
        ),
        pytest.param(
            {"a.py": "import m\n\nasync def f():\n    return m.Client()\n", "b.py": "x = 1\n"},
            ["construct: a.py builds Client in f"],
            id="built-through-an-attribute",
        ),
    ],
)
def test_rules_detect_what_they_claim(sources: dict[str, str], expected: list[str]) -> None:
    assert violations(TINY, sources) == expected


def test_a_module_claimed_by_two_domains_is_reported() -> None:
    model = {
        **TINY,
        "domains": {**TINY["domains"], "dup": {"layer": "low", "purpose": "p", "owns": ["b.py"]}},
    }
    assert violations(model, {"a.py": "x = 1\n", "b.py": "x = 1\n"}) == [
        "owner: b.py is owned by 2 domains (b, dup)"
    ]
