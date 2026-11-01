from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    kdata = _load_vmlinux_stock()

import struct

print("Surrounding strings around 0x00538740:")
chunk = kdata[0x00538730:0x00538790]
for r in range(0, len(chunk), 16):
    row = chunk[r:r+16]
    print(f"  +0x{r:02X}: {' '.join(f'{b:02X}' for b in row)} | {''.join(chr(b) if 32 <= b <= 126 else '.' for b in row)}")

# Search for code references to 0x80538754 (where "Tenda" is)
target_addr = 0x80538754
# lui $reg, 0x8054; addiu $reg, -0x78AC or lui 0x8053; addiu $reg, 0x8754
# Let's search all lui + addiu/ori
for i in range(0, len(kdata)-8, 4):
    w1, = struct.unpack("<I", kdata[i:i+4])
    op1 = (w1 >> 26) & 0x3F
    if op1 == 0x0F: # LUI
        rt1 = (w1 >> 16) & 0x1F
        imm1 = w1 & 0xFFFF
        if imm1 in (0x8053, 0x8054):
            # check next 4 instructions for use of rt1
            for j in range(1, 5):
                w2, = struct.unpack("<I", kdata[i+j*4:i+(j+1)*4])
                op2 = (w2 >> 26) & 0x3F
                rs2 = (w2 >> 21) & 0x1F
                imm2 = w2 & 0xFFFF
                if imm2 >= 0x8000: imm2 -= 0x10000
                if rs2 == rt1 and op2 in (0x09, 0x0D): # addiu or ori
                    addr = (imm1 << 16) + imm2
                    if 0x80538740 <= addr <= 0x80538760:
                        print(f"Code ref to 0x{addr:08X} at 0x{0x80000000+i:08X} (offset 0x{i:08X})!")
