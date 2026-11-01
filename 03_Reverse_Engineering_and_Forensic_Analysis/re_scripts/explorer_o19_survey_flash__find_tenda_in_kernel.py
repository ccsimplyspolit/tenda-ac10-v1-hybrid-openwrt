from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    kdata = _load_vmlinux_stock()

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
