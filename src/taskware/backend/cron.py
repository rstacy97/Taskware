from __future__ import annotations

import re
import subprocess
import uuid
import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


MARK = "taskware"
MARK_RE = re.compile(r"#\s*taskware:id=([a-f0-9\-]+)\s+enabled=(0|1)\s*$")

# Data directories
DATA_DIR = Path(os.path.expanduser("~/.local/share/taskware"))
LOGS_DIR = DATA_DIR / "logs"
JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CronJob:
    id: str
    schedule: str
    command: str
    enabled: bool

    def to_line(self) -> str:
        base = f"{self.schedule} {self.command}"
        suffix = f" # {MARK}:id={self.id} enabled={'1' if self.enabled else '0'}"
        line = base + suffix
        return line if self.enabled else f"# {line}"


def _run_crontab_list() -> List[str]:
    try:
        cp = subprocess.run(["crontab", "-l"], check=False, text=True, capture_output=True)
    except FileNotFoundError:
        # crontab not available
        return []
    if cp.returncode != 0:
        # No crontab set typically returns exit 1 with message
        return []
    return cp.stdout.splitlines()


def _write_crontab(lines: List[str]) -> None:
    text = "\n".join(lines).rstrip() + "\n" if lines else "\n"
    cp = subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(f"Failed to write crontab: {cp.stderr.strip()}")


def _parse_taskware_job(line: str) -> Optional[CronJob]:
    enabled = True
    raw = line
    if raw.strip().startswith("#"):
        enabled = False
        raw = raw.lstrip()[1:].lstrip()  # strip leading '# '
    m = MARK_RE.search(raw)
    if not m:
        return None
    job_id = m.group(1)
    enabled_flag = m.group(2) == "1"
    # remove trailing marker to get schedule+command
    body = MARK_RE.sub("", raw).rstrip()
    parts = body.split()
    if len(parts) < 6:
        return None
    schedule = " ".join(parts[:5])
    command = " ".join(parts[5:])
    return CronJob(id=job_id, schedule=schedule, command=command, enabled=(enabled and enabled_flag))


def _is_valid_schedule(expr: str) -> bool:
    # Very loose validation: 5 fields
    return len(expr.split()) == 5


def _script_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.sh"


def _status_path(job_id: str) -> Path:
    return LOGS_DIR / f"{job_id}.status"


def _meta_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_job_script(job_id: str, user_command: str, guard: Optional[str] = None, one_time_cleanup: bool = False) -> Path:
    script = _script_path(job_id)
    status_file = _status_path(job_id)
    guard_block = ""
    if guard:
        guard_block = guard + "\n"
    cleanup_block = ""
    if one_time_cleanup:
        # Remove our crontab line and cleanup files after first execution
        cleanup_block = f"\n# One-time cleanup: remove job from crontab and delete files\n" \
                        f"tmpfile=$(mktemp)\n" \
                        f"crontab -l | sed '/{MARK}:id={job_id} /d' > \"$tmpfile\" && crontab \"$tmpfile\" && rm -f \"$tmpfile\"\n" \
                        f"rm -f {str(script)!r} {str(status_file)!r} {str(_meta_path(job_id))!r}\n"
    script_content = f"""#!/usr/bin/env bash
set -o pipefail

ts=$(date -Is)
{guard_block}# Run user command
eval {user_command!r}
status=$?
echo "$ts|$status" >> {str(status_file)!r}
exit $status
{cleanup_block}
"""
    script.write_text(script_content)
    os.chmod(script, 0o700)
    return script


def _read_last_status(job_id: str) -> Tuple[Optional[str], Optional[int]]:
    p = _status_path(job_id)
    if not p.exists():
        return None, None
    try:
        with p.open("r") as f:
            lines = f.read().strip().splitlines()
        if not lines:
            return None, None
        last = lines[-1]
        ts, sep, code = last.partition("|")
        return (ts if ts else None), (int(code) if code.isdigit() else None)
    except Exception:
        return None, None


def list_user_jobs() -> List[Dict[str, object]]:
    jobs: List[Dict[str, object]] = []
    for line in _run_crontab_list():
        job = _parse_taskware_job(line)
        if job:
            # Prefer original command from metadata if present
            meta_file = _meta_path(job.id)
            original_cmd = None
            description = None
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text() or "{}")
                    original_cmd = meta.get("original_command")
                    description = meta.get("description")
                except Exception:
                    original_cmd = None
                    description = None
            last_ts, last_exit = _read_last_status(job.id)
            jobs.append({
                "id": job.id,
                "schedule": job.schedule,
                "command": original_cmd or job.command,
                "enabled": job.enabled,
                "last_run": last_ts,
                "last_exit": last_exit,
                "description": description,
            })
    return jobs


def _biweekly_guard(anchor_iso: str) -> str:
    """Return a POSIX shell guard that exits early on off-weeks based on an anchor date (YYYY-MM-DD)."""
    # Try GNU date first, fallback to BSD date -j
    return (
        "ANCHOR=\"" + anchor_iso + "\"\n"
        "AEpoch=$(date -d \"$ANCHOR 00:00:00\" +%s 2>/dev/null || date -j -f %Y-%m-%d\ %H:%M:%S \"$ANCHOR 00:00:00\" +%s 2>/dev/null)\n"
        "Now=$(date +%s)\n"
        "if [ -n \"$AEpoch\" ]; then weeks=$(( (Now - AEpoch) / 604800 )); else weeks=0; fi\n"
        "if [ $((weeks % 2)) -ne 0 ]; then exit 0; fi"
    )


def _one_time_guard(target_iso: str) -> str:
    """Return a shell guard that exits until the wall clock reaches the target ISO time (YYYY-MM-DDTHH:MM)."""
    return (
        "TARGET=\"" + target_iso + "\"\n"
        "TEpoch=$(date -d \"$TARGET\" +%s 2>/dev/null || date -j -f %Y-%m-%dT%H:%M \"$TARGET\" +%s 2>/dev/null)\n"
        "Now=$(date +%s)\n"
        "if [ -n \"$TEpoch\" ] && [ \"$Now\" -lt \"$TEpoch\" ]; then exit 0; fi"
    )


def add_user_job(schedule: str, command: str, description: Optional[str] = None, extra: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    if not _is_valid_schedule(schedule):
        raise ValueError("Invalid cron expression; expected 5 fields (min hour dom mon dow)")
    job_id = str(uuid.uuid4())
    # Create wrapper script that logs status and runs the user's command
    guard = None
    meta_extra: Dict[str, object] = {}
    one_time = False
    if isinstance(extra, dict):
        meta_extra.update(extra)
        if extra.get("biweekly"):
            anchor = str(extra.get("biweekly_anchor") or "")
            if not anchor:
                # default to today
                anchor = os.popen("date +%Y-%m-%d").read().strip() or "1970-01-01"
            guard = _biweekly_guard(anchor)
        if extra.get("one_time"):
            one_time = True
            target = str(extra.get("one_time_at") or "")
            if target:
                og = _one_time_guard(target)
                guard = (guard + "\n" + og) if guard else og
    script = _write_job_script(job_id, command, guard, one_time_cleanup=one_time)
    # Write metadata for display
    meta = {"original_command": command}
    if description is not None:
        meta["description"] = description
    if meta_extra:
        meta.update(meta_extra)
    _meta_path(job_id).write_text(json.dumps(meta))
    # Cron should execute the script path
    job = CronJob(id=job_id, schedule=schedule, command=str(script), enabled=True)
    lines = _run_crontab_list()
    lines.append(job.to_line())
    _write_crontab(lines)
    return {"id": job.id, "schedule": job.schedule, "command": command, "enabled": job.enabled, "description": description}


def set_user_job_enabled(job_id: str, enabled: bool) -> None:
    lines = _run_crontab_list()
    new_lines: List[str] = []
    found = False
    for line in lines:
        job = _parse_taskware_job(line)
        if job and job.id == job_id:
            found = True
            job.enabled = enabled
            new_lines.append(job.to_line())
        else:
            new_lines.append(line)
    if not found:
        raise ValueError("Job not found")
    _write_crontab(new_lines)


def delete_user_job(job_id: str) -> None:
    """Delete a Taskware-managed job by its id and clean up its files."""
    lines = _run_crontab_list()
    new_lines: List[str] = []
    found = False
    for line in lines:
        job = _parse_taskware_job(line)
        if job and job.id == job_id:
            found = True
            continue  # skip this line to delete
        new_lines.append(line)
    if not found:
        raise ValueError("Job not found")
    _write_crontab(new_lines)

    # Cleanup files (best-effort)
    for p in (_script_path(job_id), _status_path(job_id), _meta_path(job_id)):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def update_user_job(job_id: str, schedule: str, command: str, description: Optional[str] = None, extra: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Update an existing Taskware-managed job's schedule and/or command.
    Preserves enabled state. Rewrites wrapper script and metadata if command changes.
    Returns the updated job summary.
    """
    if not _is_valid_schedule(schedule):
        raise ValueError("Invalid cron expression; expected 5 fields (min hour dom mon dow)")

    lines = _run_crontab_list()
    new_lines: List[str] = []
    found = False
    enabled_state = True
    for line in lines:
        job = _parse_taskware_job(line)
        if job and job.id == job_id:
            found = True
            enabled_state = job.enabled
            # Rewrite wrapper script and metadata
            # Merge old metadata to preserve extra fields unless overridden
            # Preserve existing description if not provided
            meta_file = _meta_path(job_id)
            old_desc = None
            old_meta: Dict[str, object] = {}
            try:
                if meta_file.exists():
                    old_meta = json.loads(meta_file.read_text() or "{}")
                    old_desc = old_meta.get("description")
            except Exception:
                old_desc = None
            new_meta: Dict[str, object] = {"original_command": command}
            if description is not None:
                new_meta["description"] = description
            elif old_desc is not None:
                new_meta["description"] = old_desc
            # Handle biweekly extra
            guard = None
            if isinstance(extra, dict) and extra.get("biweekly"):
                anchor = str(extra.get("biweekly_anchor") or old_meta.get("biweekly_anchor") or "")
                if not anchor:
                    anchor = os.popen("date +%Y-%m-%d").read().strip() or "1970-01-01"
                new_meta["biweekly"] = True
                new_meta["biweekly_anchor"] = anchor
                guard = _biweekly_guard(anchor)
            else:
                # Preserve previous biweekly settings if present
                if old_meta.get("biweekly") and old_meta.get("biweekly_anchor"):
                    new_meta["biweekly"] = old_meta.get("biweekly")
                    new_meta["biweekly_anchor"] = old_meta.get("biweekly_anchor")
                    guard = _biweekly_guard(str(old_meta.get("biweekly_anchor")))
            # Handle one-time extra
            one_time = False
            if isinstance(extra, dict) and extra.get("one_time"):
                target = str(extra.get("one_time_at") or old_meta.get("one_time_at") or "")
                if target:
                    og = _one_time_guard(target)
                    guard = (guard + "\n" + og) if guard else og
                new_meta["one_time"] = True
                new_meta["one_time_at"] = target
                one_time = True
            else:
                if old_meta.get("one_time") and old_meta.get("one_time_at"):
                    new_meta["one_time"] = old_meta.get("one_time")
                    new_meta["one_time_at"] = old_meta.get("one_time_at")
                    og = _one_time_guard(str(old_meta.get("one_time_at")))
                    guard = (guard + "\n" + og) if guard else og
                    one_time = True
            _write_job_script(job_id, command, guard, one_time_cleanup=one_time)
            meta_file.write_text(json.dumps(new_meta))
            # Replace line with new schedule and script path
            updated = CronJob(id=job_id, schedule=schedule, command=str(_script_path(job_id)), enabled=enabled_state)
            new_lines.append(updated.to_line())
        else:
            new_lines.append(line)

    if not found:
        raise ValueError("Job not found")
    _write_crontab(new_lines)
    # Read back description for return value
    ret_desc = None
    try:
        meta = json.loads(_meta_path(job_id).read_text() or "{}")
        ret_desc = meta.get("description")
    except Exception:
        ret_desc = None
    return {"id": job_id, "schedule": schedule, "command": command, "enabled": enabled_state, "description": ret_desc}


def set_user_job_description(job_id: str, description: Optional[str]) -> None:
    """Update only the description metadata for a job (no schedule/command changes)."""
    meta_file = _meta_path(job_id)
    if not meta_file.exists():
        raise ValueError("Job not found")
    try:
        meta = json.loads(meta_file.read_text() or "{}")
    except Exception:
        meta = {}
    if description is None:
        # Remove description key if None
        meta.pop("description", None)
    else:
        meta["description"] = description
    meta_file.write_text(json.dumps(meta))
