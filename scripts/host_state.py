"""Host clock and boot identity for run provenance.

The school machine (206-40) dual-boots Windows, which writes local time to the
RTC. Linux reads the RTC as UTC, so right after a boot the wall clock is off by
the UTC offset (+9 h in KST) until NTP steps it. Every run therefore records
which boot it ran in and whether NTP was synchronized, and refuses to start
while it is not.
"""
from datetime import datetime, timezone
from pathlib import Path
import subprocess

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
STAT_PATH = Path("/proc/stat")


def ntp_synchronized(runner=subprocess.run):
    """'yes', 'no' or 'unknown' (no timedatectl / no systemd)."""
    try:
        p = runner(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                   capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = (p.stdout or "").strip()
    return value if p.returncode == 0 and value in ("yes", "no") else "unknown"


def host_clock(boot_id_path=BOOT_ID_PATH, stat_path=STAT_PATH, runner=subprocess.run):
    """boot_id, boot time (from /proc/stat btime, i.e. after any NTP step) and NTP state."""
    try:
        boot_id = Path(boot_id_path).read_text(encoding="ascii").strip()
    except OSError:
        boot_id = None
    booted_at = None
    try:
        for line in Path(stat_path).read_text(encoding="ascii").splitlines():
            if line.startswith("btime "):
                booted_at = datetime.fromtimestamp(int(line.split()[1]), timezone.utc).isoformat()
                break
    except (OSError, ValueError):
        pass
    return {"boot_id": boot_id, "booted_at": booted_at, "ntp_synchronized": ntp_synchronized(runner),
            "observed_at": datetime.now(timezone.utc).isoformat()}


def require_ntp(clock):
    if clock.get("ntp_synchronized") != "yes":
        raise ValueError("NTP not synchronized (timedatectl NTPSynchronized=%s); wait after boot "
                         "(dual-boot RTC offset) and retry" % clock.get("ntp_synchronized"))


def reboot_errors(start, end):
    """Errors to record when the boot changed between two host_clock() observations."""
    if not start or not end:
        return []
    if start.get("boot_id") and end.get("boot_id") and start["boot_id"] != end["boot_id"]:
        return ["host rebooted during run (boot_id %s -> %s, booted_at %s)"
                % (start["boot_id"], end["boot_id"], end.get("booted_at"))]
    return []
