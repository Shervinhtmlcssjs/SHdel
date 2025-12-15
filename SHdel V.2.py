#!/usr/bin/env python3
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Set, Tuple, Optional

BANNER = r"""
     ____         _     __          
    //   ) )     //    / /            /
   ((           //___ / /      ___   /      ___       //
     \\        / ___   /     //   ) /     //___) )   //
       ) )    //    / /     //   / /     //         //
((___ / /    //    / /     ((___/ /     ((____     //=======

 
||   / /     ___
||  / /    //   ) )
|| / /      ___/ /
||/ /     / ____/
|  /     / /____



 ©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France
"""

# =========================
# Settings (V2 Parameters)
# =========================
@dataclass
class Settings:
    dry_run: bool = False                 # Preview + no deletion
    max_depth: int = 0                    # 0 = unlimited
    exclude_tokens: List[str] = field(default_factory=lambda: [".git", ".shdel_trash"])
    delete_mode: str = "permanent"        # "permanent" or "trash"
    auto_confirm: bool = False            # If True: skip y/N prompt and proceed

    def is_excluded(self, p: Path) -> bool:
        s = str(p)
        return any(tok and tok in s for tok in self.exclude_tokens)

SETTINGS = Settings()

# ---------------- UI helpers ----------------
def hr() -> None:
    print("-" * 90)

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")

def pause() -> None:
    input("Press Enter to continue...")

def ask_path() -> Path:
    p = input("Target directory path (e.g. . or /path/to/project): ").strip() or "."
    p = os.path.expanduser(p)
    try:
        return Path(p).resolve()
    except Exception:
        return Path(p).absolute()

def guard_path(root: Path) -> bool:
    root_str = str(root)
    if not root_str or root_str == "/":
        print("ERROR: Refusing empty path or '/'.")
        return False
    if os.name == "nt":
        s = root_str.rstrip("\\/")
        if len(s) == 2 and s[1] == ":":
            print("ERROR: Refusing drive root path.")
            return False
    if not root.exists() or not root.is_dir():
        print(f"ERROR: Directory not found: {root}")
        return False
    return True

def confirm(msg: str) -> bool:
    if SETTINGS.auto_confirm:
        print("AUTO-CONFIRM: enabled. Proceeding without prompt.")
        return True
    ans = input(f"{msg} (y/N): ").strip().lower()
    return ans in ("y", "yes")

# ---------------- Size helpers ----------------
def format_bytes(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    n = float(num)
    for u in units:
        if n < 1024.0 or u == units[-1]:
            return f"{n:.2f} {u}" if u != "B" else f"{int(n)} {u}"
        n /= 1024.0
    return f"{num} B"

def safe_stat_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except Exception:
        return 0

def dir_size_bytes(root: Path) -> int:
    total = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        cur = Path(current)

        # prune symlink dirs
        pruned = []
        for d in dirs:
            dp = cur / d
            try:
                if dp.is_symlink():
                    pruned.append(d)
            except Exception:
                pruned.append(d)
        for d in pruned:
            try:
                dirs.remove(d)
            except ValueError:
                pass

        for f in files:
            fp = cur / f
            try:
                if fp.is_symlink():
                    continue
            except Exception:
                continue
            total += safe_stat_size(fp)
    return total

def path_size_bytes(p: Path) -> int:
    try:
        if p.is_dir():
            return dir_size_bytes(p)
        return safe_stat_size(p)
    except Exception:
        return 0

# ---------------- Walk with pruning (depth + exclusions) ----------------
def walk_scoped(root: Path) -> Iterable[Tuple[Path, List[str], List[str]]]:
    """
    os.walk with:
    - no symlink traversal
    - exclusion pruning
    - max depth pruning
    """
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        cur = Path(current)

        # depth pruning
        if SETTINGS.max_depth and SETTINGS.max_depth > 0:
            try:
                rel_depth = len(cur.relative_to(root).parts)
            except Exception:
                rel_depth = 0
            if rel_depth >= SETTINGS.max_depth:
                dirs[:] = []

        # prune dirs: exclusions + symlinks
        keep_dirs: List[str] = []
        for d in dirs:
            dp = cur / d
            try:
                if dp.is_symlink():
                    continue
            except Exception:
                continue
            if SETTINGS.is_excluded(dp):
                continue
            keep_dirs.append(d)
        dirs[:] = keep_dirs

        yield cur, dirs, files

# ---------------- Finders (with prune) ----------------
def find_dirs_named(root: Path, dirname: str) -> Iterable[Path]:
    for cur, dirs, _files in walk_scoped(root):
        if dirname in dirs:
            target = cur / dirname
            if not SETTINGS.is_excluded(target):
                yield target
            # prune match so we do not descend
            try:
                dirs.remove(dirname)
            except ValueError:
                pass

def find_dirs_by_exact_suffix(root: Path, suffix_parts: List[str]) -> Iterable[Path]:
    suffix = os.sep.join(suffix_parts)
    for cur, dirs, _files in walk_scoped(root):
        for d in list(dirs):
            candidate = cur / d
            if SETTINGS.is_excluded(candidate):
                continue
            if str(candidate).endswith(suffix):
                yield candidate
                # prune
                try:
                    dirs.remove(d)
                except ValueError:
                    pass

def find_files_named(root: Path, filename: str) -> Iterable[Path]:
    for cur, _dirs, files in walk_scoped(root):
        for f in files:
            if f != filename:
                continue
            fp = cur / f
            if SETTINGS.is_excluded(fp):
                continue
            yield fp

# ---------------- Delete helpers ----------------
def dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: Set[str] = set()
    out: List[Path] = []
    for p in paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            out.append(p)
    return out

def list_with_sizes(paths: List[Path]) -> Tuple[List[Tuple[Path, int, str]], int]:
    items: List[Tuple[Path, int, str]] = []
    total = 0
    for p in paths:
        kind = "DIR" if p.is_dir() else "FILE"
        sz = path_size_bytes(p)
        total += sz
        items.append((p, sz, kind))
    items.sort(key=lambda x: (-x[1], str(x[0])))
    return items, total

def preview_and_confirm(title: str, targets: List[Path]) -> bool:
    hr()
    print(title)
    hr()

    targets = dedupe_paths([p for p in targets if not SETTINGS.is_excluded(p)])
    if not targets:
        print("INFO: Nothing found.")
        return False

    items, total = list_with_sizes(targets)

    print(f"FOUND: {len(items)} item(s)")
    print("SIZE             TYPE  PATH")
    print("-" * 90)
    for p, sz, kind in items:
        print(f"{format_bytes(sz):<16} {kind:<4}  {p}")
    print("-" * 90)
    print(f"TOTAL SIZE: {format_bytes(total)}")
    hr()

    if SETTINGS.dry_run:
        print("DRY-RUN: enabled. Nothing will be deleted.")
        return False

    return confirm("Proceed with deletion?")

def ensure_unique_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    base = dest
    i = 1
    while True:
        candidate = Path(str(base) + f".{i}")
        if not candidate.exists():
            return candidate
        i += 1

def trash_base_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = root / ".shdel_trash" / stamp
    base.mkdir(parents=True, exist_ok=True)
    return base

def delete_or_trash(root: Path, p: Path) -> bool:
    if not p.exists():
        print(f"SKIP: Already gone: {p}")
        return False

    if SETTINGS.dry_run:
        print(f"DRY-RUN: would delete: {p}")
        return True

    try:
        if SETTINGS.delete_mode == "trash":
            base = trash_base_dir(root)
            try:
                rel = p.relative_to(root)
                dest = base / rel
            except Exception:
                dest = base / p.name

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest = ensure_unique_path(dest)
            print(f"TRASH: {p} -> {dest}")
            shutil.move(str(p), str(dest))
            return True

        # permanent
        if p.is_dir():
            print(f"DELETE DIR: {p}")
            shutil.rmtree(p)
        else:
            print(f"DELETE FILE: {p}")
            p.unlink()
        return True
    except Exception as e:
        print(f"ERROR: Failed to remove {p}: {e}")
        return False

def run_deletion(root: Path, targets: List[Path]) -> None:
    hr()
    removed = 0
    for p in dedupe_paths(targets):
        if SETTINGS.is_excluded(p):
            continue
        if delete_or_trash(root, p):
            removed += 1
    hr()
    if SETTINGS.dry_run:
        print(f"DONE: Would remove {removed} item(s).")
    else:
        print(f"DONE: Removed {removed} item(s).")

# ---------------- Actions ----------------
def action_delete_dirs_named(root: Path, name: str) -> None:
    targets = list(find_dirs_named(root, name))
    title = f"Search: directories named '{name}'\nRoot:   {root}"
    if preview_and_confirm(title, targets):
        run_deletion(root, targets)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

def action_delete_files_named(root: Path, filename: str) -> None:
    targets = list(find_files_named(root, filename))
    title = f"Search: files named '{filename}'\nRoot:   {root}"
    if preview_and_confirm(title, targets):
        run_deletion(root, targets)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

def action_builds_cleanup(root: Path) -> None:
    targets_names = ["build", "dist", "out", "Builds", ".nuxt", "coverage", ".turbo", ".parcel-cache"]
    found: List[Path] = []
    for t in targets_names:
        found.extend(list(find_dirs_named(root, t)))

    title = (
        "Search: common build output directories\n"
        f"Root:   {root}\n"
        f"Targets: {', '.join(targets_names)}"
    )
    if preview_and_confirm(title, found):
        run_deletion(root, found)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

# ---------------- Next.js ----------------
def action_nextjs_full(root: Path) -> None:
    dir_targets = [".next", "out", ".vercel", ".swc", ".turbo"]
    file_targets = ["next-env.d.ts"]

    found: List[Path] = []
    for d in dir_targets:
        found.extend(list(find_dirs_named(root, d)))
    for f in file_targets:
        found.extend(list(find_files_named(root, f)))

    title = (
        "Next.js: full cleanup\n"
        f"Root:   {root}\n"
        f"Dirs:   {', '.join(dir_targets)}\n"
        f"Files:  {', '.join(file_targets)}"
    )
    if preview_and_confirm(title, found):
        run_deletion(root, found)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

def action_nextjs_cache_only(root: Path) -> None:
    found: List[Path] = []
    found.extend(list(find_dirs_by_exact_suffix(root, [".next", "cache"])))
    found.extend(list(find_dirs_named(root, ".turbo")))

    title = (
        "Next.js: cache-only cleanup\n"
        f"Root:   {root}\n"
        "Targets: .next/cache, .turbo"
    )
    if preview_and_confirm(title, found):
        run_deletion(root, found)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

# ---------------- Python cache (pycache) ----------------
def action_python_caches(root: Path) -> None:
    cache_dirs = ["__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"]
    found: List[Path] = []
    for d in cache_dirs:
        found.extend(list(find_dirs_named(root, d)))

    title = (
        "Python: cache cleanup\n"
        f"Root:   {root}\n"
        f"Targets: {', '.join(cache_dirs)}"
    )
    if preview_and_confirm(title, found):
        run_deletion(root, found)
    else:
        print("CANCELLED or nothing to delete (or dry-run).")

# =========================
# Option 10: Parameters
# =========================
def print_settings() -> None:
    hr()
    print("PARAMETERS")
    hr()
    print(f"Dry-run (no delete):        {SETTINGS.dry_run}")
    print(f"Max scan depth (0=unlim):   {SETTINGS.max_depth}")
    print(f"Exclude tokens:             {', '.join(SETTINGS.exclude_tokens) if SETTINGS.exclude_tokens else '(none)'}")
    print(f"Delete mode:                {SETTINGS.delete_mode}  (permanent|trash)")
    print(f"Auto-confirm (skip y/N):    {SETTINGS.auto_confirm}")
    hr()

def settings_menu() -> str:
    clear_screen()
    print(BANNER)
    print_settings()
    print("1) Toggle Dry-run")
    print("2) Set Max scan depth (0 = unlimited)")
    print("3) Edit Exclude tokens (comma-separated)")
    print("4) Set Delete mode (permanent/trash)")
    print("5) Toggle Auto-confirm (skip y/N prompt)")
    print("0) Back")
    hr()
    return input("Choice: ").strip()

def action_parameters() -> None:
    while True:
        c = settings_menu()
        if c == "0":
            return

        if c == "1":
            SETTINGS.dry_run = not SETTINGS.dry_run
            print(f"Dry-run set to: {SETTINGS.dry_run}")
            pause()

        elif c == "2":
            val = input("Enter max scan depth (0 = unlimited): ").strip()
            try:
                n = int(val)
                if n < 0:
                    raise ValueError
                SETTINGS.max_depth = n
                print(f"Max depth set to: {SETTINGS.max_depth}")
            except Exception:
                print("ERROR: Invalid number.")
            pause()

        elif c == "3":
            val = input("Exclude tokens (comma-separated, empty to clear): ").strip()
            if not val:
                SETTINGS.exclude_tokens = []
                print("Exclude tokens cleared.")
            else:
                tokens = [t.strip() for t in val.split(",") if t.strip()]
                SETTINGS.exclude_tokens = tokens
                print("Exclude tokens set.")
            pause()

        elif c == "4":
            val = input("Delete mode (permanent/trash): ").strip().lower()
            if val in ("permanent", "trash"):
                SETTINGS.delete_mode = val
                print(f"Delete mode set to: {SETTINGS.delete_mode}")
                if val == "trash":
                    print("NOTE: Items will be moved under: <root>/.shdel_trash/<timestamp>/")
            else:
                print("ERROR: Invalid mode.")
            pause()

        elif c == "5":
            SETTINGS.auto_confirm = not SETTINGS.auto_confirm
            print(f"Auto-confirm set to: {SETTINGS.auto_confirm}")
            pause()

        else:
            print("Invalid choice.")
            pause()

# ---------------- Main Menu ----------------
def menu() -> str:
    clear_screen()
    print(BANNER)
    print("1) Delete node_modules")
    print("2) Delete .venv")
    print("3) Delete .cache")
    print("4) Delete .DS_Store")
    print("5) Delete common build folders (build/dist/out/...)")
    print("6) Clean everything (1-5 + Python caches)")
    print("7) Next.js full cleanup (.next, out, .vercel, .swc, .turbo + next-env.d.ts)")
    print("8) Next.js cache-only cleanup (.next/cache + .turbo)")
    print("9) Python cache cleanup (__pycache__, .pytest_cache, .mypy_cache, .ruff_cache)")
    print("10) Parameters (configure scan & deletion)")
    print("0) Quit")
    hr()
    return input("Choice: ").strip()

def main() -> None:
    while True:
        choice = menu()

        if choice == "0":
            print("Bye.")
            return

        if choice == "10":
            action_parameters()
            continue

        root = ask_path()
        if not guard_path(root):
            pause()
            continue

        if choice == "1":
            action_delete_dirs_named(root, "node_modules")
        elif choice == "2":
            action_delete_dirs_named(root, ".venv")
        elif choice == "3":
            action_delete_dirs_named(root, ".cache")
        elif choice == "4":
            action_delete_files_named(root, ".DS_Store")
        elif choice == "5":
            action_builds_cleanup(root)
        elif choice == "6":
            action_delete_dirs_named(root, "node_modules")
            action_delete_dirs_named(root, ".venv")
            action_delete_dirs_named(root, ".cache")
            action_delete_files_named(root, ".DS_Store")
            action_builds_cleanup(root)
            action_python_caches(root)
        elif choice == "7":
            action_nextjs_full(root)
        elif choice == "8":
            action_nextjs_cache_only(root)
        elif choice == "9":
            action_python_caches(root)
        else:
            print("Invalid choice.")

        pause()

if __name__ == "__main__":
    main()
