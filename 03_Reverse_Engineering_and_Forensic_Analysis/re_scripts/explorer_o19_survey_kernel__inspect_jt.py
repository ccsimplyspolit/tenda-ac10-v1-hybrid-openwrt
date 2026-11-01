import struct

KERNEL_BIN = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"

def main():
    with open(KERNEL_BIN, "rb") as f:
        data = f.read()

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
