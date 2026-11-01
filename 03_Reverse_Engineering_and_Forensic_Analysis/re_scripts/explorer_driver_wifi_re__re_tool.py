import io
import os
import sys
import lzma
import capstone

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_STOCK_DIR = os.path.join(_REPO_ROOT, "01_Stock_Firmware_and_Partitions")
BIN_PATH = os.environ.get("AC10_VMLINUX_BIN", os.path.join(_STOCK_DIR, "vmlinux_3.10.90_raw_0x80000000.bin"))
CR6C_PATH = os.path.join(_STOCK_DIR, "kernel_cr6c_0x030000.bin")
SYM_PATH = os.environ.get("AC10_SYMBOLS_TXT", os.path.join(_STOCK_DIR, "kallsyms_stock_31434.txt"))
LOAD_BASE = 0x80000000

addr2sym = {}
sym2addr = {}
with open(SYM_PATH, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) >= 3:
            addr = int(parts[0], 16)
            name = parts[2]
            addr2sym[addr] = name
            sym2addr[name] = addr

if os.path.isfile(BIN_PATH):
    _raw_bin = open(BIN_PATH, "rb").read()
else:
    _cr6c = open(CR6C_PATH, "rb").read()
    _raw_bin = lzma.decompress(_cr6c[16:])
f_bin = io.BytesIO(_raw_bin)
bin_size = len(_raw_bin)

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
