import struct

KERNEL_BIN = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"
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

def disasm_func(data, sym_list, start_va, count=50):
    start_off = start_va - 0x80000000
    for i in range(count):
        off = start_off + i*4
        w = struct.unpack("<I", data[off:off+4])[0]
        op = w >> 26
        rs = (w >> 21) & 0x1f
        rt = (w >> 16) & 0x1f
        rd = (w >> 11) & 0x1f
        simm = struct.unpack("<h", data[off:off+2])[0]
        target = (0x80000000 & 0xf0000000) | ((w & 0x03ffffff) << 2)
        extra = ""
        if op == 0x03: # jal
            extra = f" -> {get_sym(target, sym_list)}"
        print(f"  {start_va+i*4:08x}: ({w:08x}) op=0x{op:02x} rs={rs:2d} rt={rt:2d} rd={rd:2d} simm={simm:6d}{extra}")

def main():
    data, sym_list = load_data()
    print("\n--- Disassembly of rtl_get_8367r_port_link_status (0x801bc1a4) ---")
    disasm_func(data, sym_list, 0x801bc1a4, 40)

    print("\n--- Disassembly of display_8367r_port_stat (0x801c27d4) ---")
    disasm_func(data, sym_list, 0x801c27d4, 45)

if __name__ == "__main__":
    main()
