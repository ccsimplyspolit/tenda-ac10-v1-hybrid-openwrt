from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    kdata = _load_vmlinux_stock()

# In MIPS, pointers in KSEG0 start with 0x80xxxxxx.
# What is the load address of vmlinux_stock.bin?
# Let's find string references to 'rtkxxpart' or 'Bootloader'.
# First let's find the kernel base address.
# Usually 0x80000000 or 0x80001000.
# Let's find pointer to "rtkxxpart" string in binary.
str_offset = kdata.find(b"rtkxxpart\x00")
print(f"'rtkxxpart' string at offset 0x{str_offset:08X}")

# Search for this offset + base address:
for base in [0x80000000, 0x80001000, 0x80002000, 0x80000400]:
    target_addr = base + str_offset
    # search big endian and little endian
    be_bytes = target_addr.to_bytes(4, "big")
    le_bytes = target_addr.to_bytes(4, "little")
    pos_be = kdata.find(be_bytes)
    pos_le = kdata.find(le_bytes)
    if pos_be != -1:
        print(f"Found BE pointer to rtkxxpart (base=0x{base:08X}) at 0x{pos_be:08X}")
    if pos_le != -1:
        print(f"Found LE pointer to rtkxxpart (base=0x{base:08X}) at 0x{pos_le:08X}")

# Also let's search for "Bootloader" pointer
str_boot = kdata.find(b"Bootloader\x00")
print(f"'Bootloader' string at offset 0x{str_boot:08X}")
for base in [0x80000000, 0x80001000, 0x80002000]:
    target_addr = base + str_boot
    pos_le = kdata.find(target_addr.to_bytes(4, "little"))
    if pos_le != -1:
        print(f"Found LE pointer to Bootloader (base=0x{base:08X}) at 0x{pos_le:08X}")
        # inspect surrounding struct mtd_partition
        # struct mtd_partition:
        #   char *name (4 bytes)
        #   uint64_t size (8 bytes)
        #   uint64_t offset (8 bytes)
        #   uint32_t mask_flags (4 bytes)
        #   struct nand_ecclayout *ecclayout (4 bytes)
        struct_chunk = kdata[pos_le-16:pos_le+120]
        print("Partition struct hex dump:")
        for r in range(0, len(struct_chunk), 16):
            row = struct_chunk[r:r+16]
            print(f"  +0x{r:02X}: {' '.join(f'{b:02X}' for b in row)}")
