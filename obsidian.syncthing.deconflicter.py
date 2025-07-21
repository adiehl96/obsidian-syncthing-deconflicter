#!/usr/bin/env python3

import os
import re
import time
import subprocess
import requests
from datetime import datetime

# === CONFIGURATION ===
STVERSIONS_DIR = ".stversions"
LOG_PATH = "deconflicter.log"
API_KEY = os.environ.get("SYNCTHING_API_KEY")
FOLDER_ID = os.environ.get("SYNCTHING_FOLDER_ID")
SYNCTHING_URL = "http://localhost:8384"
CHECK_DIR = "."  # Directory to monitor for changes
MIN_IDLE_TIME = 600  # 10 minutes in seconds

CONFLICT_REGEX = re.compile(
    r"^(.*?)(?:\.|%2F)sync-conflict-\d{8}-\d{6}-\w{7}\.?(.*)$"
)

# === UTILITIES ===

def log_run(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")

def is_obsidian_running() -> bool:
    try:
        subprocess.check_output(["pgrep", "-x", "Obsidian"])
        return True
    except subprocess.CalledProcessError:
        return False

def is_syncthing_idle(folder_id: str) -> bool:
    try:
        response = requests.get(
            f"{SYNCTHING_URL}/rest/db/status?folder={folder_id}",
            headers={"X-API-Key": API_KEY},
            timeout=5
        )
        response.raise_for_status()
        return response.json().get("state") == "idle"
    except Exception as e:
        log_run(f"Error checking Syncthing status: {e}")
        return False

def no_recent_file_changes(path: str, seconds: int) -> bool:
    now = time.time()
    for dirpath, _, files in os.walk(path):
        for name in files:
            full_path = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(full_path) > now - seconds:
                    return False
            except FileNotFoundError:
                continue
    return True

# === MERGING LOGIC ===

def find_conflict_files(base_dir="."):
    for root, _, files in os.walk(base_dir):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), start=base_dir)
            if CONFLICT_REGEX.match(rel_path):
                yield rel_path

def find_backup_file(conflict_base, ext):
    pattern = re.compile(
        rf"{re.escape(STVERSIONS_DIR)}/{re.escape(conflict_base)}~\d{{8}}-\d{{6}}\." + re.escape(ext)
    )
    for dirpath, _, files in os.walk(STVERSIONS_DIR):
        for file in files:
            candidate = os.path.relpath(os.path.join(dirpath, file))
            if pattern.match(candidate):
                return candidate
    return None

def merge_files(original, backup, conflict):
    cmd = ["git", "merge-file", "--union", original, backup, conflict]
    result = subprocess.run(cmd, cwd=os.getcwd())
    return result.returncode == 0

def process_conflict(conflict_path):
    match = CONFLICT_REGEX.match(conflict_path)
    if not match:
        return False

    base_name, ext = match.groups()
    original = f"{base_name}.{ext}" if ext else base_name

    if not os.path.isfile(original):
        return False

    backup = find_backup_file(base_name, ext)
    if not backup:
        return False

    if merge_files(original, backup, conflict_path):
        os.remove(conflict_path)
        return True

    return False

# === MAIN ===

def main():
    if is_obsidian_running():
        log_run("Skipped: Obsidian is running")
        return

    if not is_syncthing_idle(FOLDER_ID):
        log_run("Skipped: Syncthing is active")
        return

    if not no_recent_file_changes(CHECK_DIR, MIN_IDLE_TIME):
        log_run("Skipped: recent file changes detected")
        return

    time.sleep(0.1)  # Give Syncthing time to settle moves
    conflicts = list(find_conflict_files())
    resolved_files = []

    for conflict in conflicts:
        if process_conflict(conflict):
            resolved_files.append(conflict)

    if resolved_files:
        summary = f"Resolved {len(resolved_files)} conflict(s): {', '.join(resolved_files)}"
    else:
        summary = "No conflicts found"

    log_run(summary)

if __name__ == "__main__":
    main()
