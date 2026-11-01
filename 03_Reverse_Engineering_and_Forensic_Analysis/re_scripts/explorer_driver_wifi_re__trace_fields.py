import sys
import explorer_driver_wifi_re__re_tool as re_tool

offsets = {
    0x2bfc: "priv->xcap",
    0x2c04: "priv->share_xcap",
    0x2c10: "priv->ther",
    0x2c61: "priv->rfe_type",
    0x096a: "priv->pwrlevel5GHT40_1S_A",
    0x0a2e: "priv->pwrlevel5GHT40_1S_B",
}

print("Searching for accesses to priv offsets:")
for va in range(0x80200000, 0x80380000, 4):
    word = re_tool.read_u32(va)
    imm = word & 0xffff
    if imm in offsets:
        # Find which function this address belongs to
        caller = "unknown"
        for s_addr, s_name in sorted(re_tool.addr2sym.items()):
            if s_addr <= va:
                caller = s_name
            else:
                break
        desc = offsets[imm]
        # Disassemble instruction
        code = re_tool.read_bytes(va, 4)
        for ins in re_tool.md.disasm(code, va):
            print(f"0x{va:08x} in {caller}: {ins.mnemonic:8s} {ins.op_str:24s} [{desc}]")
