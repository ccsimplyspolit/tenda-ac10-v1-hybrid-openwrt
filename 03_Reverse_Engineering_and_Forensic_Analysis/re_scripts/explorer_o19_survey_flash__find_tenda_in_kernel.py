FLASH_PATH = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"

with open(FLASH_PATH, "rb") as f:
    kdata = f.read()

# Search for "Tenda" in kernel
idx = 0
matches = []
while True:
    pos = kdata.find(b"Tenda", idx)
    if pos == -1: break
    matches.append(pos)
    idx = pos + 5

print(f"Found {len(matches)} occurrences of 'Tenda' in vmlinux_stock.bin:")
for m in matches:
    chunk = kdata[max(0, m-16):min(len(kdata), m+48)]
    print(f"  0x{m:08X} (VA: 0x{0x80000000+m:08X}): {chunk}")
