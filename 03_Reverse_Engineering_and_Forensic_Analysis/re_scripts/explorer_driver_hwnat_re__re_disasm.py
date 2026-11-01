import os
import lzma
import struct
import capstone

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_STOCK_DIR = os.path.join(_REPO_ROOT, "01_Stock_Firmware_and_Partitions")
KERNEL_BIN = os.environ.get("AC10_VMLINUX_BIN", os.path.join(_STOCK_DIR, "vmlinux_3.10.90_raw_0x80000000.bin"))
KERNEL_CR6C = os.path.join(_STOCK_DIR, "kernel_cr6c_0x030000.bin")
SYMBOLS_TXT = os.environ.get("AC10_SYMBOLS_TXT", os.path.join(_STOCK_DIR, "kallsyms_stock_31434.txt"))
BASE_VA = 0x80000000

def load_kernel_bytes():
    if os.path.isfile(KERNEL_BIN):
        with open(KERNEL_BIN, "rb") as f:
            return f.read()
    with open(KERNEL_CR6C, "rb") as f:
        cr6c = f.read()
    assert cr6c[:4] == b"cr6c", "Expected cr6c magic in kernel_cr6c_0x030000.bin"
    return lzma.decompress(cr6c[16:])

def load_environment():
    data = load_kernel_bytes()
    symbols = {}
    sym_list = []
    with open(SYMBOLS_TXT, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=2)
            if len(parts) == 3:
                addr = int(parts[0], 16)
                name = parts[2]
                symbols[addr] = name
                sym_list.append((addr, name))
    sym_list.sort(key=lambda x: x[0])
    return data, symbols, sym_list

def resolve_symbol(addr, sym_list):
    # binary search or scan backwards
    low = 0
    high = len(sym_list) - 1
    best = None
    while low <= high:
        mid = (low + high) // 2
        if sym_list[mid][0] <= addr:
            best = sym_list[mid]
            low = mid + 1
        else:
            high = mid - 1
    if best:
        offset = addr - best[0]
        if offset == 0:
            return best[1]
        elif offset < 0x2000:
            return f"{best[1]}+0x{offset:x}"
    return f"0x{addr:08x}"

def disassemble_range(data, sym_list, start_va, end_va=None, max_instructions=None):
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    start_off = start_va - BASE_VA
    if end_va:
        code = data[start_off:end_va - BASE_VA]
    elif max_instructions:
        code = data[start_off:start_off + max_instructions * 4]
    else:
        code = data[start_off:start_off + 100 * 4]

    disasm_lines = []
    count = 0
    for insn in md.disasm(code, start_va):
        extra = ""
        # if branch or jump
        if insn.mnemonic in ['jal', 'j', 'bal', 'beq', 'bne', 'bgez', 'bgtz', 'blez', 'bltz']:
            # check if target operand is immediate
            for op in insn.operands:
                if op.type == capstone.mips.MIPS_OP_IMM:
                    target = op.imm
                    if target >= BASE_VA:
                        sym = resolve_symbol(target, sym_list)
                        extra = f"  ; target={sym}"
        line = f"0x{insn.address:08x}:  {insn.bytes.hex()}   {insn.mnemonic:<8} {insn.op_str:<25} {extra}"
        disasm_lines.append(line)
        count += 1
        if max_instructions and count >= max_instructions:
            break
    return "\n".join(disasm_lines)

if __name__ == "__main__":
    data, symbols, sym_list = load_environment()
    print(f"Loaded {len(data)} bytes, {len(sym_list)} symbols.")
    # test disasm of rtl_nat_init_hooks
    print("Disassembling rtl_nat_init_hooks (0x8047f57c):")
    print(disassemble_range(data, sym_list, 0x8047f57c, max_instructions=25))
