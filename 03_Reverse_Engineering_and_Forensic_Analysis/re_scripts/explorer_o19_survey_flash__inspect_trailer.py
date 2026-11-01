from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    data = _load_vmlinux_stock()

print("--- Inspecting Flash Trailer 0x700000 to 0x800000 ---")
for off in range(0x760000, 0x800000, 0x10000):
    chunk = data[off:off+0x10000]
    non_ff = sum(1 for b in chunk if b != 0xff)
    non_00 = sum(1 for b in chunk if b != 0x00)
    print(f"Block 0x{off:06X} - 0x{off+0x10000:06X} (64KB): non-FF={non_ff}, non-00={non_00}, first 16 bytes: {chunk[:16].hex()}")
    # Check for strings
    cur = []
    found_str = []
    for i, b in enumerate(chunk):
        if 32 <= b <= 126:
            cur.append(chr(b))
        else:
            if len(cur) >= 4:
                found_str.append((off + i - len(cur), "".join(cur)))
            cur = []
    if found_str:
        print(f"  Found {len(found_str)} strings. Sample:")
        for soff, s in found_str[:10]:
            print(f"    0x{soff:06X}: {s}")

# Let's check booter environment & strings in 0x00000 to 0x20000
print("\n--- Inspecting Booter (0x00000 to 0x20000) ---")
booter = data[0:0x20000]
# Search for environment variables (key=value\0)
cur = []
env_vars = []
for i, b in enumerate(booter):
    if 32 <= b <= 126:
        cur.append(chr(b))
    elif b == 0:
        if len(cur) >= 3 and "=" in "".join(cur):
            env_vars.append((i - len(cur), "".join(cur)))
        cur = []
    else:
        cur = []

print(f"Environment variables found in booter ({len(env_vars)}):")
for off, ev in env_vars:
    print(f"  0x{off:05X}: {ev}")

# Search for network configuration in booter (IP addresses, TFTP, MAC)
import re
ip_matches = re.findall(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b", booter)
print(f"\nIP addresses found in booter: {set(ip_matches)}")
