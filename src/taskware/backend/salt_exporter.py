from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SaltConfig:
    master_url: str = "https://localhost:8000"
    eauth: str = "pam"  # pam, ldap, etc.
    username: str = ""
    verify_tls: bool = True
    token: Optional[str] = None  # prefer tokens over passwords
    target_type: str = "glob"  # glob, list, grain, nodegroup
    target: str = "*"
    push_mode: str = "generate"  # generate | salt-api | salt-ssh | gitfs
    default_user: str = os.environ.get("USER", "")


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def job_to_sls(job: Dict) -> str:
    """
    Convert a Taskware job dict into a Salt SLS YAML string using cron.present.
    Expected job keys: id, command, schedule (cron string), description (optional), user (optional), extras (optional dict)
    If extras['biweekly'] is True, create a wrapper script resource and point cron to it.
    """
    job_id = str(job.get("id") or job.get("job_id") or _slug(job.get("command", "job")))
    cmd = str(job.get("command", ""))
    cron = str(job.get("schedule", "* * * * *"))
    description = str(job.get("description")) if job.get("description") else ""
    user = str(job.get("user") or os.environ.get("USER", ""))
    extras = job.get("extras") or {}

    parts = cron.split()
    if len(parts) != 5:
        parts = ["*", "*", "*", "*", "*"]
    minute, hour, daymonth, month, dayweek = parts

    sls_id = f"taskware_job_{_slug(job_id)}"

    # Base cron.present resource template
    cron_block = f"""
{sls_id}:
  cron.present:
    - name: "{cmd}"
    - user: "{user}"
    - minute: "{minute}"
    - hour: "{hour}"
    - daymonth: "{daymonth}"
    - month: "{month}"
    - dayweek: "{dayweek}"
    - comment: "Taskware {job_id} — {description}"
""".strip("\n")

    # Biweekly wrapper: install a small gate script and have cron run it
    if extras.get("biweekly"):
        # Choose anchor based on optional extras['biweekly_anchor'] (YYYY-MM-DD) if present
        # otherwise default to 0. For simplicity, default 0.
        wrapper_name = f"/usr/local/bin/taskware-biweekly-{_slug(job_id)}"
        wrapper_id = f"{sls_id}_wrapper_script"
        wrapper_contents = f"""#!/usr/bin/env bash
# Taskware biweekly gate for {job_id}
# Anchor parity configurable; default 0
week_parity=$(date +%V)
week_parity=$((10#$week_parity % 2))
if [ "$week_parity" -eq "{int(extras.get('anchor_parity', 0))}" ]; then
  exec {cmd}
else
  exit 0
fi
"""
        sls = f"""
{wrapper_id}:
  file.managed:
    - name: {wrapper_name}
    - mode: '0755'
    - user: root
    - group: root
    - contents: |
{_indent(wrapper_contents, 6)}

{sls_id}:
  cron.present:
    - name: "{wrapper_name}"
    - user: "{user}"
    - minute: "{minute}"
    - hour: "{hour}"
    - dayweek: "{dayweek}"
    - comment: "Taskware Biweekly {job_id} — {description}"
    - require:
      - file: {wrapper_id}
""".strip("\n")
        return sls

    return cron_block


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else pad for line in text.splitlines())


def export_job_to_files(job: Dict, out_dir: str) -> str:
    """
    Write SLS to out_dir with a stable filename and return that path.
    """
    os.makedirs(out_dir, exist_ok=True)
    job_id = str(job.get("id") or job.get("job_id") or _slug(job.get("command", "job")))
    fname = f"taskware_{_slug(job_id)}.sls"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(job_to_sls(job) + "\n")
    return path
