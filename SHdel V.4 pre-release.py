#!/usr/bin/env python3
import os
import json
import shutil
import subprocess
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


||   / /                  //   ) )     //   ) )     //   / /
||  / /   //___/ /       //___/ /     //___/ /     //____
|| / /   /____  /       / ____ /     / ___ (      / ____
||/ /        / /       //           //   | |     //
|  /        / /       //           //    | |    //____/ /



 ©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France
"""

# =========================
# Settings (Parameters)
# =========================
@dataclass
class Settings:
    dry_run: bool = False
    max_depth: int = 0  # 0 = unlimited
    exclude_tokens: List[str] = field(default_factory=lambda: [".git", ".shdel_trash", ".shdel_logs"])
    delete_mode: str = "permanent"  # "permanent" or "trash"
    auto_confirm: bool = False

    def is_excluded(self, p: Path) -> bool:
        s = str(p)
        return any(tok and tok in s for tok in self.exclude_tokens)

SETTINGS = Settings()

# =========================
# Logs + Registry
# =========================
LOGS_DIRNAME = ".shdel_logs"
SERVERS_REGISTRY_NAME = "shdel_servers.json"   # stored in user's home by default

def registry_path() -> Path:
    home = Path.home()
    return home / SERVERS_REGISTRY_NAME

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

        if SETTINGS.max_depth and SETTINGS.max_depth > 0:
            try:
                rel_depth = len(cur.relative_to(root).parts)
            except Exception:
                rel_depth = 0
            if rel_depth >= SETTINGS.max_depth:
                dirs[:] = []

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
    kind: str
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
    action: str
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

    with fpath.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False)

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
            print(f"{action.upper()}: {it.path}")
        elif action == "skipped":
            skipped += 1
            print(f"SKIP: {it.path} ({err})")
        else:
            failed += 1
            print(f"FAILED: {it.path} ({err})")

        results.append(DeletionResultItem(path=it.path, action=action, error=err))

    finished = datetime.now().isoformat(timespec="seconds")

    hr()
    print("DELETION DONE")
    print(f"Mode:        {SETTINGS.delete_mode}")
    print(f"Removed:     {removed}")
    print(f"Failed:      {failed}")
    print(f"Skipped:     {skipped}")
    print(f"Target size: {format_bytes(plan.total_size_bytes)}")
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
# Deletion Actions
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
                SETTINGS.exclude_tokens = [t.strip() for t in val.split(",") if t.strip()]
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
# Option 11: Review deletion logs (JSON)
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
    total_size = int(data.get("total_size_bytes", 0) or 0)
    mode = data.get("mode", "?")
    return (
        f"Title:   {title}\n"
        f"Start:   {started}\n"
        f"End:     {finished}\n"
        f"Mode:    {mode}\n"
        f"Items:   {total_items}\n"
        f"Removed: {removed}  Failed: {failed}  Skipped: {skipped}\n"
        f"Size:    {format_bytes(total_size)}"
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
    show = reports[:20]
    for i, rp in enumerate(show, start=1):
        print(f"{i:>2}) {rp.name}")
    hr()

    choice = input("Select a report number to view (or press Enter to go back): ").strip()
    if not choice:
        return
    try:
        idx = int(choice)
        if idx < 1 or idx > len(show):
            raise ValueError
    except Exception:
        print("ERROR: Invalid selection.")
        pause()
        return

    selected = show[idx - 1]
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

    if confirm("Print full results list (path + action)?"):
        results = data.get("results", [])
        if not isinstance(results, list):
            print("ERROR: Invalid report format.")
            pause()
            return
        print("ACTION    PATH")
        print("-" * 90)
        for r in results:
            action = str(r.get("action", ""))
            path = str(r.get("path", ""))
            print(f"{action:<9} {path}")
        hr()

    pause()

# =========================
# NEW: NPM Server Runner + Registry (Options 12 & 13)
# =========================
def npm_exists() -> bool:
    return shutil.which("npm") is not None or shutil.which("npm.cmd") is not None

def is_node_project(project_dir: Path) -> bool:
    return (project_dir / "package.json").exists()

def load_servers_registry() -> List[Dict[str, Any]]:
    rp = registry_path()
    if not rp.exists():
        return []
    try:
        data = json.loads(rp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

def save_servers_registry(entries: List[Dict[str, Any]]) -> None:
    rp = registry_path()
    try:
        rp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"ERROR: Could not save registry: {rp} ({e})")

def register_server(project_dir: Path, name: Optional[str] = None) -> None:
    entries = load_servers_registry()
    p = str(project_dir)

    # avoid duplicates by path
    for e in entries:
        if str(e.get("path", "")) == p:
            e["name"] = e.get("name") or (name or project_dir.name)
            e["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_servers_registry(entries)
            print("Server path already registered (updated).")
            return

    entries.append({
        "name": name or project_dir.name,
        "path": p,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "last_started_at": None,
    })
    save_servers_registry(entries)
    print(f"Registered: {p}")
    print(f"Registry file: {registry_path()}")

def update_last_started(project_dir: Path) -> None:
    entries = load_servers_registry()
    p = str(project_dir)
    changed = False
    for e in entries:
        if str(e.get("path", "")) == p:
            e["last_started_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
            break
    if changed:
        save_servers_registry(entries)

def run_command_stream(cmd: List[str], cwd: Path, save_output_to: Optional[Path] = None) -> int:
    """
    Runs a command and streams combined stdout/stderr to the console.
    If save_output_to is provided, writes the same output to that file.
    """
    log_f = None
    try:
        if save_output_to:
            save_output_to.parent.mkdir(parents=True, exist_ok=True)
            log_f = save_output_to.open("w", encoding="utf-8")

        creationflags = 0
        preexec_fn = None
        if os.name != "nt":
            # Start a new process group so we can interrupt the whole group
            preexec_fn = os.setsid  # type: ignore[attr-defined]
        else:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            preexec_fn=preexec_fn,
            creationflags=creationflags,
        )

        assert p.stdout is not None
        for line in p.stdout:
            print(line, end="")
            if log_f:
                log_f.write(line)
        return p.wait()

    except KeyboardInterrupt:
        print("\nINTERRUPT: Stopping process...")
        try:
            if os.name != "nt":
                import signal
                os.killpg(p.pid, signal.SIGINT)  # type: ignore[name-defined]
            else:
                p.send_signal(subprocess.signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
        try:
            return p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
            return 130

    finally:
        if log_f:
            log_f.close()

def action_npm_install_and_dev() -> None:
    if not npm_exists():
        print("ERROR: npm not found in PATH.")
        pause()
        return

    project = ask_path("Project path (Node/Next project folder): ")
    if not guard_path(project):
        pause()
        return

    if not is_node_project(project):
        print("ERROR: package.json not found in this folder.")
        pause()
        return

    print(f"Project: {project}")
    hr()
    if not confirm("Run 'npm install' then 'npm run dev'?"):
        print("CANCELLED")
        pause()
        return

    save_terminal = confirm("Save terminal output to a log file in .shdel_logs?")
    out_log: Optional[Path] = None
    if save_terminal:
        out_log = logs_dir(project) / ("npm-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".log")
        print(f"Output log: {out_log}")

    hr()
    print("RUN: npm install")
    hr()
    code_install = run_command_stream(["npm", "install"], cwd=project, save_output_to=out_log)
    hr()
    print(f"npm install exit code: {code_install}")
    hr()

    if code_install != 0:
        print("ERROR: npm install failed. Not starting dev server.")
        pause()
        return

    if confirm("Register this project path for quick start later?"):
        default_name = project.name
        name = input(f"Name (Enter for '{default_name}'): ").strip() or default_name
        register_server(project, name=name)

    print("RUN: npm run dev")
    print("INFO: Press Ctrl+C to stop the dev server and return to the menu.")
    hr()
    update_last_started(project)
    _ = run_command_stream(["npm", "run", "dev"], cwd=project, save_output_to=out_log)
    hr()
    print("Dev server stopped.")
    pause()

def action_start_registered_server() -> None:
    if not npm_exists():
        print("ERROR: npm not found in PATH.")
        pause()
        return

    entries = load_servers_registry()
    if not entries:
        print("INFO: No registered servers found.")
        print(f"Registry file: {registry_path()}")
        pause()
        return

    clear_screen()
    print(BANNER)
    print(f"Registry: {registry_path()}")
    hr()
    print("Registered servers:")
    for i, e in enumerate(entries, start=1):
        name = str(e.get("name", "Unnamed"))
        path = str(e.get("path", ""))
        last = e.get("last_started_at") or "-"
        print(f"{i:>2}) {name}")
        print(f"    Path: {path}")
        print(f"    Last: {last}")
    hr()

    choice = input("Select a server number to start (or press Enter to go back): ").strip()
    if not choice:
        return
    try:
        idx = int(choice)
        if idx < 1 or idx > len(entries):
            raise ValueError
    except Exception:
        print("ERROR: Invalid selection.")
        pause()
        return

    selected = entries[idx - 1]
    project = Path(str(selected.get("path", ""))).expanduser()
    try:
        project = project.resolve()
    except Exception:
        project = project.absolute()

    if not guard_path(project):
        pause()
        return
    if not is_node_project(project):
        print("ERROR: package.json not found in this folder.")
        pause()
        return

    save_terminal = confirm("Save terminal output to a log file in .shdel_logs?")
    out_log: Optional[Path] = None
    if save_terminal:
        out_log = logs_dir(project) / ("npm-dev-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".log")
        print(f"Output log: {out_log}")

    if not confirm(f"Start dev server now? (npm run dev)"):
        print("CANCELLED")
        pause()
        return

    update_last_started(project)
    print("INFO: Press Ctrl+C to stop the dev server and return to the menu.")
    hr()
    _ = run_command_stream(["npm", "run", "dev"], cwd=project, save_output_to=out_log)
    hr()
    print("Dev server stopped.")
    pause()

# =========================
# Main Menu
# =========================
def menu() -> str:
    clear_screen()
    print(BANNER)
    print("1)  Delete node_modules")
    print("2)  Delete .venv")
    print("3)  Delete .cache")
    print("4)  Delete .DS_Store")
    print("5)  Delete common build folders (build/dist/out/...)")
    print("6)  Clean everything (1-5 + Python caches)")
    print("7)  Next.js full cleanup (.next, out, .vercel, .swc, .turbo + next-env.d.ts)")
    print("8)  Next.js cache-only cleanup (.next/cache + .turbo)")
    print("9)  Python cache cleanup (__pycache__, .pytest_cache, .mypy_cache, .ruff_cache)")
    print("10) Parameters (configure scan & deletion)")
    print("11) Review deletion logs (JSON reports)")
    print("12) Node: npm install + npm run dev (optionally register project)")
    print("13) Start a registered dev server (npm run dev)")
    print("0)  Quit")
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

        if choice == "12":
            action_npm_install_and_dev()
            continue

        if choice == "13":
            action_start_registered_server()
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
