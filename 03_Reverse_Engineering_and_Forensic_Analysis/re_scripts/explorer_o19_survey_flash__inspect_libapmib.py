ROOT = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\squashfs_root"
fpath = ROOT + r"\lib\libapmib.so"

with open(fpath, "rb") as f:
    data = f.read()

cur = []
strings = []
for i, b in enumerate(data):
    if 32 <= b <= 126:
        cur.append(chr(b))
    else:
        if len(cur) >= 4:
            strings.append("".join(cur))
        cur = []

print("Key strings in libapmib.so:")
for s in strings:
    if any(k in s for k in ["CFG", "HW_", "apmib", "flash", "mib", "wlan", "read", "init"]):
        print("  ", s)
