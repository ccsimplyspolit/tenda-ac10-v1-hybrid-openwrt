import os
import struct

from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock
SYMBOLS_TXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "01_Stock_Firmware_and_Partitions", "kallsyms_stock_31434.txt"))

def load_data():
            data = _load_vmlinux_stock()
    sym_list = []
    with open(SYMBOLS_TXT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=2)
            addr = int(parts[0], 16)
            if addr >= 0x80000000:
                sym_list.append((addr, parts[2]))
    sym_list.sort()
    return data, sym_list

def get_sym(addr, sym_list):
    for a, name in reversed(sym_list):
        if a <= addr:
            return f"{name}+0x{addr-a:x}"
    return "unknown"

def main():
    data, sym_list = load_data()
    # Let's inspect 0x80594c00 to 0x80594c50
    off = 0x80594c00 - 0x80000000
    print("--- Memory at 0x80594c00 - 0x80594c60 ---")
    for i in range(24):
        val = struct.unpack("<I", data[off+4*i:off+4*i+4])[0]
        va = 0x80594c00 + 4*i
        sym = get_sym(va, sym_list)
        s_name = ""
        if 0x80000000 <= val < 0x80700000:
            s_off = val - 0x80000000
            end = data.find(b"\x00", s_off)
            if end != -1 and 1 < (end - s_off) < 50:
                s = data[s_off:end].decode("latin1", errors="replace")
                if s.isprintable(): s_name = f'"{s}"'
        print(f"  0x{va:08x} ({sym:<25}): 0x{val:08x} ({val:10d}) {s_name}")

if __name__ == "__main__":
    main()
