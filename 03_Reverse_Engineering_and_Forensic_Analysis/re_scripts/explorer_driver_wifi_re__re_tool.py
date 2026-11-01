import sys
import os
import capstone

BIN_PATH = r'/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin'
SYM_PATH = r'K:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt'
LOAD_BASE = 0x80000000

# Load symbols
addr2sym = {}
sym2addr = {}
with open(SYM_PATH, 'r') as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) >= 3:
            addr = int(parts[0], 16)
            name = parts[2]
            addr2sym[addr] = name
            sym2addr[name] = addr

# Open binary
f_bin = open(BIN_PATH, 'rb')
bin_size = os.path.getsize(BIN_PATH)

def read_bytes(va, length):
    offset = va - LOAD_BASE
    if offset < 0 or offset + length > bin_size:
        return b''
    f_bin.seek(offset)
    return f_bin.read(length)

def read_u32(va):
    b = read_bytes(va, 4)
    if len(b) < 4:
        return 0
    return int.from_bytes(b, 'little')

def read_str(va, max_len=128):
    offset = va - LOAD_BASE
    if offset < 0 or offset >= bin_size:
        return ""
    f_bin.seek(offset)
    s = b""
    while len(s) < max_len:
        ch = f_bin.read(1)
        if not ch or ch == b'\x00':
            break
        s += ch
    try:
        return s.decode('ascii', errors='replace')
    except:
        return str(s)

md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)

def disasm_func(va, max_instructions=200):
    code = read_bytes(va, max_instructions * 4)
    res = []
    for ins in md.disasm(code, va):
        target_name = ""
        # Check if JAL or direct branch
        if ins.mnemonic in ('jal', 'j', 'bal', 'b'):
            try:
                target_addr = int(ins.op_str, 16)
                if target_addr in addr2sym:
                    target_name = f" <{addr2sym[target_addr]}>"
            except:
                pass
        res.append(f"0x{ins.address:08x}:  {ins.bytes.hex()}   {ins.mnemonic:8s} {ins.op_str:28s}{target_name}")
        # Stop at jr $ra followed by delay slot if not early
        if len(res) > 2 and res[-2].find('jr       $ra') != -1:
            break
    return "\n".join(res)

if __name__ == '__main__':
    # Test printk string from rtl8192cd_init_one
    s1 = read_str(0x8055157c)
    s2 = read_str(0x805515a0)
    s3 = read_str(0x805515cc)
    print("Strings:", repr(s1), repr(s2), repr(s3))
