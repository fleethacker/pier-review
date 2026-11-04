"""S00b: implementations are reached only through their stable interface, so a mock can be swapped for a real
module in one place. Checked statically (AST), no imports executed."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELING = ROOT / "modeling"
# The only non-mock files allowed to import a mock implementation: the swap points.
SWAP_POINTS = {"modeling/modeling_api/backend.py", "modeling/mooring/environment/__init__.py"}


def imports_mock(source: str, is_package_init: bool = False) -> list[str]:
    """Imported names/modules that point at something called `mock`."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if "mock" in a.name.split(".")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "mock" in mod.split("."):
                hits.append(mod)
            hits += [f"{mod}.{a.name}" for a in node.names if a.name == "mock"]
    return hits


def is_mock_file(path: Path) -> bool:
    return path.stem == "mock" or "mock" in path.relative_to(ROOT).parts


def test_checker_detects_each_import_form():
    for src in ("from mooring.environment import mock as e", "from mooring.moored.mock import solver",
                "import mooring.environment.mock", "from .mock import size_tugs", "from . import mock"):
        assert imports_mock(src), src
    assert not imports_mock("from mooring import environment\nfrom mooring.templates import template_config")


def test_modeling_code_imports_mocks_only_through_swap_points():
    offenders = []
    for path in sorted(MODELING.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or is_mock_file(path) or rel in SWAP_POINTS:
            continue
        if hits := imports_mock(path.read_text()):
            offenders.append(f"{rel}: {hits}")
    assert not offenders, "import the stable interface, not the mock:\n" + "\n".join(offenders)


def test_agents_never_import_modeling_mocks():
    offenders = []
    for path in sorted((ROOT / "agents" / "mooring_agents").rglob("*.py")):
        for hit in imports_mock(path.read_text()):
            if hit.split(".")[0] == "mooring" or hit.startswith("modeling_api"):
                offenders.append(f"{path.relative_to(ROOT)}: {hit}")
    assert not offenders, "\n".join(offenders)


def test_template_config_output_is_unchanged_after_move():
    from mooring import refdata
    from mooring.templates import template_config

    cfg = template_config(refdata.ship("DDG-51-FIIA"), refdata.berth("NAVSTA-NORFOLK-P12-N"), "starboard", 650.0, "NYLON-DB-7IN")
    assert [(ln.line_number, ln.role, ln.ship_fitting_id, ln.pier_fitting_id) for ln in cfg.lines] == [
        (1, "bow", "BITT-1S", cfg.lines[0].pier_fitting_id), (2, "spring_aft", "BITT-2S", cfg.lines[1].pier_fitting_id),
        (3, "breast", "BITT-3S", cfg.lines[2].pier_fitting_id), (4, "breast", "BITT-4S", cfg.lines[3].pier_fitting_id),
        (5, "spring_fwd", "BITT-5S", cfg.lines[4].pier_fitting_id), (6, "stern", "BITT-6S", cfg.lines[5].pier_fitting_id)]


def test_environment_interface_exposes_the_swap_surface():
    from mooring import environment

    for name in ("now", "forecast", "history", "create_scenario", "get_scenario", "scenario_snapshot", "gust_model",
                 "synthetic", "with_relative"):
        assert callable(getattr(environment, name)), name


PHASES = ("moored", "berthing", "approach")


def _imports(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            out.append(("." * node.level) + (node.module or ""))
            out += [f"{'.' * node.level}{node.module or ''}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            out += [a.name for a in node.names]
    return out


def test_shared_capabilities_never_import_phases_and_phases_never_import_each_other():
    offenders = []
    base = MODELING / "mooring"
    for path in sorted(base.rglob("*.py")):
        rel = path.relative_to(base).parts
        for imp in _imports(path):
            parts = imp.lstrip(".").split(".")
            if parts[0] == "mooring" and len(parts) > 1:
                target = parts[1]
            else:
                continue
            if target in PHASES and (rel[0] not in PHASES or rel[0] != target):
                offenders.append(f"{'/'.join(rel)} imports mooring.{target}")
    assert not offenders, "\n".join(offenders)


def test_old_mock_modules_for_replaced_capabilities_are_gone():
    gone = ["moored/mock", "berthing/mock/tugs.py", "berthing/mock/sequence.py"]
    assert not [g for g in gone if (MODELING / "mooring" / g).exists()]
