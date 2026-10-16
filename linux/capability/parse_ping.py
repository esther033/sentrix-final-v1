"""Print "<avg_rtt_ms> <loss_pct>" from iputils/busybox ping -q output (nan if absent)."""
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
loss = re.search(r"([\d.]+)% packet loss", text)
rtt = re.search(r"= [\d.]+/([\d.]+)/", text)
print(rtt.group(1) if rtt else "nan", loss.group(1) if loss else "nan")
