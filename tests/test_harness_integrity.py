"""The harness must be RUNNABLE, not merely correct in pieces.

`eval.py run` called `validate_reference_solution` without importing it. The
function was defined, two tests covered it directly, 195 tests were green and
three review rounds had read the call - and the only code path that spends
money raised NameError on its first line of real work.

Python binds globals at CALL time, so a name that is used but never bound is
invisible until that line executes. Tests reach the paths they were written
for; this reaches every path, including the branches no test takes.
"""

import ast
import builtins
from pathlib import Path

import pytest

# The harness itself. Fixtures are deliberately excluded: they are subject
# trees under test, and a broken one is a finding rather than a test failure.
MODULES = sorted(
    path
    for pattern in ("*.py", "*/*.py")
    for path in Path(".").glob(pattern)
    if not any(
        part in {".venv", "fixtures", "tests", "__pycache__", "build"}
        for part in path.parts
    )
)

MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__spec__", "__package__",
    "__loader__", "__builtins__", "__path__",
}


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name the module could plausibly bind, over-approximated.

    Over-approximating is the right error: a name this misses is reported as
    undefined and someone must look, while a name it wrongly adds is a false
    negative that only costs what the status quo already cost.
    """
    bound = set(dir(builtins)) | MODULE_DUNDERS
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            bound.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            bound.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def _undefined_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    bound = _bound_names(tree)
    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return sorted(used - bound)


def test_the_scan_catches_a_name_that_is_used_but_never_bound(tmp_path):
    """A guard nobody has watched fail is a guard that may not fire.

    This is the shape of the real defect: the name is called, and the import
    line does not mention it.
    """
    module = tmp_path / "broken.py"
    module.write_text(
        "from os import getcwd\n\n\ndef run():\n    return validate_reference_solution(getcwd())\n"
    )
    assert _undefined_names(module) == ["validate_reference_solution"]


def test_the_scan_does_not_flag_ordinary_binding_forms(tmp_path):
    """Over-approximating bindings is only safe if it covers what real code
    does - comprehensions, walrus, lambdas, except-as, and star imports of
    names bound elsewhere would otherwise make the guard too noisy to keep."""
    module = tmp_path / "ordinary.py"
    module.write_text(
        "import json\n"
        "TOTAL = 3\n"
        "def run(items, *rest, key=None, **kw):\n"
        "    doubled = [x * 2 for x in items]\n"
        "    picked = {k: v for k, v in kw.items()}\n"
        "    if (found := TOTAL) > 1:\n"
        "        pass\n"
        "    try:\n"
        "        json.dumps(doubled)\n"
        "    except ValueError as exc:\n"
        "        return exc, picked, found, rest, key\n"
        "    return sorted(doubled, key=lambda pair: pair)\n"
    )
    assert _undefined_names(module) == []


def test_modules_are_actually_being_scanned():
    """A glob that silently matches nothing turns this file into a no-op that
    reports success - the exact failure mode the harness exists to reject."""
    names = {path.name for path in MODULES}
    assert "eval.py" in names
    assert {"runner.py", "preflight.py", "apply.py"} <= names


@pytest.mark.parametrize("path", MODULES, ids=str)
def test_no_module_uses_a_name_it_never_binds(path):
    undefined = _undefined_names(path)
    assert not undefined, (
        f"{path} uses {undefined} without binding them. Python resolves this "
        f"at call time, so it fails only when that line runs - which for "
        f"eval.py meant after preflight, in the path that spends money."
    )
