from __future__ import annotations

import subprocess
import re
from typing import List, Dict
from pathlib import Path
import os

# Columns from `systemctl --user list-timers --all --no-legend --no-pager`
# Example line (columns separated by 2+ spaces):
# NEXT                          LEFT       LAST                          PASSED    UNIT                         ACTIVATES
# Mon 2025-09-22 12:00:00 EDT   1min left  Mon 2025-09-22 11:00:00 EDT   1h ago    example.timer                example.service

_SPLIT_RE = re.compile(r"\s{2,}")


def _run_systemctl_list_timers(user: bool = True) -> List[str]:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    # Do NOT include --all so that disabled timers don't linger in UI lists
    cmd += ["list-timers", "--no-legend", "--no-pager"]
    try:
        cp = subprocess.run(cmd, check=False, text=True, capture_output=True)
    except FileNotFoundError:
        return []
    if cp.returncode != 0:
        return []
    return [ln for ln in cp.stdout.splitlines() if ln.strip()]


def list_user_timers() -> List[Dict[str, object]]:
    timers: List[Dict[str, object]] = []
    for line in _run_systemctl_list_timers(user=True):
        parts = _SPLIT_RE.split(line.strip())
        if len(parts) < 6:
            # Some systemd versions may omit LAST/PASSED when never run; pad safely
            parts = (parts + ["", "", "", "", "", ""])[:6]
        next_time, left, last_time, passed, unit, activates = parts[:6]
        timers.append({
            "unit": unit,
            "activates": activates,
            "next": next_time,
            "left": left,
            "last": last_time,
            "passed": passed,
        })
    return timers


def list_system_timers() -> List[Dict[str, object]]:
    """List system-level timers (requires permission to query systemctl)."""
    timers: List[Dict[str, object]] = []
    for line in _run_systemctl_list_timers(user=False):
        parts = _SPLIT_RE.split(line.strip())
        if len(parts) < 6:
            parts = (parts + ["", "", "", "", "", ""])[:6]
        next_time, left, last_time, passed, unit, activates = parts[:6]
        timers.append({
            "unit": unit,
            "activates": activates,
            "next": next_time,
            "left": left,
            "last": last_time,
            "passed": passed,
        })
    return timers


def _run(cmd: list[str]) -> None:
    cp = subprocess.run(cmd, text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"Failed: {' '.join(cmd)}")


def daemon_reload(user: bool = True) -> None:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["daemon-reload"]
    _run(cmd)


def start_timer(unit: str, user: bool = True) -> None:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["start", unit]
    _run(cmd)


def stop_timer(unit: str, user: bool = True) -> None:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["stop", unit]
    _run(cmd)


def enable_timer(unit: str, user: bool = True) -> None:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["enable", unit]
    _run(cmd)


def disable_timer(unit: str, user: bool = True) -> None:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["disable", unit]
    _run(cmd)


def _user_unit_dir() -> Path:
    p = Path(os.path.expanduser("~/.config/systemd/user"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def add_timer(name: str, command: str, oncalendar: str) -> Dict[str, str]:
    """Create a user-level systemd service/timer and enable it.
    Name is the base (without .timer/.service). Returns units created.
    """
    if not name or any(ch in name for ch in " /\t\n"):
        raise ValueError("Invalid unit name")
    unit_dir = _user_unit_dir()
    service = unit_dir / f"{name}.service"
    timer = unit_dir / f"{name}.timer"
    service.write_text(f"""[Unit]
Description=Taskware service {name}

[Service]
Type=oneshot
ExecStart={command}
""")
    timer.write_text(f"""[Unit]
Description=Taskware timer {name}

[Timer]
OnCalendar={oncalendar}
Persistent=true

[Install]
WantedBy=timers.target
""")
    # Reload and enable/start
    daemon_reload(user=True)
    enable_timer(f"{name}.timer", user=True)
    start_timer(f"{name}.timer", user=True)


def delete_timer_root(name: str) -> None:
    """Delete a system-level timer via pkexec."""
    # Ensure pkexec exists
    if subprocess.run(["which", "pkexec"], text=True, capture_output=True).returncode != 0:
        raise RuntimeError("pkexec not found. Please install a polkit agent or use sudo manually.")
    script = (
        f"set -e -x\n"
        f"/usr/bin/systemctl disable --now {name}.timer || true\n"
        f"/usr/bin/systemctl stop {name}.service || true\n"
        f"/usr/bin/systemctl mask {name}.timer || true\n"
        f"/usr/bin/rm -f /etc/systemd/system/{name}.timer /etc/systemd/system/{name}.service || true\n"
        f"/usr/bin/rm -f /etc/systemd/system/timers.target.wants/{name}.timer || true\n"
        f"/usr/bin/rm -f /run/systemd/generator/{name}.timer /run/systemd/generator.late/{name}.timer /run/systemd/generator.early/{name}.timer || true\n"
        f"/usr/bin/systemctl daemon-reload\n"
        f"/usr/bin/systemctl daemon-reexec || true\n"
        f"/usr/bin/systemctl reset-failed || true\n"
    )
    cp = subprocess.run(["pkexec", "/bin/sh", "-c", script], text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "Failed to delete root timer")
    # Verify removal
    if unit_exists(name, is_timer=True, user=False) or unit_exists(name, is_timer=False, user=False):
        raise RuntimeError("Timer/service still present after deletion; systemd refused or recreated the unit")


def _read_file(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""


def read_unit_details(name: str, user: bool = True) -> Dict[str, str]:
    """Read ExecStart and OnCalendar from service/timer unit files."""
    base = _user_unit_dir() if user else Path("/etc/systemd/system")
    svc_text = _read_file(base / f"{name}.service")
    tim_text = _read_file(base / f"{name}.timer")
    exec_start = ""
    oncal = ""
    for line in svc_text.splitlines():
        s = line.strip()
        if s.startswith("ExecStart="):
            exec_start = s.split("=", 1)[1]
            break
    for line in tim_text.splitlines():
        s = line.strip()
        if s.startswith("OnCalendar="):
            oncal = s.split("=", 1)[1]
            break
    # Fallback to systemctl show if missing
    if not exec_start:
        cmd = ["systemctl"]
        if user:
            cmd.append("--user")
        cmd += ["show", f"{name}.service", "-p", "ExecStart", "--no-pager"]
        try:
            cp = subprocess.run(cmd, text=True, capture_output=True)
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    if line.startswith("ExecStart="):
                        exec_start = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    if not oncal:
        cmd = ["systemctl"]
        if user:
            cmd.append("--user")
        cmd += ["show", f"{name}.timer", "-p", "TimersCalendar", "--no-pager"]
        try:
            cp = subprocess.run(cmd, text=True, capture_output=True)
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    if line.startswith("TimersCalendar="):
                        val = line.split("=", 1)[1].strip()
                        # This field may contain multiple; pick the first fragment before ';'
                        oncal = val.split(';', 1)[0].strip()
                        break
        except Exception:
            pass
    return {"command": exec_start, "oncalendar": oncal}


def update_timer(name: str, command: str, oncalendar: str, user: bool = True) -> None:
    """Update timer/service units and reload systemd, enabling and starting the timer."""
    if user:
        unit_dir = _user_unit_dir()
        (unit_dir / f"{name}.service").write_text(
            f"[Unit]\nDescription=Taskware service {name}\n\n[Service]\nType=oneshot\nExecStart=={command}\n".replace("==","=")
        )
        (unit_dir / f"{name}.timer").write_text(
            f"[Unit]\nDescription=Taskware timer {name}\n\n[Timer]\nOnCalendar=={oncalendar}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n".replace("==","=")
        )
        daemon_reload(user=True)
        enable_timer(f"{name}.timer", user=True)
        start_timer(f"{name}.timer", user=True)
    else:
        if subprocess.run(["which", "pkexec"], text=True, capture_output=True).returncode != 0:
            raise RuntimeError("pkexec not found. Please install a polkit agent or use sudo manually.")
        service_path = f"/etc/systemd/system/{name}.service"
        timer_path = f"/etc/systemd/system/{name}.timer"
        service_content = (
            f"[Unit]\nDescription=Taskware service {name}\n\n"
            f"[Service]\nType=oneshot\nExecStart={command}\n"
        )
        timer_content = (
            f"[Unit]\nDescription=Taskware timer {name}\n\n"
            f"[Timer]\nOnCalendar={oncalendar}\nPersistent=true\n\n"
            f"[Install]\nWantedBy=timers.target\n"
        )
        script = (
            f"set -e\n"
            f"cat > {service_path} << 'EOF_SVC'\n{service_content}\nEOF_SVC\n"
            f"cat > {timer_path} << 'EOF_TIM'\n{timer_content}\nEOF_TIM\n"
            f"/usr/bin/systemctl daemon-reload\n"
            f"/usr/bin/systemctl enable {name}.timer\n"
            f"/usr/bin/systemctl start {name}.timer\n"
        )
        cp = subprocess.run(["pkexec", "/bin/sh", "-c", script], text=True, capture_output=True)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "Failed to update root timer")


def unit_exists(name: str, is_timer: bool = True, user: bool = True) -> bool:
    unit = f"{name}.timer" if is_timer else f"{name}.service"
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["show", unit, "-p", "LoadState", "--no-pager"]
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True)
        if cp.returncode != 0:
            return False
        for line in cp.stdout.splitlines():
            if line.startswith("LoadState="):
                return line.split("=", 1)[1].strip() != "not-found"
        return False
    except Exception:
        return False


def delete_timer_completely(name: str, user: bool = True) -> Dict[str, object]:
    """Strongly attempt to delete a timer and its paired service, returning a detailed log and success flag.
    user=True targets ~/.config/systemd/user; user=False targets /etc/systemd/system via pkexec.
    """
    log: list[str] = []
    ok = True
    try:
        if user:
            # Stop/disable timer, stop service
            for args in (
                ["systemctl", "--user", "disable", "--now", f"{name}.timer"],
                ["systemctl", "--user", "stop", f"{name}.service"],
            ):
                cp = subprocess.run(args, text=True, capture_output=True)
                log.append(f"$ {' '.join(args)}\n{cp.stdout}{cp.stderr}")
            # Remove units and wants link
            unit_dir = _user_unit_dir()
            for p in (unit_dir / f"{name}.timer", unit_dir / f"{name}.service"):
                try:
                    if p.exists():
                        p.unlink()
                        log.append(f"removed {p}")
                except Exception as e:
                    log.append(f"error removing {p}: {e}")
                    ok = False
            wants = unit_dir / "timers.target.wants" / f"{name}.timer"
            try:
                if wants.exists():
                    wants.unlink()
                    log.append(f"removed {wants}")
            except Exception as e:
                log.append(f"error removing {wants}: {e}")
                ok = False
            # Reload/reset
            for args in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "reset-failed"],
            ):
                cp = subprocess.run(args, text=True, capture_output=True)
                log.append(f"$ {' '.join(args)}\n{cp.stdout}{cp.stderr}")
        else:
            # Root scope via pkexec: set -e -x for visibility
            script = (
                f"set -e -x\n"
                f"/usr/bin/systemctl disable --now {name}.timer || true\n"
                f"/usr/bin/systemctl stop {name}.service || true\n"
                f"/usr/bin/systemctl mask {name}.timer || true\n"
                f"/usr/bin/rm -f /etc/systemd/system/{name}.timer /etc/systemd/system/{name}.service || true\n"
                f"/usr/bin/rm -f /etc/systemd/system/timers.target.wants/{name}.timer || true\n"
                f"/usr/bin/rm -f /run/systemd/generator/{name}.timer /run/systemd/generator.late/{name}.timer /run/systemd/generator.early/{name}.timer || true\n"
                f"/usr/bin/systemctl daemon-reload\n"
                f"/usr/bin/systemctl daemon-reexec || true\n"
                f"/usr/bin/systemctl reset-failed || true\n"
            )
            cp = subprocess.run(["pkexec", "/bin/sh", "-c", script], text=True, capture_output=True)
            log.append(cp.stdout)
            if cp.returncode != 0:
                ok = False
                log.append(cp.stderr)
        # Verify removal
        t_user = unit_exists(name, is_timer=True, user=True)
        t_root = unit_exists(name, is_timer=True, user=False)
        s_user = unit_exists(name, is_timer=False, user=True)
        s_root = unit_exists(name, is_timer=False, user=False)
        if t_user or t_root or s_user or s_root:
            ok = False
            log.append(f"still present: timer(user)={t_user} timer(root)={t_root} service(user)={s_user} service(root)={s_root}")
    except Exception as e:
        ok = False
        log.append(f"exception: {e}")
    return {"ok": ok, "log": "\n".join(log)}


def delete_service(name: str) -> None:
    """Delete a user-level service unit and reload."""
    unit_dir = _user_unit_dir()
    svc = unit_dir / f"{name}.service"
    try:
        if svc.exists():
            svc.unlink()
    except Exception:
        pass
    try:
        _run(["systemctl", "--user", "daemon-reload"])  # type: ignore[list-item]
        _run(["systemctl", "--user", "reset-failed"])  # type: ignore[list-item]
    except Exception:
        pass


def delete_service_root(name: str) -> None:
    """Delete a system-level service unit via pkexec and reload."""
    if subprocess.run(["which", "pkexec"], text=True, capture_output=True).returncode != 0:
        raise RuntimeError("pkexec not found. Please install polkit agent or use sudo manually.")
    service_path = f"/etc/systemd/system/{name}.service"
    script = (
        f"set -e -x\n"
        f"/usr/bin/systemctl stop {name}.service || true\n"
        f"/usr/bin/rm -f {service_path} || true\n"
        f"/usr/bin/systemctl daemon-reload\n"
        f"/usr/bin/systemctl daemon-reexec || true\n"
        f"/usr/bin/systemctl reset-failed || true\n"
    )
    cp = subprocess.run(["pkexec", "/bin/sh", "-c", script], text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "Failed to delete root service")
    if unit_exists(name, is_timer=False, user=False):
        raise RuntimeError("Service still present after deletion; systemd refused or recreated the unit")


def delete_any_timer(name: str) -> None:
    """Delete timer choosing scope by existence; try both if uncertain."""
    tried: list[str] = []
    # Prefer user if present
    if unit_exists(name, is_timer=True, user=True):
        tried.append("user")
        delete_timer(name)
        return
    # Else prefer root if present
    if unit_exists(name, is_timer=True, user=False):
        tried.append("root")
        delete_timer_root(name)
        return
    # Unknown: attempt both best-effort
    err = []
    try:
        tried.append("user")
        delete_timer(name)
        return
    except Exception as e:
        err.append(str(e))
    try:
        tried.append("root")
        delete_timer_root(name)
    except Exception as e:
        err.append(str(e))
    if err:
        raise RuntimeError("; ".join(err))


def is_taskware_timer(name: str, user: bool = True) -> bool:
    """Detect if the timer was created by Taskware by scanning unit files for our description marker."""
    base = _user_unit_dir() if user else Path("/etc/systemd/system")
    timer_path = base / f"{name}.timer"
    svc_path = base / f"{name}.service"
    marker = "Description=Taskware timer"
    try:
        if timer_path.exists() and marker in timer_path.read_text():
            return True
    except Exception:
        pass
    try:
        if svc_path.exists() and marker in svc_path.read_text():
            return True
    except Exception:
        pass
    return False


def add_timer_root(name: str, command: str, oncalendar: str) -> Dict[str, str]:
    """Create a system-level (root) timer under /etc/systemd/system via pkexec.
    Requires interactive authentication. Returns paths to created units.
    """
    if not name or any(ch in name for ch in " /\t\n"):
        raise ValueError("Invalid unit name")
    # Check pkexec availability
    if subprocess.run(["which", "pkexec"], text=True, capture_output=True).returncode != 0:
        raise RuntimeError("pkexec not found. Please install polkit agent or use sudo manually.")

    service_path = f"/etc/systemd/system/{name}.service"
    timer_path = f"/etc/systemd/system/{name}.timer"
    service_content = (
        f"[Unit]\nDescription=Taskware service {name}\n\n"
        f"[Service]\nType=oneshot\nExecStart={command}\n"
    )
    timer_content = (
        f"[Unit]\nDescription=Taskware timer {name}\n\n"
        f"[Timer]\nOnCalendar={oncalendar}\nPersistent=true\n\n"
        f"[Install]\nWantedBy=timers.target\n"
    )

    script = (
        f"set -e\n"
        f"cat > {service_path} << 'EOF_SVC'\n{service_content}\nEOF_SVC\n"
        f"cat > {timer_path} << 'EOF_TIM'\n{timer_content}\nEOF_TIM\n"
        f"/usr/bin/systemctl daemon-reload\n"
        f"/usr/bin/systemctl enable {name}.timer\n"
        f"/usr/bin/systemctl start {name}.timer\n"
    )

    # Run via pkexec /bin/sh -c "script"
    cp = subprocess.run(["pkexec", "/bin/sh", "-c", script], text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "Failed to create root timer")
    return {"service": service_path, "timer": timer_path}


def delete_timer(name: str) -> None:
    unit_dir = _user_unit_dir()
    timer_unit = f"{name}.timer"
    # best-effort stop/disable
    try:
        stop_timer(timer_unit, user=True)
    except Exception:
        pass
    try:
        disable_timer(timer_unit, user=True)
    except Exception:
        pass
    # remove files
    for p in (unit_dir / f"{name}.timer", unit_dir / f"{name}.service"):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    # Remove wants symlink if present
    wants = unit_dir / "timers.target.wants" / f"{name}.timer"
    try:
        if wants.exists():
            wants.unlink()
    except Exception:
        pass
    daemon_reload(user=True)
    # reset failed in user scope
    try:
        _run(["systemctl", "--user", "reset-failed"])  # type: ignore[list-item]
    except Exception:
        pass
