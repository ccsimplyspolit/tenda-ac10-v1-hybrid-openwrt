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
    # struct platform_driver rtl819x_8367r_reset_pin_driver at 0x805a5664
    off1 = 0x805a5664 - 0x80000000
    print("rtl819x_8367r_reset_pin_driver (0x805a5664):")
    for i in range(12):
        val = struct.unpack("<I", data[off1+4*i:off1+4*i+4])[0]
        name = ""
        if 0x80000000 <= val < 0x80700000:
            s_off = val - 0x80000000
            end = data.find(b"\x00", s_off)
            if end != -1 and 1 < (end - s_off) < 50:
                s = data[s_off:end].decode("latin1", errors="replace")
                if s.isprintable(): name = f'"{s}"'
        print(f"  +0x{4*i:02x}: 0x{val:08x} -> {get_sym(val, sym_list)} {name}")

    # struct platform_driver rtl819x_8367r_i2c_pin_driver at 0x805a56b8
    off2 = 0x805a56b8 - 0x80000000
    print("\nrtl819x_8367r_i2c_pin_driver (0x805a56b8):")
    for i in range(12):
        val = struct.unpack("<I", data[off2+4*i:off2+4*i+4])[0]
        name = ""
        if 0x80000000 <= val < 0x80700000:
            s_off = val - 0x80000000
            end = data.find(b"\x00", s_off)
            if end != -1 and 1 < (end - s_off) < 50:
                s = data[s_off:end].decode("latin1", errors="replace")
                if s.isprintable(): name = f'"{s}"'
        print(f"  +0x{4*i:02x}: 0x{val:08x} -> {get_sym(val, sym_list)} {name}")

if __name__ == "__main__":
    main()
