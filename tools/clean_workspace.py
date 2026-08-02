from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

PROTECTED_DIRECTORY_NAMES = {".git", ".venv", "venv", "node_modules"}
CACHE_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
GENERATED_DIRECTORIES = {
    ".cache",
    "build",
    "htmlcov",
    "tmp",
    "apps/api/build",
    "apps/api/htmlcov",
    "apps/api/staticfiles",
    "apps/web/.cache",
    "apps/web/.vite",
    "apps/web/build",
    "apps/web/coverage",
    "apps/web/dist",
}
GENERATED_FILES = {
    ".coverage",
    "coverage.xml",
    "apps/api/.coverage",
    "apps/api/coverage.xml",
    "apps/api/openapi-schema.yaml",
    "apps/web/.eslintcache",
}


class UnsafeCleanupPath(RuntimeError):
    """Indica que un destino no pertenece de forma segura al repositorio."""


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").is_dir() or not (root / "package.json").is_file():
        raise UnsafeCleanupPath("No se pudo verificar la raíz del repositorio Claridez.")
    return root


def assert_safe_target(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate == resolved_root or resolved_root not in resolved_candidate.parents:
        raise UnsafeCleanupPath(f"Destino fuera del repositorio: {candidate}")
    return resolved_candidate


def discovered_artifacts(root: Path) -> Iterable[Path]:
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directory_names[:] = [
            name for name in directory_names if name not in PROTECTED_DIRECTORY_NAMES
        ]
        for name in tuple(directory_names):
            if name in CACHE_DIRECTORY_NAMES or name.endswith(".egg-info"):
                yield current_path / name
                directory_names.remove(name)
        for name in file_names:
            if name.endswith((".pyc", ".pyo", ".tsbuildinfo")) or name.startswith(".coverage."):
                yield current_path / name


def cleanup_targets(root: Path) -> list[Path]:
    candidates = {root / relative for relative in GENERATED_DIRECTORIES | GENERATED_FILES}
    candidates.update(discovered_artifacts(root))
    existing = sorted(
        (candidate for candidate in candidates if candidate.exists() or candidate.is_symlink()),
        key=lambda path: (len(path.parts), path.as_posix()),
    )
    selected: list[Path] = []
    for candidate in existing:
        assert_safe_target(root, candidate)
        if any(parent == candidate or parent in candidate.parents for parent in selected):
            continue
        selected.append(candidate)
    return selected


def remove_target(root: Path, target: Path, *, dry_run: bool) -> None:
    safe_target = assert_safe_target(root, target)
    relative = target.relative_to(root).as_posix()
    action = "Eliminaría" if dry_run else "Eliminando"
    print(f"{action}: {relative}")
    if dry_run:
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif safe_target.is_dir():
        shutil.rmtree(safe_target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Elimina únicamente artefactos regenerables del repositorio Claridez."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Muestra los destinos sin eliminarlos."
    )
    args = parser.parse_args()
    try:
        root = repository_root()
        targets = cleanup_targets(root)
        if not targets:
            print("No se encontraron artefactos regenerables.")
            return 0
        for target in targets:
            remove_target(root, target, dry_run=args.dry_run)
    except UnsafeCleanupPath as error:
        print(f"Limpieza rechazada: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
