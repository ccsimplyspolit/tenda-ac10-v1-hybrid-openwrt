import sys
import capstone
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True

def disasm_func_named(name, max_insns=120):
    # find symbol
    addr = None
    for a, n in sym_list:
        if n == name:
            addr = a
            break
    if not addr:
        print(f"[-] Symbol {name} not found!")
        return
    print(f"\n=======================================================")
    print(f"Disassembly of {name} at 0x{addr:08x} (max {max_insns} insns):")
    print(f"=======================================================")
    start_off = addr - 0x80000000
    code = data[start_off:start_off + max_insns * 4]
    count = 0
    for insn in md.disasm(code, addr):
        extra = ""
        # Check target
        for op in insn.operands:
            if op.type == capstone.mips.MIPS_OP_IMM:
                target = op.imm
                if target >= 0x80000000:
                    extra += f" ; {resolve_symbol(target, sym_list)}"
                elif target > 0x1000:
                    extra += f" ; 0x{target:x}"
        # Check lui / lw for constants
        line = f"0x{insn.address:08x}:  {insn.bytes.hex()}   {insn.mnemonic:<8} {insn.op_str:<28} {extra}"
        print(line)
        count += 1
        if count >= max_insns:
            break

# Disassemble rtl_nat_init_hooks and around
disasm_func_named("rtl_nat_init_hooks", 40)
disasm_func_named("rtl865x_handle_nat", 120)
disasm_func_named("FastPath_Enter", 120)
disasm_func_named("FastPath_Route", 100)
