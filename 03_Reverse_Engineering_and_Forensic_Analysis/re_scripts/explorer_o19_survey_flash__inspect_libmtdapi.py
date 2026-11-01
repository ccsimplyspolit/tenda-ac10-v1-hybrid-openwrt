import re

ROOT = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\squashfs_root"
fpath = ROOT + r"\lib\libmtdapi.so"

with open(fpath, "rb") as f:
    data = f.read()

# Extract all ASCII strings >= 4 chars
strings = []
cur = []
for i, b in enumerate(data):
    if 32 <= b <= 126:
        cur.append(chr(b))
    else:
        if len(cur) >= 4:
            strings.append("".join(cur))
        cur = []

print("Strings in libmtdapi.so:")
for s in strings:
    if any(k in s.lower() for k in ["mtd", "proc", "dev", "cfg", "boot", "flash", "open", "read", "write", "part"]):
        print("  ", s)
