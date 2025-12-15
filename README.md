# SHdel

©2025 Shervin Nosrati ©2025 - 2025 SHdel TM, ®Shervin. All rights reserved. France

SHdel is a single-file terminal application (Python) that helps you quickly clean common development artifacts (Node, Python, Next.js, build folders), preview what will be removed (with sizes), optionally move items to a local “trash” folder, save deletion reports as JSON, and even start an npm dev server from the same app.

---

## Features

### Cleaning & Removal
- Delete `node_modules`
- Delete `.venv`
- Delete `.cache`
- Delete `.DS_Store`
- Delete common build output folders: `build`, `dist`, `out`, `Builds`, `.nuxt`, `coverage`, `.turbo`, `.parcel-cache`
- Next.js full cleanup: `.next`, `out`, `.vercel`, `.swc`, `.turbo` + `next-env.d.ts`
- Next.js cache-only cleanup: `.next/cache` + `.turbo`
- Python cache cleanup: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`

### Preview Before Delete
Before deleting anything, SHdel:
- scans the target directory
- prints a full list of items that will be removed
- shows the size of each item
- shows the total size to be removed
- asks for confirmation `(y/N)` before deletion

### Configurable Parameters
SHdel includes a “Parameters” menu where you can configure how scanning and deletion behaves:
- Dry-run: preview only, do not delete
- Max scan depth: limit recursion (0 = unlimited)
- Exclude tokens: skip matching paths (example: `.git`)
- Delete mode:
  - `permanent`: deletes immediately
  - `trash`: moves items into `<root>/.shdel_trash/<timestamp>/`
- Auto-confirm: skip confirmation prompts (use with caution)

### JSON Reports for Deletions
After a deletion run, SHdel can optionally save a JSON report:
- stored inside: `<project>/.shdel_logs/`
- filename format: `YYYYMMDD-HHMMSS.json`
- includes:
  - start/end timestamps
  - settings used
  - full list of deleted/trashed/skipped/failed items
  - total count and total size

### Review Past Deletions
SHdel can list and open your recent JSON deletion reports from:
- `<project>/.shdel_logs/`

### Node / Next.js Dev Server (npm)
SHdel can also run npm commands from within the app:
- Option 12: run `npm install` then `npm run dev` for a project path
  - can optionally register the project for quick startup later
- Option 13: start a previously registered project (`npm run dev`)

#### Registered Servers
Registered project paths are saved in:
- `~/shdel_servers.json`

#### Windows Compatibility
On Windows, npm is often `npm.cmd`. SHdel resolves the correct executable and runs it safely through `cmd.exe /c` when required.

---

## Requirements

- Python 3.9+ recommended (works on Windows/macOS/Linux)
- For npm features:
  - Node.js installed
  - `npm` available in your PATH

---

## Installation

1. Save the script as `shdel.py`
2. Run:

### Windows (PowerShell)
```powershell
python .\shdel.py
