#!/usr/bin/env python3
"""Chrysalis mutation strategy toolkit.

Python 3.10+. Strategies operate on ASTs. The ``apply`` command parses,
transforms, validates compilation, and prints a unified diff; ``--write``
opts into replacing the target only after validation. Non-implemented
strategies remain conservative no-ops by design.
"""
from __future__ import annotations

import argparse
import ast
import copy
import difflib
import io
import importlib.util
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Protocol, Sequence


class MutationStrategy(Protocol):
    name: str
    preservation_class: str  # "formal" or "heuristic"
    description: str

    def applies_to(self, node: ast.AST) -> bool: ...
    def transform(self, node: ast.AST) -> ast.AST: ...
    def rationale(self, node: ast.AST) -> str: ...


STRATEGY_REGISTRY: Dict[str, Callable[[], MutationStrategy]] = {}


def register_strategy(cls: Callable[[], MutationStrategy]):
    """Register a strategy class, rejecting ambiguous or malformed plugins."""
    name = getattr(cls, "name", None) or getattr(cls, "__name__", "")
    if not isinstance(name, str) or not name:
        raise ValueError("strategy classes need a non-empty name")
    if name in STRATEGY_REGISTRY and STRATEGY_REGISTRY[name] is not cls:
        raise ValueError(f"strategy {name!r} is already registered")
    STRATEGY_REGISTRY[name] = cls
    return cls


def list_registered() -> List[str]:
    return sorted(STRATEGY_REGISTRY)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def instantiate(name: str) -> MutationStrategy:
    try:
        strategy = STRATEGY_REGISTRY[name]()
    except KeyError as exc:
        raise KeyError(f"Strategy {name!r} not registered") from exc
    for attr in ("name", "preservation_class", "description"):
        if not isinstance(getattr(strategy, attr, None), str):
            raise TypeError(f"strategy {name!r} has invalid {attr}")
    if strategy.preservation_class not in {"formal", "heuristic"}:
        raise ValueError(f"strategy {name!r} has invalid preservation_class")
    return strategy


class BaseStrategy:
    """Stateless strategy base; subclasses use class-level metadata."""
    name = "BaseStrategy"
    preservation_class = "heuristic"
    description = "Base strategy; do not use directly."

    def applies_to(self, node: ast.AST) -> bool:
        return False

    def transform(self, node: ast.AST) -> ast.AST:
        return node

    def rationale(self, node: ast.AST) -> str:
        return f"No-op rationale for {self.name}."


@register_strategy
class SimplifyBooleanExpressions(BaseStrategy):
    name = "SimplifyBooleanExpressions"
    preservation_class = "heuristic"
    description = "Simplify explicit equality checks against True or False."

    class Transformer(ast.NodeTransformer):
        def visit_Compare(self, node: ast.Compare) -> ast.AST:
            node = self.generic_visit(node)
            if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
                return node
            left, right = node.left, node.comparators[0]
            if isinstance(right, ast.Constant) and type(right.value) is bool:
                replacement: ast.AST = left if right.value else ast.UnaryOp(ast.Not(), left)
            elif isinstance(left, ast.Constant) and type(left.value) is bool:
                replacement = right if left.value else ast.UnaryOp(ast.Not(), right)
            else:
                return node
            return ast.copy_location(replacement, node)

    def applies_to(self, node: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Compare)
            and len(n.ops) == 1
            and isinstance(n.ops[0], ast.Eq)
            and ((isinstance(n.left, ast.Constant) and type(n.left.value) is bool)
                 or (isinstance(n.comparators[0], ast.Constant)
                     and type(n.comparators[0].value) is bool))
            for n in ast.walk(node)
        )

    def transform(self, node: ast.AST) -> ast.AST:
        return ast.fix_missing_locations(self.Transformer().visit(node))

    def rationale(self, node: ast.AST) -> str:
        return "Replace explicit boolean equality checks; review truthiness-sensitive operands."


@register_strategy
class LoopToComprehension(BaseStrategy):
    name = "LoopToComprehension"
    preservation_class = "heuristic"
    description = "Convert the narrow 'result=[]; for x in xs: result.append(expr)' form."

    class Transformer(ast.NodeTransformer):
        def _body(self, body: List[ast.stmt]) -> List[ast.stmt]:
            out: List[ast.stmt] = []
            i = 0
            while i < len(body):
                if i + 1 < len(body) and isinstance(body[i], ast.Assign) and isinstance(body[i + 1], ast.For):
                    init, loop = body[i], body[i + 1]
                    if (len(init.targets) == 1 and isinstance(init.targets[0], ast.Name)
                            and isinstance(init.value, ast.List) and not init.value.elts
                            and len(loop.body) == 1 and not loop.orelse
                            and isinstance(loop.body[0], ast.Expr)
                            and isinstance(loop.body[0].value, ast.Call)
                            and isinstance(loop.body[0].value.func, ast.Attribute)
                            and loop.body[0].value.func.attr == "append"
                            and isinstance(loop.body[0].value.func.value, ast.Name)
                            and loop.body[0].value.func.value.id == init.targets[0].id
                            and len(loop.body[0].value.args) == 1
                            and not loop.body[0].value.keywords):
                        comp = ast.ListComp(
                            elt=loop.body[0].value.args[0],
                            generators=[ast.comprehension(target=loop.target, iter=loop.iter, ifs=[], is_async=0)],
                        )
                        out.append(ast.copy_location(ast.Assign(targets=init.targets, value=comp), init))
                        i += 2
                        continue
                out.append(self.visit(body[i]))
                i += 1
            return out

        def visit_Module(self, node: ast.Module) -> ast.AST:
            node.body = self._body(node.body)
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            node.body = self._body(node.body)
            return node

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
            node.body = self._body(node.body)
            return node

    def applies_to(self, node: ast.AST) -> bool:
        return any(isinstance(n, ast.For) and len(n.body) == 1 and isinstance(n.body[0], ast.Expr)
                   and isinstance(n.body[0].value, ast.Call)
                   and isinstance(n.body[0].value.func, ast.Attribute)
                   and n.body[0].value.func.attr == "append" for n in ast.walk(node))

    def transform(self, node: ast.AST) -> ast.AST:
        return ast.fix_missing_locations(self.Transformer().visit(node))

    def rationale(self, node: ast.AST) -> str:
        return "Convert only a side-effect-free-looking, single-statement append loop."


class ProbeStrategy(BaseStrategy):
    """Base for discovery-only strategies whose transform is intentionally a no-op."""
    probe: Callable[[ast.AST], bool] = staticmethod(lambda node: False)

    def applies_to(self, node: ast.AST) -> bool:
        return bool(self.probe(node))


@register_strategy
class AddInputValidation(ProbeStrategy):
    name = "AddInputValidation"
    description = "Identify functions with inputs that may need explicit validation."
    probe = staticmethod(lambda n: any(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.args.args for x in ast.walk(n)))

    def rationale(self, node): return "Validation policy is domain-specific; no guard is invented automatically."


@register_strategy
class MagicNumberExtraction(ProbeStrategy):
    name = "MagicNumberExtraction"
    description = "Identify non-trivial numeric literals for domain-specific constants."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Constant) and type(x.value) in (int, float) and x.value not in (0, 1) for x in ast.walk(n)))

    def rationale(self, node): return "Constant names and scope require domain knowledge; discovery only."


@register_strategy
class ReplaceBlockingIOWithAsync(ProbeStrategy):
    name = "ReplaceBlockingIOWithAsync"
    description = "Identify open, requests, and socket calls for async review."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Call) and (getattr(x.func, "id", None) == "open" or getattr(getattr(x.func, "value", None), "id", None) in ("requests", "socket")) for x in ast.walk(n)))

    def rationale(self, node): return "Async conversion changes call contracts; discovery only."


@register_strategy
class HardenRPCSerializationChecks(ProbeStrategy):
    name = "HardenRPCSerializationChecks"
    description = "Identify JSON serialization sites for payload validation review."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and getattr(x.func.value, "id", None) == "json" and x.func.attr == "dumps" for x in ast.walk(n)))

    def rationale(self, node): return "Serialization policy is protocol-specific; discovery only."


@register_strategy
class AddRetryBackoff(ProbeStrategy):
    name = "AddRetryBackoff"
    description = "Identify requests calls for retry and backoff review."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and getattr(x.func.value, "id", None) == "requests" for x in ast.walk(n)))

    def rationale(self, node): return "Retry safety depends on idempotency and failure policy; discovery only."


@register_strategy
class LocalBufferingRefactor(ProbeStrategy):
    name = "LocalBufferingRefactor"
    description = "Identify direct open calls for durable buffering review."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Call) and getattr(x.func, "id", None) == "open" for x in ast.walk(n)))

    def rationale(self, node): return "Durability and ordering requirements are application-specific; discovery only."


@register_strategy
class AddBatchingForFSWrites(ProbeStrategy):
    name = "AddBatchingForFSWrites"
    description = "Identify files containing repeated open calls."
    probe = staticmethod(lambda n: sum(isinstance(x, ast.Call) and getattr(x.func, "id", None) == "open" for x in ast.walk(n)) >= 2)

    def rationale(self, node): return "Batch boundaries and failure semantics require domain knowledge; discovery only."


@register_strategy
class LimitGrowthStructure(ProbeStrategy):
    name = "LimitGrowthStructure"
    description = "Identify append, extend, and update operations for bound review."
    probe = staticmethod(lambda n: any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in ("append", "extend", "update") for x in ast.walk(n)))

    def rationale(self, node): return "Capacity limits require a product invariant; discovery only."


def _scaffold(name: str, author: str) -> str:
    return f'''"""Generated Chrysalis mutation strategy: {name}."""
import ast
from chrysalis_mutation_skeletons import BaseStrategy, register_strategy


@register_strategy
class {name}(BaseStrategy):
    name = {name!r}
    preservation_class = "heuristic"
    description = "TODO: describe the transformation and its safety boundary."

    def applies_to(self, node: ast.AST) -> bool:
        return False

    def transform(self, node: ast.AST) -> ast.AST:
        # Keep this a no-op until the semantic preconditions are explicit.
        return node

    def rationale(self, node: ast.AST) -> str:
        return "TODO: explain the preservation hypothesis and required tests."

# Generated by {author}.
'''


def generate(name: str, author: str, root: Path) -> Path:
    if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
        raise ValueError("name must be a PascalCase Python class name")
    target = root / "plugins" / "strategies" / f"{name}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    target.write_text(_scaffold(name, author), encoding="utf-8")
    return target


def load_plugin(path: Path) -> None:
    """Execute one plugin file; registration happens through the decorator."""
    # Support both normal imports and Tester/Python runner execution contexts.
    if "chrysalis_mutation_skeletons" not in sys.modules:
        sys.modules["chrysalis_mutation_skeletons"] = sys.modules[__name__]
    if path.suffix != ".py":
        raise ValueError(f"plugin must be a .py file: {path}")
    spec = importlib.util.spec_from_file_location(f"chrysalis_plugin_{path.stem}", path)
    if not spec or not spec.loader:
        raise ImportError(f"cannot load plugin {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def _load_plugins(paths: Iterable[Path]) -> None:
    for path in paths:
        load_plugin(path)


def discover_plugins(root: Path | None = None) -> List[Path]:
    """Discover Python strategy modules under plugins/strategies."""
    base = (root or Path.cwd()) / "plugins" / "strategies"
    if not base.is_dir():
        return []
    return sorted(path for path in base.glob("*.py") if path.name != "__init__.py")


def load_discovered_plugins(root: Path | None = None) -> None:
    for path in discover_plugins(root):
        try:
            load_plugin(path)
        except Exception as exc:
            print(f"Warning: failed to load plugin {path}: {exc}", file=sys.stderr)


def apply_diff(strategy_name: str, source_path: Path, plugins: Sequence[Path] = ()) -> str:
    _load_plugins(plugins)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    strategy = instantiate(strategy_name)
    if not strategy.applies_to(tree):
        return ""
    # Strategies receive an isolated tree so cached/shared ASTs cannot be mutated.
    transformed = ast.fix_missing_locations(strategy.transform(copy.deepcopy(tree)))
    if not isinstance(transformed, ast.AST):
        raise TypeError(f"{strategy_name} returned {type(transformed).__name__}, not an AST")
    compile(transformed, str(source_path), "exec")
    if ast.dump(transformed, include_attributes=False) == ast.dump(tree, include_attributes=False):
        return ""
    output = ast.unparse(transformed) + "\n"
    if output == source:
        return ""
    return "".join(difflib.unified_diff(
        source.splitlines(True), output.splitlines(True),
        fromfile=str(source_path), tofile=f"{source_path} [{strategy_name}]"))


def _metadata() -> List[Dict[str, Any]]:
    result = []
    for name in list_registered():
        strategy = instantiate(name)
        result.append({"name": name, "preservation_class": strategy.preservation_class,
                       "description": strategy.description})
    return result


def regression_tests() -> Dict[str, Any]:
    """Run focused regression checks for plugins, writes, validation, and isolation."""
    import contextlib
    import tempfile
    from unittest.mock import patch

    checks: Dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="chrysalis-tests-") as td:
        root = Path(td)
        target = root / "target.py"
        target.write_text("flag = True\nvalue = (flag == True)\n", encoding="utf-8")
        diff = apply_diff("SimplifyBooleanExpressions", target)
        assert "flag == True" in diff and "flag == True" in target.read_text(encoding="utf-8")
        checks["compile_validation_and_dry_run"] = "PASS"

        before = ast.parse("value = (flag == True)\n")
        original_dump = ast.dump(before, include_attributes=True)
        transformed = instantiate("SimplifyBooleanExpressions").transform(copy.deepcopy(before))
        compile(ast.fix_missing_locations(transformed), "<test>", "exec")
        assert ast.dump(before, include_attributes=True) == original_dump
        checks["ast_isolation"] = "PASS"

        written = root / "written.py"
        written.write_text("flag = True\nvalue = (flag == True)\n", encoding="utf-8")
        with patch.object(sys, "argv", ["chrysalis", "apply", "--strategy",
                                          "SimplifyBooleanExpressions", "--file",
                                          str(written), "--write"]):
            main()
        assert "flag == True" not in written.read_text(encoding="utf-8")
        checks["in_place_write"] = "PASS"

        plugin = root / "plugins" / "strategies" / "regression_plugin.py"
        plugin.parent.mkdir(parents=True)
        plugin.write_text(
            "from __main__ import BaseStrategy, register_strategy\n"
            "@register_strategy\n"
            "class RegressionPlugin(BaseStrategy):\n"
            "    name = 'RegressionPlugin'\n", encoding="utf-8")
        load_discovered_plugins(root)
        assert "RegressionPlugin" in STRATEGY_REGISTRY
        checks["plugin_discovery"] = "PASS"

        invalid = root / "invalid.py"
        invalid.write_text("x = 1\n", encoding="utf-8")
        class InvalidStrategy(BaseStrategy):
            name = "InvalidRegressionStrategy"
            def applies_to(self, node): return True
            def transform(self, node): return ast.parse("if:")
        register_strategy(InvalidStrategy)
        try:
            apply_diff("InvalidRegressionStrategy", invalid)
        except SyntaxError:
            checks["compile_rejection"] = "PASS"
        else:
            raise AssertionError("invalid transformed AST was accepted")

    return {"status": "PASS", "checks": checks}


def self_test() -> Dict[str, Any]:
    """Exercise canonical transforms, discovery-only behavior, and provenance."""
    with tempfile.TemporaryDirectory(prefix="chrysalis-") as td:
        source_path = Path(td) / "sample.py"
        source_path.write_text("def build(items, flag):\n    result = []\n    for item in items:\n        result.append(item * 2)\n    return flag == True, result\n", encoding="utf-8")
        loop_diff = apply_diff("LoopToComprehension", source_path)
        bool_diff = apply_diff("SimplifyBooleanExpressions", source_path)
        assert "ListComp" not in loop_diff and "for item in items" in loop_diff
        assert "+    return (flag, result)" in bool_diff
        assert apply_diff("AddInputValidation", source_path) == ""
        manifest = mutation_manifest("LoopToComprehension", source_path, loop_diff)
        assert manifest["changed"] and manifest["output_hash"]
    return {"status": "PASS", "strategies": len(STRATEGY_REGISTRY), "canonical_owner": "chrysalis_mutation_skeletons"}


def capability_inventory() -> Dict[str, Any]:
    """Return a deterministic convergence inventory for this toolkit."""
    return {
        "canonical_owner": "chrysalis_mutation_skeletons",
        "capabilities": {
            "ast_mutation": {"owner": "strategy_registry", "implemented": ["SimplifyBooleanExpressions", "LoopToComprehension"], "discovery_only": [name for name in list_registered() if name not in {"SimplifyBooleanExpressions", "LoopToComprehension"}]},
            "plugin_extension": {"owner": "register_strategy/load_plugin"},
            "safe_output": {"owner": "apply_diff", "properties": ["no_source_overwrite", "syntax_parse", "compile_check", "unified_diff"]},
            "provenance": {"owner": "mutation_manifest", "properties": ["strategy", "source_hash", "output_hash", "timestamp", "rationale"]},
        },
        "integration_candidates": {"autonomous_code_evolution_lab": "adapter", "ases_v3_evolution_lab": "adapter", "autonomous_code_evolution_reference": "migration_source"},
        "deletion_candidates": [],
    }


def mutation_manifest(strategy_name: str, source_path: Path, diff: str) -> Dict[str, Any]:
    source = source_path.read_text(encoding="utf-8")
    strategy = instantiate(strategy_name)
    tree = ast.parse(source, filename=str(source_path))
    transformed = strategy.transform(copy.deepcopy(tree)) if strategy.applies_to(tree) else tree
    if ast.dump(transformed, include_attributes=False) == ast.dump(tree, include_attributes=False):
        output = source
    else:
        output = ast.unparse(ast.fix_missing_locations(transformed)) + "\n"
    return {"schema": "chrysalis.mutation-manifest.v1", "created_at": utc_now(), "strategy": strategy_name,
            "preservation_class": strategy.preservation_class, "source_path": str(source_path),
            "source_hash": sha256_hex(source), "output_hash": sha256_hex(output), "diff_hash": sha256_hex(diff),
            "changed": output != source, "rationale": strategy.rationale(tree), "diff_lines": len(diff.splitlines())}



def main(argv: Sequence[str] | None = None) -> int:
    load_discovered_plugins()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="list registered strategy metadata")
    sub.add_parser("self-test", help="run deterministic toolkit self-tests")
    sub.add_parser("regression-tests", help="run focused regression tests")
    gen = sub.add_parser("generate", help="create a strategy scaffold")
    gen.add_argument("--name", required=True)
    gen.add_argument("--author", default="unknown")
    gen.add_argument("--root", type=Path, default=Path.cwd())
    run = sub.add_parser("apply", help="print a transformed-source diff")
    run.add_argument("--strategy", required=True)
    run.add_argument("--file", required=True, type=Path)
    run.add_argument("--plugin", type=Path, action="append", default=[])
    run.add_argument("--write", action="store_true", help="write the validated transformed source in place")
    inv = sub.add_parser("inventory", help="show canonical ownership and integration inventory")
    man = sub.add_parser("manifest", help="emit provenance for a proposed diff")
    man.add_argument("--strategy", required=True)
    man.add_argument("--file", required=True, type=Path)
    man.add_argument("--plugin", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "list":
            print(json.dumps(_metadata(), indent=2))
        elif args.command == "self-test":
            print(json.dumps(self_test(), indent=2))
        elif args.command == "regression-tests":
            print(json.dumps(regression_tests(), indent=2))
        elif args.command == "inventory":
            print(json.dumps(capability_inventory(), indent=2))
        elif args.command == "generate":
            print(generate(args.name, args.author, args.root))
        elif args.command == "manifest":
            _load_plugins(args.plugin)
            diff = apply_diff(args.strategy, args.file, ())
            print(json.dumps(mutation_manifest(args.strategy, args.file, diff), indent=2))
        else:
            diff = apply_diff(args.strategy, args.file, args.plugin)
            print(diff, end="")
            if args.write and diff:
                source = args.file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(args.file))
                strategy = instantiate(args.strategy)
                transformed = ast.fix_missing_locations(strategy.transform(copy.deepcopy(tree)))
                compile(transformed, str(args.file), "exec")
                args.file.write_text(ast.unparse(transformed) + "\n", encoding="utf-8")
                print(f"Successfully wrote {args.file}")
        return 0
    except (OSError, SyntaxError, KeyError, TypeError, ValueError, ImportError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
