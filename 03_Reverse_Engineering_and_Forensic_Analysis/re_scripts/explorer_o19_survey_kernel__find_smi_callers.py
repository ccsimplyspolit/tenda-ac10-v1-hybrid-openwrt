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

def find_jal(data, target_va):
    target_instr = 0x0c000000 | ((target_va & 0x0fffffff) >> 2)
    b = struct.pack("<I", target_instr)
    pos = 0
    results = []
    while True:
        idx = data.find(b, pos)
        if idx == -1: break
        results.append(0x80000000 + idx)
        pos = idx + 1
    return results

def main():
    data, sym_list = load_data()
    print("Callers of smi_init (0x801d7bbc):")
    callers = find_jal(data, 0x801d7bbc)
    for c in callers:
        print(f"  0x{c:08x} in {get_sym(c, sym_list)}")
        # print 10 instructions before the call
        c_off = c - 0x80000000
        for off in range(c_off - 40, c_off + 8, 4):
            w = struct.unpack("<I", data[off:off+4])[0]
            op = w >> 26
            rs = (w >> 21) & 0x1f
            rt = (w >> 16) & 0x1f
            rd = (w >> 11) & 0x1f
            simm = struct.unpack("<h", data[off:off+2])[0]
            print(f"    0x{0x80000000+off:08x}: ({w:08x}) op=0x{op:02x} rs={rs:2d} rt={rt:2d} rd={rd:2d} simm={simm:6d}")

if __name__ == "__main__":
    main()
