import os
import glob

ROOT = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\squashfs_root"

print("--- 1. Listing etc_ro/init.d ---")
initd = os.path.join(ROOT, "etc_ro", "init.d")
if os.path.exists(initd):
    for f in sorted(os.listdir(initd)):
        fpath = os.path.join(initd, f)
        print(f"  {f} ({os.path.getsize(fpath)} bytes)")
else:
    print("etc_ro/init.d not found")

print("\n--- 2. Checking /etc/wlan /etc_ro/wlan or similar ---")
for p in glob.glob(os.path.join(ROOT, "**", "*wlan*"), recursive=True):
    print("  ", p.replace(ROOT, ""))

print("\n--- 3. Checking scripts that contain mtd1, wlan, /proc/wlan, or calibration ---")
keywords = [b"mtd1", b"mtdblock1", b"HW_WLAN", b"/proc/wlan0", b"/proc/wlan1", b"iwpriv", b"wlan0", b"wlan1", b"CFG"]
found_files = {}

for dirpath, _, filenames in os.walk(ROOT):
    for fn in filenames:
        fpath = os.path.join(dirpath, fn)
        try:
            with open(fpath, "rb") as fp:
                content = fp.read()
                matches = [kw.decode() for kw in keywords if kw in content]
                if matches:
                    rel_p = os.path.relpath(fpath, ROOT)
                    found_files[rel_p] = matches
        except Exception:
            pass

print(f"Found {len(found_files)} files referencing target keywords:")
for p, matches in sorted(found_files.items()):
    print(f"  {p:<40} : {', '.join(matches)}")
