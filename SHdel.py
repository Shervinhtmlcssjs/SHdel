#©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France
#!/usr/bin/env python3
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Set

BANNER = r"""
     ____         _     __          
    //   ) )     //    / /            /
   ((           //___ / /      ___   /      ___       //
     \\        / ___   /     //   ) /     //___) )   //
       ) )    //    / /     //   / /     //         //
((___ / /    //    / /     ((___/ /     ((____     //=======


 ©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France
"""

# ---------------- UI helpers ----------------
def hr() -> None:
    print("-" * 72)

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
        # Avoid drive root like C:\
        s = root_str.rstrip("\\/")
        if len(s) == 2 and s[1] == ":":
            print("ERROR: Refusing drive root path.")
            return False
    if not root.exists() or not root.is_dir():
        print(f"ERROR: Directory not found: {root}")
        return False
    return True

def confirm(msg: str) -> bool:
    ans = input(f"{msg} (y/N): ").strip().lower()
    return ans in ("y", "yes")

# ---------------- Finders (with prune) ----------------
def find_dirs_named(root: Path, dirname: str) -> Iterable[Path]:
    """
    Finds directories named `dirname` under `root`.
    Uses topdown walk so we can prune and avoid descending into matches.
    """
    for current, dirs, _files in os.walk(root, topdown=True):
        if dirname in dirs:
            target = Path(current) / dirname
            yield target
            dirs.remove(dirname)  # prune

def find_dirs_by_exact_suffix(root: Path, suffix_parts: List[str]) -> Iterable[Path]:
    """
    Finds directories matching an exact path suffix, e.g. [".next","cache"] -> .../.next/cache
    """
    suffix = os.sep.join(suffix_parts)
    for current, dirs, _files in os.walk(root, topdown=True):
        # Examine children dirs; prune when we match
        for d in list(dirs):
            candidate = Path(current) / d
            if str(candidate).endswith(suffix):
                yield candidate
                dirs.remove(d)  # prune

def find_files_named(root: Path, filename: str) -> Iterable[Path]:
    for current, _dirs, files in os.walk(root):
        for f in files:
            if f == filename:
                yield Path(current) / f

# ---------------- Delete ----------------
def delete_path(p: Path) -> bool:
    if not p.exists():
        print(f"SKIP: Already gone: {p}")
        return False
    try:
        if p.is_dir():
            print(f"DELETE DIR: {p}")
            shutil.rmtree(p)
        else:
            print(f"DELETE FILE: {p}")
            p.unlink()
        return True
    except Exception as e:
        print(f"ERROR: Failed to delete {p}: {e}")
        return False

def dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: Set[str] = set()
    out: List[Path] = []
    for p in paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            out.append(p)
    return out

def print_found(paths: List[Path], label: str) -> None:
    if not paths:
        print("INFO: Nothing found.")
        return
    print(f"FOUND ({label}): {len(paths)} item(s)")
    for p in paths:
        print(f"  - {p}")

# ---------------- Actions ----------------
def delete_dirs(root: Path, name: str) -> None:
    hr()
    print(f"Search: directories named '{name}'")
    print(f"Root:   {root}")
    hr()

    targets = list(find_dirs_named(root, name))
    print_found(targets, f"dir '{name}'")
    if not targets:
        return

    if not confirm(f"Confirm deletion of {len(targets)} directory(ies) named '{name}'?"):
        print("CANCELLED")
        return

    hr()
    removed = 0
    for d in targets:
        if delete_path(d):
            removed += 1
    hr()
    print(f"DONE: Removed {removed} directory(ies) named '{name}'")

def delete_files(root: Path, filename: str) -> None:
    hr()
    print(f"Search: files named '{filename}'")
    print(f"Root:   {root}")
    hr()

    targets = list(find_files_named(root, filename))
    print_found(targets, f"file '{filename}'")
    if not targets:
        return

    if not confirm(f"Confirm deletion of {len(targets)} file(s) named '{filename}'?"):
        print("CANCELLED")
        return

    hr()
    removed = 0
    for f in targets:
        if delete_path(f):
            removed += 1
    hr()
    print(f"DONE: Removed {removed} file(s) named '{filename}'")

def builds_cleanup(root: Path) -> None:
    targets = ["build", "dist", "out", "Builds", ".nuxt", "coverage", ".turbo", ".parcel-cache"]
    hr()
    print("Search: common build output directories")
    print(f"Root:   {root}")
    print("Targets:", ", ".join(targets))
    hr()

    found: List[Path] = []
    for t in targets:
        found.extend(list(find_dirs_named(root, t)))

    found = dedupe_paths(found)
    print_found(found, "build output directories")
    if not found:
        return

    if not confirm(f"Confirm deletion of {len(found)} build directory(ies)?"):
        print("CANCELLED")
        return

    hr()
    removed = 0
    for p in found:
        if delete_path(p):
            removed += 1
    hr()
    print(f"DONE: Removed {removed} build directory(ies)")

# ---------------- Next.js ----------------
def nextjs_cleanup_full(root: Path) -> None:
    dir_targets = [".next", "out", ".vercel", ".swc", ".turbo"]
    file_targets = ["next-env.d.ts"]

    hr()
    print("Next.js: full cleanup")
    print(f"Root:   {root}")
    print("Dirs:   " + ", ".join(dir_targets))
    print("Files:  " + ", ".join(file_targets))
    hr()

    found_dirs: List[Path] = []
    for d in dir_targets:
        found_dirs.extend(list(find_dirs_named(root, d)))

    found_files: List[Path] = []
    for f in file_targets:
        found_files.extend(list(find_files_named(root, f)))

    all_found = dedupe_paths(found_dirs + found_files)
    if not all_found:
        print("INFO: Nothing found.")
        return

    print(f"FOUND: {len(all_found)} item(s)")
    for p in all_found:
        kind = "DIR " if p.is_dir() else "FILE"
        print(f"  - {kind}: {p}")

    if not confirm(f"Confirm deletion of {len(all_found)} Next.js item(s)?"):
        print("CANCELLED")
        return

    hr()
    removed = 0
    for p in all_found:
        if delete_path(p):
            removed += 1
    hr()
    print(f"DONE: Removed {removed} Next.js item(s)")

def nextjs_cleanup_cache_only(root: Path) -> None:
    hr()
    print("Next.js: cache-only cleanup")
    print(f"Root:   {root}")
    print("Targets: .next/cache, .turbo")
    hr()

    found: List[Path] = []
    found.extend(list(find_dirs_by_exact_suffix(root, [".next", "cache"])))
    found.extend(list(find_dirs_named(root, ".turbo")))

    found = dedupe_paths(found)
    print_found(found, "Next.js cache directories")
    if not found:
        return

    if not confirm(f"Confirm deletion of {len(found)} Next.js cache directory(ies)?"):
        print("CANCELLED")
        return

    hr()
    removed = 0
    for p in found:
        if delete_path(p):
            removed += 1
    hr()
    print(f"DONE: Removed {removed} Next.js cache directory(ies)")

# ---------------- Menu ----------------
def menu() -> str:
    clear_screen()
    print(BANNER)
    print("________________________________________________________________________________________")
    print("1) Delete node_modules")
    print("2) Delete .venv")
    print("3) Delete .cache")
    print("4) Delete .DS_Store")
    print("5) Delete common build folders (build/dist/out/...)")
    print("6) Clean everything (1-5)")
    print("7) Next.js full cleanup (.next, out, .vercel, .swc, .turbo + next-env.d.ts)")
    print("8) Next.js cache-only cleanup (.next/cache + .turbo)")
    print("0) Quit")
    print("________________________________________________________________________________________")
    #hr()
    return input("Choice: ").strip()

def main() -> None:
    while True:
        choice = menu()

        if choice == "0":
            print("Bye.")
            return

        root = ask_path()
        if not guard_path(root):
            pause()
            continue

        if choice == "1":
            delete_dirs(root, "node_modules")
        elif choice == "2":
            delete_dirs(root, ".venv")
        elif choice == "3":
            delete_dirs(root, ".cache")
        elif choice == "4":
            delete_files(root, ".DS_Store")
        elif choice == "5":
            builds_cleanup(root)
        elif choice == "6":
            delete_dirs(root, "node_modules")
            delete_dirs(root, ".venv")
            delete_dirs(root, ".cache")
            delete_files(root, ".DS_Store")
            builds_cleanup(root)
        elif choice == "7":
            nextjs_cleanup_full(root)
        elif choice == "8":
            nextjs_cleanup_cache_only(root)
        else:
            print("Invalid choice.")

        pause()

if __name__ == "__main__":
    main()
