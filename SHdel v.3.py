#!/usr/bin/env python3
import os
import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Set, Tuple, Optional, Dict, Any

BANNER = r"""
     ____         _     __          
    //   ) )     //    / /            /
   ((           //___ / /      ___   /      ___       //
     \\        / ___   /     //   ) /     //___) )   //
       ) )    //    / /     //   / /     //         //
((___ / /    //    / /     ((___/ /     ((____     //=======

||   / /     ___
||  / /    //   ) )
|| / /      __ / /
||/ /          ) )
|  /     ((___/ /



 ©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France
"""

# =========================
# Settings (Parameters)
# =========================
@dataclass
class Settings:
    dry_run: bool = False                 # Preview + no deletion
    max_depth: int = 0                    # 0 = unlimited
    exclude_tokens: List[str] = field(default_factory=lambda: [".git", ".shdel_trash", ".shdel_logs"])
    delete_mode: str = "permanent"        # "permanent" or "trash"
    auto_confirm: bool = False            # If True: skip y/N prompt and proceed

    def is_excluded(self, p: Path) -> bool:
        s = str(p)
        return any(tok and tok in s for tok in self.exclude_tokens)

SETTINGS = Settings()

# =========================
# Logging
# =========================
LOGS_DIRNAME = ".shdel_logs"
LAST_POINTER = "last_report.txt"  # stores the filename of the last report inside logs folder


# ---------------- UI helpers ----------------
def hr() -> None:
    print("-" * 90)

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")

def pause() -> None:
    input("Press Enter to continue...")

def ask_path(prompt: str = "Target directory path (e.g. . or /path/to/project): ") -> Path:
    p = input(prompt).strip() or "."
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

# ---------------- Finders ----------------
def find_dirs_named(root: Path, dirname: str) -> Iterable[Path]:
    for cur, dirs, _files in walk_scoped(root):
        if dirname in dirs:
            target = cur / dirname
            if not SETTINGS.is_excluded(target):
                yield target
            try:
                dirs.remove(dirname)  # prune
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
                try:
                    dirs.remove(d)  # prune
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

# ---------------- Utilities ----------------
def dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: Set[str] = set()
    out: List[Path] = []
    for p in paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            out.append(p)
    return out

@dataclass
class PlanItem:
    path: str
    kind: str          # DIR or FILE
    size_bytes: int

@dataclass
class DeletionPlan:
    root: str
    title: str
    created_at: str
    settings: Dict[str, Any]
    items: List[PlanItem]
    total_size_bytes: int

@dataclass
class DeletionResultItem:
    path: str
    action: str        # deleted | trashed | skipped | failed
    error: Optional[str] = None

@dataclass
class DeletionReport:
    root: str
    title: str
    started_at: str
    finished_at: str
    settings: Dict[str, Any]
    total_items: int
    total_size_bytes: int
    removed_count: int
    failed_count: int
    skipped_count: int
    mode: str
    results: List[DeletionResultItem]

def build_plan(root: Path, title: str, targets: List[Path]) -> Optional[DeletionPlan]:
    filtered = [p for p in dedupe_paths(targets) if not SETTINGS.is_excluded(p)]
    if not filtered:
        return None

    items: List[PlanItem] = []
    total = 0
    for p in filtered:
        kind = "DIR" if p.is_dir() else "FILE"
        sz = path_size_bytes(p)
        total += sz
        items.append(PlanItem(path=str(p), kind=kind, size_bytes=sz))

    # sort: largest first then path
    items.sort(key=lambda x: (-x.size_bytes, x.path))

    return DeletionPlan(
        root=str(root),
        title=title,
        created_at=datetime.now().isoformat(timespec="seconds"),
        settings=asdict(SETTINGS),
        items=items,
        total_size_bytes=total,
    )

def preview_plan_and_confirm(plan: DeletionPlan) -> bool:
    hr()
    print(plan.title)
    hr()
    print(f"FOUND: {len(plan.items)} item(s)")
    print("SIZE             TYPE  PATH")
    print("-" * 90)
    for it in plan.items:
        print(f"{format_bytes(it.size_bytes):<16} {it.kind:<4}  {it.path}")
    print("-" * 90)
    print(f"TOTAL SIZE: {format_bytes(plan.total_size_bytes)}")
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

def delete_or_trash(root: Path, p: Path) -> Tuple[str, Optional[str]]:
    if not p.exists():
        return "skipped", "already missing"

    if SETTINGS.dry_run:
        return "skipped", "dry-run"

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
            shutil.move(str(p), str(dest))
            return "trashed", None

        # permanent delete
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return "deleted", None

    except Exception as e:
        return "failed", str(e)

def logs_dir(root: Path) -> Path:
    d = root / LOGS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_report_prompt(root: Path, report: DeletionReport) -> None:
    if SETTINGS.dry_run:
        return

    if not confirm("Save deletion report as JSON?"):
        return

    d = logs_dir(root)
    fname = datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
    fpath = d / fname

    data = asdict(report)
    with fpath.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # update last pointer
    (d / LAST_POINTER).write_text(fname, encoding="utf-8")

    print(f"Report saved: {fpath}")

def run_deletion_with_logging(root: Path, plan: DeletionPlan) -> None:
    started = datetime.now().isoformat(timespec="seconds")
    removed = 0
    failed = 0
    skipped = 0
    results: List[DeletionResultItem] = []

    hr()
    print("DELETION START")
    hr()

    for it in plan.items:
        p = Path(it.path)

        if SETTINGS.is_excluded(p):
            skipped += 1
            results.append(DeletionResultItem(path=it.path, action="skipped", error="excluded"))
            print(f"SKIP: excluded: {it.path}")
            continue

        action, err = delete_or_trash(root, p)
        if action in ("deleted", "trashed"):
            removed += 1
            if action == "deleted":
                print(f"DELETE: {it.path}")
            else:
                print(f"TRASH:  {it.path}")
        elif action == "skipped":
            skipped += 1
            print(f"SKIP:   {it.path} ({err})")
        else:
            failed += 1
            print(f"FAILED: {it.path} ({err})")

        results.append(DeletionResultItem(path=it.path, action=action, error=err))

    finished = datetime.now().isoformat(timespec="seconds")

    hr()
    print("DELETION DONE")
    print(f"Mode:          {SETTINGS.delete_mode}")
    print(f"Removed:       {removed}")
    print(f"Failed:        {failed}")
    print(f"Skipped:       {skipped}")
    print(f"Target size:   {format_bytes(plan.total_size_bytes)}")
    hr()

    report = DeletionReport(
        root=plan.root,
        title=plan.title,
        started_at=started,
        finished_at=finished,
        settings=plan.settings,
        total_items=len(plan.items),
        total_size_bytes=plan.total_size_bytes,
        removed_count=removed,
        failed_count=failed,
        skipped_count=skipped,
        mode=SETTINGS.delete_mode,
        results=results,
    )

    save_report_prompt(Path(plan.root), report)

# =========================
# Actions
# =========================
def action_delete_dirs_named(root: Path, name: str) -> None:
    targets = list(find_dirs_named(root, name))
    title = f"Search: directories named '{name}'\nRoot:   {root}"
    plan = build_plan(root, title, targets)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

def action_delete_files_named(root: Path, filename: str) -> None:
    targets = list(find_files_named(root, filename))
    title = f"Search: files named '{filename}'\nRoot:   {root}"
    plan = build_plan(root, title, targets)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

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
    plan = build_plan(root, title, found)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

# Next.js
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
    plan = build_plan(root, title, found)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

def action_nextjs_cache_only(root: Path) -> None:
    found: List[Path] = []
    found.extend(list(find_dirs_by_exact_suffix(root, [".next", "cache"])))
    found.extend(list(find_dirs_named(root, ".turbo")))

    title = (
        "Next.js: cache-only cleanup\n"
        f"Root:   {root}\n"
        "Targets: .next/cache, .turbo"
    )
    plan = build_plan(root, title, found)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

# Python caches
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
    plan = build_plan(root, title, found)
    if not plan:
        print("INFO: Nothing found.")
        return
    if preview_plan_and_confirm(plan):
        run_deletion_with_logging(root, plan)
    else:
        print("CANCELLED or dry-run.")

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
                    print("Note: Items will be moved under: <root>/.shdel_trash/<timestamp>/")
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

# =========================
# Option 11: Review recent deletions
# =========================
def read_json_safe(p: Path) -> Optional[Dict[str, Any]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def summarize_report(data: Dict[str, Any]) -> str:
    title = data.get("title", "Unknown")
    started = data.get("started_at", "?")
    finished = data.get("finished_at", "?")
    removed = data.get("removed_count", 0)
    failed = data.get("failed_count", 0)
    skipped = data.get("skipped_count", 0)
    total_items = data.get("total_items", 0)
    total_size = data.get("total_size_bytes", 0)
    mode = data.get("mode", "?")
    return (
        f"Title:   {title}\n"
        f"Start:   {started}\n"
        f"End:     {finished}\n"
        f"Mode:    {mode}\n"
        f"Items:   {total_items}\n"
        f"Removed: {removed}  Failed: {failed}  Skipped: {skipped}\n"
        f"Size:    {format_bytes(int(total_size))}"
    )

def action_review_deletions() -> None:
    root = ask_path("Project directory to review logs (e.g. . or /path/to/project): ")
    if not guard_path(root):
        pause()
        return

    d = root / LOGS_DIRNAME
    if not d.exists() or not d.is_dir():
        print(f"INFO: No logs folder found: {d}")
        pause()
        return

    reports = sorted([p for p in d.glob("*.json") if p.is_file()], reverse=True)
    if not reports:
        print("INFO: No JSON reports found.")
        pause()
        return

    clear_screen()
    print(BANNER)
    print(f"Logs folder: {d}")
    hr()
    print("Recent reports:")
    for i, rp in enumerate(reports[:20], start=1):
        print(f"{i:>2}) {rp.name}")
    hr()
    choice = input("Select a report number to view (or press Enter to go back): ").strip()
    if not choice:
        return
    try:
        idx = int(choice)
        if idx < 1 or idx > min(20, len(reports)):
            raise ValueError
    except Exception:
        print("ERROR: Invalid selection.")
        pause()
        return

    selected = reports[idx - 1]
    data = read_json_safe(selected)
    if not data:
        print("ERROR: Could not read this report as JSON.")
        pause()
        return

    clear_screen()
    print(BANNER)
    print(f"Report file: {selected}")
    hr()
    print(summarize_report(data))
    hr()

    if confirm("Print full list of results (paths + action)?"):
        results = data.get("results", [])
        if not isinstance(results, list):
            print("ERROR: Invalid report format.")
            pause()
            return
        print("ACTION   PATH")
        print("-" * 90)
        for r in results:
            action = str(r.get("action", ""))
            path = str(r.get("path", ""))
            print(f"{action:<7} {path}")
        hr()

    pause()

# =========================
# Main Menu
# =========================
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
    print("11) Review recent deletions (JSON reports)")
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

        if choice == "11":
            action_review_deletions()
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
