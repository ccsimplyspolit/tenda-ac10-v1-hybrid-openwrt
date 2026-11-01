import struct

from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

def main():
            data = _load_vmlinux_stock()

    # String at 0x80544060
    s_off = 0x80544060 - 0x80000000
    end = data.find(b"\x00", s_off)
    print("String at 0x80544060:", data[s_off:end].decode("latin1", errors="replace"))

    # Jump table at 0x804af2cc
    jt_off = 0x804af2cc - 0x80000000
    print("Jump table 1 at 0x804af2cc:")
    for i in range(16):
        target = struct.unpack("<I", data[jt_off+4*i:jt_off+4*i+4])[0]
        print(f"  [{i}]: 0x{target:08x}")

    # Jump table at 0x804af310
    jt_off2 = 0x804af310 - 0x80000000
    print("Jump table 2 at 0x804af310:")
    for i in range(16):
        target = struct.unpack("<I", data[jt_off2+4*i:jt_off2+4*i+4])[0]
        print(f"  [{i}]: 0x{target:08x}")

if __name__ == "__main__":
    main()
