import struct

KERNEL_BIN = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"
SYMBOLS_TXT = r"k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt"

def load_data():
    with open(KERNEL_BIN, "rb") as f:
        data = f.read()
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
