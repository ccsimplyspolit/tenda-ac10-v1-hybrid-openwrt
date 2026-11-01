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

def find_strings_in_range(data, start_va, end_va):
    start_off = start_va - 0x80000000
    end_off = end_va - 0x80000000
    for i in range(start_off, end_off, 4):
        w = struct.unpack("<I", data[i:i+4])[0]
        if (w >> 26) == 0x0f: # lui
            imm = w & 0xffff
            w2 = struct.unpack("<I", data[i+4:i+8])[0]
            if (w2 >> 26) == 0x09: # addiu
                simm = struct.unpack("<h", data[i+4:i+6])[0]
                target_addr = (imm << 16) + simm
                if 0x80000000 <= target_addr < 0x80700000:
                    t_off = target_addr - 0x80000000
                    end = data.find(b"\x00", t_off)
                    if end != -1 and 1 < (end - t_off) < 120:
                        s = data[t_off:end].decode("latin1", errors="replace")
                        if s.isprintable() and len(s) > 3:
                            print(f"  0x{0x80000000+i:08x}: {repr(s)}")

def disasm_func(data, start_va, count=40):
    start_off = start_va - 0x80000000
    for i in range(count):
        off = start_off + i*4
        w = struct.unpack("<I", data[off:off+4])[0]
        op = w >> 26
        rs = (w >> 21) & 0x1f
        rt = (w >> 16) & 0x1f
        rd = (w >> 11) & 0x1f
        funct = w & 0x3f
        imm = w & 0xffff
        simm = struct.unpack("<h", data[off:off+2])[0]
        target = (0x80000000 & 0xf0000000) | ((w & 0x03ffffff) << 2)
        print(f"  {start_va+i*4:08x}: ({w:08x}) op={op:02x} rs={rs:2d} rt={rt:2d} rd={rd:2d} imm=0x{imm:04x} (simm={simm:6d}) target=0x{target:08x}")

def main():
    data, sym_list = load_data()
    print("Loaded data & symbols.")

    print("\n--- Disassembly of halmac_parse_efuse_data_88xx (0x803725a0) ---")
    disasm_func(data, 0x803725a0, 45)

if __name__ == "__main__":
    main()
