"""Host clock and boot identity for run provenance.

The school machine (206-40) dual-boots Windows, which writes local time to the
RTC. Linux reads the RTC as UTC, so right after a boot the wall clock is off by
the UTC offset (+9 h in KST) until NTP steps it. Every run therefore records
which boot it ran in and whether NTP was synchronized, and refuses to start
while it is not.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
STAT_PATH = Path("/proc/stat")
LOCAL_ENV_PATH = Path(__file__).resolve().parents[1] / "linux" / "config" / "local.env"
ENV_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def ntp_synchronized(runner=subprocess.run):
    """'yes', 'no' or 'unknown' (no timedatectl / no systemd)."""
    try:
        p = runner(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                   capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = (p.stdout or "").strip()
    return value if p.returncode == 0 and value in ("yes", "no") else "unknown"


def local_env(path=LOCAL_ENV_PATH):
    """KEY=VALUE pairs of linux/config/local.env (machine-local, not in Git)."""
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def environment_id(environ=None, local_env_path=LOCAL_ENV_PATH, hostname=socket.gethostname):
    """Collection PC identity for parallel collection (= shard name, k3s node name,
    run records' environment_id). SENTRIX_ENVIRONMENT_ID in the environment, else
    in linux/config/local.env, else the hostname. Lowercase letters, digits and
    single hyphens only; anything else (e.g. hostname "D" on 206-39) is refused so
    the PC must set an ID instead of collecting under a wrong one."""
    environ = os.environ if environ is None else environ
    for source, value in (("SENTRIX_ENVIRONMENT_ID", environ.get("SENTRIX_ENVIRONMENT_ID")),
                          (str(local_env_path), local_env(local_env_path).get("SENTRIX_ENVIRONMENT_ID")),
                          ("hostname", hostname())):
        if value:
            if not ENV_ID.fullmatch(value):
                raise ValueError(f"environment id {value!r} from {source} is not lowercase letters, digits and "
                                 "hyphens; set SENTRIX_ENVIRONMENT_ID in linux/config/local.env "
                                 "(see linux/config/local.env.example)")
            return value
    raise ValueError("no environment id: set SENTRIX_ENVIRONMENT_ID in linux/config/local.env")


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


if __name__ == "__main__":   # shell scripts: ID=$(python3 scripts/host_state.py)
    try:
        print(environment_id())
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
