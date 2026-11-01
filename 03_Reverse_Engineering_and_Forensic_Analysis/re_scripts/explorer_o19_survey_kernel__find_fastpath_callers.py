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
    print("Callers of FastPath_Enter (0x80473290):")
    for c in find_jal(data, 0x80473290):
        print(f"  0x{c:08x} in {get_sym(c, sym_list)}")

    print("\nCallers of FastPath_Route (0x8046e7c0):")
    for c in find_jal(data, 0x8046e7c0):
        print(f"  0x{c:08x} in {get_sym(c, sym_list)}")

    print("\nCallers of rtl865x_handle_nat:")
    # Find symbol rtl865x_handle_nat
    nat_addr = None
    for a, name in sym_list:
        if name == "rtl865x_handle_nat":
            nat_addr = a
            break
    if nat_addr:
        print(f"  rtl865x_handle_nat is at 0x{nat_addr:08x}")
        for c in find_jal(data, nat_addr):
            print(f"  0x{c:08x} in {get_sym(c, sym_list)}")

    print("\nCallers of fastpath_xmit_prerouting_hook (0x803a2c78):")
    for c in find_jal(data, 0x803a2c78):
        print(f"  0x{c:08x} in {get_sym(c, sym_list)}")

if __name__ == "__main__":
    main()
