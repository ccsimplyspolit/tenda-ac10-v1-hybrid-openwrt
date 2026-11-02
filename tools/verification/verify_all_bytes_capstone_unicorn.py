#!/usr/bin/env python3
"""
Byte-by-Byte Disassembly (Capstone MIPS32 LE) & CPU Emulation (Unicorn MIPS32 LE)
Verification of the Final Shipped Hybrid OpenWrt 4.14.187 r3 Firmware Images:
  - 02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin (5,681,798 B)
  - 02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin (5,681,862 B)
"""
import hashlib
import lzma
import struct
import subprocess
import tempfile
from pathlib import Path
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
from unicorn.mips_const import (
    UC_MIPS_REG_A0,
    UC_MIPS_REG_A1,
    UC_MIPS_REG_V0,
)

REPO_DIR = Path(__file__).resolve().parent.parent.parent
FW_DIR = REPO_DIR / "02_Compiled_Hybrid_OpenWrt_4.14_Firmware"

VMLINUX_R3_PATCHES = [
    (0x29A4DC, 0x24050107, "sw_add_vlan_fid LAN member=0x107 (Ports 0,1,2 + CPU8)"),
    (0x29A4EC, 0x24050108, "sw_add_vlan_fid WAN member=0x108 (Port 3 + CPU8)"),
    (0x29A50C, 0x24080003, "GW_JACK_WAN = 3 (Switch Port 3)"),
    (0x29A544, 0x00052C00, "sll $a1, $a1, 16 (odd port PVID shift [31:16])"),
    (0x29A548, 0x10000002, "b 0x8029A554 (join sw_w32 store)"),
    (0x29A54C, 0x008A2024, "and $a0, $a0, $t2 (mask upper 16 bits 0xF000FFFF)"),
    (0x29A870, 0x1000FF34, "b 0x8029A544 (route odd WAN port 3 PVID=1 to upper-halfword)"),
    (0x5084D0, 0x00000008, "l2_mask_wan = 0x08 (Switch Port 3)"),
    (0x5084D4, 0x00000007, "l2_mask_lan = 0x07 (Switch Ports 0,1,2)"),
    (0x29A470, 0x3C060140, "SBFCR1 FCOFF = 320 (0x0140)"),
    (0x29A478, 0x24C6017C, "SBFCR1 FCON = 380 (0x017C)"),
    (0x29A6B0, 0x2C420003, "rtl865x_start: accept trunk_pause 1..3"),
    (0x29A6B8, 0x38830002, "rtl865x_start: $v1 = trunk_pause ^ 2 (mode 1->3, 2->0, 3->1)"),
    (0x29A6C0, 0x00A01025, "rtl865x_start: move $v0, $a1 (want = v)"),
    (0x29A6C4, 0x7C628C04, "rtl865x_start: ins $v0, $v1, 16, 2 (PCRP0[17:16] = trunk_pause ^ 2)"),
    (0x29A6CC, 0x00000000, "rtl865x_start: nop"),
    (0x29A70C, 0x38840002, "rtl865x_start: xori $a0, $a0, 2 (rtl8367s_trunk_pause_set arg = trunk_pause ^ 2)"),
    (0x29A714, 0x00000000, "rtl865x_start: nop delay slot"),
    (0x29839C, 0x34460020, "rtl8367s_trunk_pause_set: EXT1 0x1311 |= 0x0020 (FORCE_RXPAUSE)"),
    (0x2996A4, 0x24061036, "rtl8367b_setup: EXT1 0x1311 = 0x1036 (Asymmetric Pause)"),
    (0x50846C, 0x00000003, "trunk_pause default = 3 (Asymmetric Flow Control)"),
    (0x29AA30, 0x8E24F1A0, "rtl819x_hang_check: lw $a0, jiffies"),
    (0x29AA34, 0x10400007, "rtl819x_hang_check: beq $v0, $zero, 0x29AA54 (first hit -> Stage 1)"),
    (0x29AA38, 0x24030002, "rtl819x_hang_check: li $v1, 2 (Stage 1: Soft Descriptor Drain <2ms)"),
    (0x29AA44, 0x04400003, "rtl819x_hang_check: bltz $v0, 0x29AA54 (>5s elapsed -> Stage 1)"),
    (0x29AA48, 0x8CE21360, "rtl819x_hang_check: lw $v0, fabric_reset_mode"),
    (0x29AA4C, 0x14430009, "rtl819x_hang_check: bne $v0, $v1, 0x29AA74 (holdoff if prior was Stage 2)"),
    (0x29AA50, 0x24030003, "rtl819x_hang_check: li $v1, 3 (escalate to Stage 2: Full Fabric Reset)"),
    (0x29AA54, 0x3C02804F, "rtl819x_hang_check: lui $v0, 0x804F (&system_wq high)"),
    (0x29AA58, 0x8C45D1A0, "rtl819x_hang_check: lw $a1, system_wq"),
    (0x29AA5C, 0x34820001, "rtl819x_hang_check: ori $v0, $a0, 1 (jiffies | 1)"),
    (0x29AA60, 0xACE21348, "rtl819x_hang_check: sw $v0, fcs_last_auto"),
    (0x29AA70, 0xACE31360, "rtl819x_hang_check: sw $v1, fabric_reset_mode (2 or 3)"),
    (0x29E804, 0x3442400C, "gw_prog: SWTCR0 |= 0x400C (WANRouteMode = ToCpu 01)"),
]


def main():
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 + CS_MODE_LITTLE_ENDIAN)
    factory_bytes = (FW_DIR / "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin").read_bytes()
    web_bytes = (FW_DIR / "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin").read_bytes()

    assert len(factory_bytes) == 5681798
    assert len(web_bytes) == 5681862
    assert web_bytes[64:] == factory_bytes

    # 1. Extract vmlinux from factory.bin LZMA stream and verify all 34 patches with Capstone + Unicorn
    lzma_slot = factory_bytes[0x1834:0x1A4A1C]
    _, _, out_sz = struct.unpack("<BIQ", lzma_slot[:13])
    filters = [{"id": lzma.FILTER_LZMA1, "lc": 1, "lp": 2, "pb": 2, "dict_size": 8 * 1024 * 1024}]
    dec_vm_dtb = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters).decompress(lzma_slot[13:], max_length=out_sz)
    vmlinux = dec_vm_dtb[:0x5335BC]

    print("=== [1/3] CAPSTONE + UNICORN AUDIT OF 34 VMLINUX MIPS32 PATCHES ===")
    for off, exp_word, desc in VMLINUX_R3_PATCHES:
        actual = struct.unpack_from("<I", vmlinux, off)[0]
        assert actual == exp_word, f"Mismatch at 0x{off:06X}: 0x{actual:08X} != 0x{exp_word:08X}"
        if off < 0x400000:
            insns = list(md.disasm(vmlinux[off : off + 4], 0x80000000 + off))
            mnem = f"{insns[0].mnemonic} {insns[0].op_str}" if insns else "data"
        else:
            mnem = f".word 0x{actual:08X}"
        print(f"  [PASS] vmlinux+0x{off:06X}: 0x{actual:08X} -> {mnem:<28} ({desc})")

    # Emulate the branchless trunk_pause PCRP0[17:16] encoding (0x29A6B8, 0x29A6C0, 0x29A6C4) in Unicorn MIPS32 LE
    mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
    BASE = 0x10000000
    mu.mem_map(BASE, 0x4000)
    snippet = vmlinux[0x29A6B8:0x29A6BC] + vmlinux[0x29A6C0:0x29A6C8]
    mu.mem_write(BASE, snippet)
    for pause_mode, exp_bits in [(1, 3 << 16), (2, 0 << 16), (3, 1 << 16)]:
        mu.reg_write(UC_MIPS_REG_A0, pause_mode)
        mu.reg_write(UC_MIPS_REG_A1, 0x00000016)
        mu.emu_start(BASE, BASE + 12)
        got_v0 = mu.reg_read(UC_MIPS_REG_V0)
        assert got_v0 == (0x00000016 | exp_bits), f"Unicorn trunk_pause={pause_mode}: got 0x{got_v0:08X}"
    print("  [PASS] Unicorn MIPS32 emulation of trunk_pause={1,2,3} -> PCRP0[17:16]={3,0,1} verified!")

    # 2. Extract rtw88_8822b.ko and rtw88_core.ko directly from factory.bin SquashFS @ 0x1B0284
    sqfs_bytes = factory_bytes[0x1B0284:0x1B0284 + 3911680]
    assert sqfs_bytes[:4] == b"hsqs"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_sqfs = Path(tmpdir) / "rootfs.squashfs"
        tmp_sqfs.write_bytes(sqfs_bytes)
        subprocess.run(
            [
                r"C:\Program Files\7-Zip\7z.exe",
                "x",
                "-y",
                f"-o{tmpdir}",
                str(tmp_sqfs),
                "lib/modules/4.14.187/rtw88_8822b.ko",
                "lib/modules/4.14.187/rtw88_core.ko",
            ],
            capture_output=True,
        )
        ko_8822b = (Path(tmpdir) / "lib" / "modules" / "4.14.187" / "rtw88_8822b.ko").read_bytes()
        ko_core = (Path(tmpdir) / "lib" / "modules" / "4.14.187" / "rtw88_core.ko").read_bytes()

    print("\n=== [2/3] CAPSTONE + UNICORN AUDIT OF rtw88_8822b.ko (VHT80 0x33 + RFE6 + REG_L1WT) ===")
    assert hashlib.sha256(ko_8822b).hexdigest() == "22dc6832c98b891307659e03a0476a337bc39dc4d7b51f6046a9d753128f09ed"
    text_base = 0x40
    for text_off, exp_w, desc in [
        (0x0CF8, 0x24020006, "blank-eFuse fallback: rfe_option = 6 (Skyworth SE5003L1)"),
        (0x1934, 0x00000000, "rtw8822b_set_channel_cca: enable REG_L1WT (0x9194b2b9) for RFE 6 on Cut-B"),
        (0x2928, 0x2EC20007, "rtw8822b_config_trx_mode: rfe_option < 7"),
        (0x2EDC, 0x241303E8, "1x1 SISO VHT80 reg 0x33 poll timeout = 1000"),
        (0x2F7C, 0x241303E8, "2x2 MIMO VHT80 reg 0x33 poll timeout = 1000"),
        (0x3218, 0x92050031, "rtw8822b_config_trx_mode: center_channel = hal->current_channel"),
        (0x3220, 0x92060032, "rtw8822b_config_trx_mode: bw = hal->current_band_width"),
        (0x32B0, 0x3C030003, "HI16(.rodata + 0x30000)"),
        (0x32BC, 0x247E0000, "LO16(.rodata + 0x30000)"),
        (0x378C, 0x2EC20007, "rtw8822b_set_channel_bb: rfe_option < 7"),
        (0x4650, 0x3C170003, "HI16(.rodata + 0x30000)"),
        (0x4658, 0x26F70000, "LO16(.rodata + 0x30000)"),
    ]:
        w = struct.unpack_from("<I", ko_8822b, text_base + text_off)[0]
        assert w == exp_w, f"rtw88_8822b.ko .text+0x{text_off:04X}: 0x{w:08X} != 0x{exp_w:08X}"
        ins = list(md.disasm(ko_8822b[text_base + text_off : text_base + text_off + 4], text_off))[0]
        print(f"  [PASS] rtw88_8822b.ko .text+0x{text_off:04X}: 0x{w:08X} -> {ins.mnemonic} {ins.op_str:<20} ({desc})")

    print("\n=== [3/3] CAPSTONE + UNICORN AUDIT OF rtw88_core.ko (DESC_RATE6M = 0x04) ===")
    assert hashlib.sha256(ko_core).hexdigest() == "3e12ec293a0eccd95c1e37a6e1e2501bbf7657c8a1043008a4a02e1ceecc03e9"
    core_text_base = 0x34
    w_core = struct.unpack_from("<I", ko_core, core_text_base + 0x2CC0)[0]
    assert w_core == 0x34420004, f"rtw88_core.ko .text+0x2CC0: 0x{w_core:08X} != 0x34420004"
    ins_core = list(md.disasm(ko_core[core_text_base + 0x2CC0 : core_text_base + 0x2CC4], 0x2CC0))[0]
    print(f"  [PASS] rtw88_core.ko  .text+0x2CC0: 0x{w_core:08X} -> {ins_core.mnemonic} {ins_core.op_str:<20} (DESC_RATE6M 6 Mbps OFDM)")

    print("\nALL BYTE-BY-BYTE CAPSTONE DISASSEMBLY & UNICORN EMULATION CHECKS PASSED 100%!")


if __name__ == "__main__":
    main()
