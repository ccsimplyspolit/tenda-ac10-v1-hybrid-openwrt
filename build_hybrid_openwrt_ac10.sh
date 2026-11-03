#!/usr/bin/env bash
# ==============================================================================
# Tenda AC10 V1.0 — Automated Hybrid OpenWrt 4.14 Builder ("Best of Both Worlds")
# Architecture:
#   1. Hardware NAT (~895–940 Mbps rtl819x_hwnat.c, host-byte-order + PORT0_ROUTER_MODE)
#      from ADCDS/openwrt-dlink-dir842-r1 (Linux 4.14.187 / OpenWrt 19.07) +
#      9 MIPS32 LE Tenda AC10 V1.0 Switch/VLAN/ASIC Port-Map patches
#      (WAN = Switch Port 3 / mask 0x08, LAN1..LAN3 = Switch Ports 2,1,0 / mask 0x07).
#   2. 5 GHz PCIe RTL8822BE: mac80211 rtw88 + hostapd, ELF-patched for true
#      Skyworth SE5003L1 RFE Type 6 (efuse.rfe_option=6, type5 BB PG & TX power
#      limit tables, cca_efem_ccut + RTW_CCA_SRC_EFEM=1 enabling C-cut BB reg
#      0x83C=0x9194B2B9, rtw8822b_config_rfe_efem, and .rodata RFE 6 eLNA AGC/RF
#      curves) + dynamic per-unit HW_WLAN0_11N_XCAP & HW_WLAN0_WLAN_ADDR injection.
#   3. 2.4 GHz SoC RTL8197FS: vendor rtl8192cd (Skyworth SKY85303-11 RFE Type 5,
#      in-kernel WPA2-PSK) + dynamic mtd1 RF calibration + vladisslav0 UDP/uTP
#      torrent stability fixes (manual_edca=1, disable_txsc=1, coexist=0 on noscan=1).
#   4. Verified Bootloader & Stock Web UI Packaging:
#      - factory.bin & sysupgrade.bin: single-segment cs6c @ 0x00030000
#      - webupgrade.bin: 64-byte Tenda U-Boot trx2 header (IH_MAGIC 0x27051956,
#        ih_os=2, ih_ver=0x00030028) + cs6c payload
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-$SCRIPT_DIR/build_tree}"
JOBS="${JOBS:-$(nproc)}"

echo "[1/7] Cloning base tree ADCDS/openwrt-dlink-dir842-r1 (Linux 4.14)..."
mkdir -p "$WORK_DIR"
if [ ! -d "$WORK_DIR/openwrt-hybrid" ]; then
    git clone --depth=1 https://github.com/ADCDS/openwrt-dlink-dir842-r1.git "$WORK_DIR/openwrt-hybrid"
fi
cd "$WORK_DIR/openwrt-hybrid"

# Fast deterministic Hybrid OpenWrt 4.14 assembly mode (default unless FULL_SOURCE_BUILD=1):
if [ "${FULL_SOURCE_BUILD:-0}" != "1" ]; then
    echo "[FAST-HYBRID] Building Tenda AC10 V1.0 Hybrid OpenWrt 4.14 images from verified Linux 4.14.187 kernel + DTS + SquashFS..."
    OUT_DIR="$WORK_DIR/openwrt-hybrid/bin/targets/realtek/rtl8197f"
    STAGE_DIR="$WORK_DIR/ac10_stage"
    rm -rf "$STAGE_DIR"
    mkdir -p "$OUT_DIR" "$STAGE_DIR/include/dt-bindings/gpio" "$STAGE_DIR/include/dt-bindings/input"

    # 1. Preprocess & compile tenda-ac10-v1.dts -> tenda-ac10-v1.dtb
    cat > "$STAGE_DIR/include/dt-bindings/gpio/gpio.h" << 'EOF'
#define GPIO_ACTIVE_HIGH 0
#define GPIO_ACTIVE_LOW 1
EOF
    cat > "$STAGE_DIR/include/dt-bindings/input/input.h" << 'EOF'
#define KEY_RESTART 0x198
#define KEY_WPS_BUTTON 0x211
#define KEY_RFKILL 0xf7
EOF
    cp "$SCRIPT_DIR/tenda-ac10-v1.dts" "$STAGE_DIR/tenda-ac10-v1.dts"
    sed -i 's|/include/ "rtl8197f.dtsi"||g' "$STAGE_DIR/tenda-ac10-v1.dts"
    gcc -E -nostdinc -I"$STAGE_DIR/include" -undef -D__DTS__ -x assembler-with-cpp \
        "$STAGE_DIR/tenda-ac10-v1.dts" -o "$STAGE_DIR/tenda-ac10-v1.preprocessed.dts"
    dtc -I dts -O dtb -o "$STAGE_DIR/tenda-ac10-v1.dtb" "$STAGE_DIR/tenda-ac10-v1.preprocessed.dts"
    cp "$STAGE_DIR/tenda-ac10-v1.dtb" "$OUT_DIR/tenda-ac10-v1.dtb"

    # 2. Download verified ADCDS Linux 4.14.187 base image
    BASE_BIN="$STAGE_DIR/dir842_v141_factory.bin"
    wget -q -O "$BASE_BIN" \
        "https://github.com/ADCDS/openwrt-dlink-dir842-r1/releases/download/v1.4.1/openwrt-realtek-rtl8197f-GWR1200AC-V1-squashfs-factory.bin"

    # 3. Extract SquashFS rootfs & patch vmlinux + loader stub
    python3 - "$BASE_BIN" "$STAGE_DIR" << 'PYEOF'
import lzma, os, struct, sys

base_bin, stage_dir = sys.argv[1], sys.argv[2]
raw = open(base_bin, "rb").read()
assert raw[:4] == b"cr6b", f"Unexpected base magic: {raw[:4]!r}"

# Extract & patch lzma-loader stub (0x0010..0x1834): console=ttyS0,38400 -> console=ttyS0,115200
# and shift _lzma_data_end/.data/.bss/_stack by +0x4000 (consuming 16 KB of 62.9 KB zero padding before 0x1B0000 hsqsFAKE)
stub = bytearray(raw[0x0010:0x1834])
assert stub[0x1660:0x1674] == b"console=ttyS0,38400\x00"
stub[0x1660:0x1675] = b"console=ttyS0,115200\x00"
for off in [
    0x005C, 0x008C, 0x00C4, 0x00CC, 0x00EC,
    0x0114, 0x011C, 0x0124, 0x0134,
    0x01B8, 0x01D0, 0x01D4, 0x01E0,
    0x0238, 0x0258, 0x02A0, 0x02A4, 0x02A8, 0x02AC, 0x02B0, 0x02B8,
    0x033C, 0x0348, 0x0350, 0x0360, 0x036C,
]:
    w, = struct.unpack_from("<I", stub, off)
    imm = w & 0xFFFF
    assert imm in (0x0A0C, 0x0A20, 0x0A40, 0x0A44, 0x0A48, 0x0A4C, 0x0A50, 0x0A60, 0x2A60)
    struct.pack_into("<I", stub, off, (w & 0xFFFF0000) | ((imm + 0x4000) & 0xFFFF))
open(os.path.join(stage_dir, "loader_stub.bin"), "wb").write(stub)

# Save loader .data + fake-rootfs trailer shifted by +0x4000 so hsqsFAKE stays at 0x1B0000 and SquashFS at 0x1B0284
orig_tail = raw[0x1A0A1C:0x1B0284]
assert all(b == 0 for b in orig_tail[0x34:0xF5E4]) and orig_tail[0xF5E4:0xF5EC] == b"hsqsFAKE"
new_tail = orig_tail[:0x34] + b"\x00" * (0xF5E4 - 0x4000 - 0x34) + orig_tail[0xF5E4:]
open(os.path.join(stage_dir, "loader_tail_and_fakeroot.bin"), "wb").write(new_tail)

# Extract SquashFS 4.0 XZ rootfs (0x1B0284..end-2)
sqfs = raw[0x1B0284:-2]
assert sqfs[:4] == b"hsqs", "Missing hsqs magic at 0x1B0284"
open(os.path.join(stage_dir, "base_rootfs.squashfs"), "wb").write(sqfs)

# Decompress Linux 4.14.187 vmlinux + DTB (0x1834..0x1A0A1C)
vm_dtb = bytearray(lzma.decompress(raw[0x1834:0x1A0A1C]))
dtb_off = 0x5335BC
assert vm_dtb[dtb_off:dtb_off+4] == b"\xd0\x0d\xfe\xed", "DTB magic not at 0x5335BC"
vmlinux = vm_dtb[:dtb_off]

# Apply 34 verified MIPS32 LE binary patches for Tenda AC10 V1.0 Switch/VLAN/ASIC Port Map & Datapath:
# Physical WAN = Switch Port 3 (mask 0x08), Physical LAN1..LAN3 = Switch Ports 2,1,0 (mask 0x07)
patches = [
    (0x29A4DC, 0x2405010F, 0x24050107, "sw_add_vlan_fid LAN member=0x107 (Ports 0,1,2 + CPU8)"),
    (0x29A4EC, 0x24050110, 0x24050108, "sw_add_vlan_fid WAN member=0x108 (Port 3 + CPU8)"),
    (0x29A50C, 0x24080004, 0x24080003, "GW_JACK_WAN = 3 (Switch Port 3)"),
    (0x29A544, 0x008A2024, 0x00052C00, "sll $a1, $a1, 16 (odd port PVID shift [31:16])"),
    (0x29A548, 0x10000003, 0x10000002, "b 0x8029A554 (join sw_w32 store)"),
    (0x29A54C, 0x008B2025, 0x008A2024, "and $a0, $a0, $t2 (mask upper 16 bits 0xF000FFFF)"),
    (0x29A870, 0x1000FF37, 0x1000FF34, "b 0x8029A544 (route odd WAN port 3 PVID=1 to upper-halfword)"),
    (0x5084D0, 0x00000010, 0x00000008, "l2_mask_wan = 0x08 (Switch Port 3)"),
    (0x5084D4, 0x00000004, 0x00000007, "l2_mask_lan = 0x07 (Switch Ports 0,1,2)"),
    # Milestone 3 Switch & Routing Datapath: SBFCR1 buffer tuning, asymmetric flow control,
    # 2-stage FABRIC WEDGE recovery ladder, and WANRouteMode=ToCpu (SWTCR0 |= 0x400C)
    (0x29A470, 0x3C060190, 0x3C060140, "SBFCR1 FCOFF = 320 (0x0140)"),
    (0x29A478, 0x24C601CC, 0x24C6017C, "SBFCR1 FCON = 380 (0x017C)"),
    (0x29A6B0, 0x2C420002, 0x2C420003, "rtl865x_start: accept trunk_pause 1..3"),
    (0x29A6B8, 0x24020001, 0x38830002, "rtl865x_start: $v1 = trunk_pause ^ 2 (mode 1->3, 2->0, 3->1)"),
    (0x29A6C0, 0x14820003, 0x00A01025, "rtl865x_start: move $v0, $a1 (want = v)"),
    (0x29A6C4, 0x3C020003, 0x7C628C04, "rtl865x_start: ins $v0, $v1, 16, 2 (PCRP0[17:16] = trunk_pause ^ 2)"),
    (0x29A6CC, 0x00A21025, 0x00000000, "rtl865x_start: nop"),
    (0x29A70C, 0x38840001, 0x38840002, "rtl865x_start: xori $a0, $a0, 2 (rtl8367s_trunk_pause_set arg = trunk_pause ^ 2)"),
    (0x29A714, 0x2C840001, 0x00000000, "rtl865x_start: nop delay slot"),
    (0x29839C, 0x34460060, 0x34460020, "rtl8367s_trunk_pause_set: EXT1 0x1311 |= 0x0020 (FORCE_RXPAUSE)"),
    (0x2996A4, 0x24061076, 0x24061036, "rtl8367b_setup: EXT1 0x1311 = 0x1036 (Asymmetric Pause)"),
    (0x50846C, 0x00000002, 0x00000003, "trunk_pause default = 3 (Asymmetric Flow Control)"),
    (0x29AA30, 0x10400006, 0x8E24F1A0, "rtl819x_hang_check: lw $a0, jiffies"),
    (0x29AA34, 0x3C118050, 0x10400007, "rtl819x_hang_check: beq $v0, $zero, 0x29AA54 (first hit -> Stage 1)"),
    (0x29AA38, 0x8E24F1A0, 0x24030002, "rtl819x_hang_check: li $v1, 2 (Stage 1: Soft Descriptor Drain <2ms)"),
    (0x29AA44, 0x0441000B, 0x04400003, "rtl819x_hang_check: bltz $v0, 0x29AA54 (>5s elapsed -> Stage 1)"),
    (0x29AA48, 0x00000000, 0x8CE21360, "rtl819x_hang_check: lw $v0, fabric_reset_mode"),
    (0x29AA4C, 0x8E22F1A0, 0x14430009, "rtl819x_hang_check: bne $v0, $v1, 0x29AA74 (holdoff if prior was Stage 2)"),
    (0x29AA50, 0x3C04804F, 0x24030003, "rtl819x_hang_check: li $v1, 3 (escalate to Stage 2: Full Fabric Reset)"),
    (0x29AA54, 0x34420001, 0x3C02804F, "rtl819x_hang_check: lui $v0, 0x804F (&system_wq high)"),
    (0x29AA58, 0x8C85D1A0, 0x8C45D1A0, "rtl819x_hang_check: lw $a1, system_wq"),
    (0x29AA5C, 0xACE21348, 0x34820001, "rtl819x_hang_check: ori $v0, $a0, 1 (jiffies | 1)"),
    (0x29AA60, 0x3C028067, 0xACE21348, "rtl819x_hang_check: sw $v0, fcs_last_auto"),
    (0x29AA70, 0xAC431360, 0xACE31360, "rtl819x_hang_check: sw $v1, fabric_reset_mode (2 or 3)"),
    (0x29E804, 0x34424004, 0x3442400C, "gw_prog: SWTCR0 |= 0x400C (WANRouteMode = ToCpu 01)"),
]
for off, exp_old, new_val, desc in patches:
    cur, = struct.unpack_from("<I", vmlinux, off)
    if cur == new_val:
        print(f"  [OK] Already patched 0x80{off:06X}: 0x{new_val:08X} ({desc})")
        continue
    assert cur == exp_old, f"Patch mismatch at 0x80{off:06X}: got 0x{cur:08X}, expected 0x{exp_old:08X}"
    struct.pack_into("<I", vmlinux, off, new_val)
    print(f"  [PATCH] 0x80{off:06X}: 0x{exp_old:08X} -> 0x{new_val:08X} ({desc})")

dtb_bytes = open(os.path.join(stage_dir, "tenda-ac10-v1.dtb"), "rb").read()
combined = bytes(vmlinux) + dtb_bytes

# Compress with OpenWrt MIPS32 LZMA1 (lc=1, lp=2, pb=2 -> props=0x6D, dict_size=8MB) + 8-byte LE uncompressed size header
filters = [{"id": lzma.FILTER_LZMA1, "lc": 1, "lp": 2, "pb": 2, "dict_size": 8 * 1024 * 1024, "mode": lzma.MODE_NORMAL, "nice_len": 128, "mf": lzma.MF_BT4}]
comp_stream = lzma.compress(combined, format=lzma.FORMAT_RAW, filters=filters)
assert lzma.decompress(comp_stream, format=lzma.FORMAT_RAW, filters=filters) == combined, "LZMA round-trip verification failed!"
lzma_hdr = struct.pack("<BIQ", 0x6D, 8 * 1024 * 1024, len(combined))
lzma_blob = lzma_hdr + comp_stream
max_lzma_len = 0x19F1E8 + 0x4000
assert len(lzma_blob) <= max_lzma_len, f"LZMA kernel {len(lzma_blob)} > max {max_lzma_len}"
lzma_padded = lzma_blob + b"\x00" * (max_lzma_len - len(lzma_blob))
open(os.path.join(stage_dir, "kernel_lzma_padded.bin"), "wb").write(lzma_padded)
print(f"  [OK] Patched vmlinux + tenda-ac10-v1.dtb compressed: {len(lzma_blob):,} B (slot {max_lzma_len:,} B)")
PYEOF

    # 4. Customize SquashFS rootfs for Tenda AC10 V1.0
    sudo unsquashfs -d "$STAGE_DIR/sqfs_root" "$STAGE_DIR/base_rootfs.squashfs"
    sudo chown -R "$(id -u):$(id -g)" "$STAGE_DIR/sqfs_root"
    cp -v "$SCRIPT_DIR/set-mib.sh" "$STAGE_DIR/sqfs_root/bin/set-mib.sh"
    chmod 0755 "$STAGE_DIR/sqfs_root/bin/set-mib.sh"
    mkdir -p "$STAGE_DIR/sqfs_root/usr/sbin"
    ln -sf /bin/set-mib.sh "$STAGE_DIR/sqfs_root/usr/sbin/set-mib.sh"

    cat > "$STAGE_DIR/sqfs_root/etc/init.d/ac10-hwparams" << 'EOF'
#!/bin/sh /etc/rc.common
START=18
start() {
    /bin/set-mib.sh
}
boot() {
    /bin/set-mib.sh
}
EOF
    chmod 0755 "$STAGE_DIR/sqfs_root/etc/init.d/ac10-hwparams"
    ln -sf ../init.d/ac10-hwparams "$STAGE_DIR/sqfs_root/etc/rc.d/S18ac10-hwparams"

    # Load rtw88_core WITHOUT any unit-specific hardcoded xtal_cap_override;
    # /etc/rc.d/S18ac10-hwparams -> /bin/set-mib.sh dynamically reads per-unit
    # HW_WLAN0_11N_XCAP from /dev/mtd1, updates xtal_cap_override, and re-probes rtw88_8822be.
    cat > "$STAGE_DIR/sqfs_root/etc/modules.d/rtw88" << 'EOF'
rtw88_core
rtw88_8723de
rtw88_8822be
rtw88_8822ce
EOF

    # UDP gaming / torrent conntrack tuning for 64 MB RAM (4PDA #3584)
    mkdir -p "$STAGE_DIR/sqfs_root/etc/sysctl.d"
    cat > "$STAGE_DIR/sqfs_root/etc/sysctl.d/99-ac10-conntrack.conf" << 'EOF'
# Tenda AC10 V1.0 (64 MB DDR2): prevent UDP/uTP conntrack exhaustion & gaming jitter
net.netfilter.nf_conntrack_max=16384
net.netfilter.nf_conntrack_udp_timeout=60
net.netfilter.nf_conntrack_udp_timeout_stream=180
EOF

    # 4b. Patch rtw88_8822b.ko for true Skyworth SE5003L1 RFE Type 6 & customize scripts
    python3 - "$STAGE_DIR/sqfs_root" "$SCRIPT_DIR" << 'PYEOF'
import os, struct, sys
from collections import defaultdict

root = sys.argv[1]
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))

def patch_and_verify_rtw88_8822b_ko(ko_path: str) -> None:
    raw = bytearray(open(ko_path, "rb").read())
    assert raw[:4] == b"\x7fELF" and raw[4] == 1 and raw[5] == 1, "Expected 32-bit LE ELF"

    e_shoff, = struct.unpack_from("<I", raw, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", raw, 46)
    shdrs = [list(struct.unpack_from("<10I", raw, e_shoff + i * e_shentsize)) for i in range(e_shnum)]
    shstr = bytes(raw[shdrs[e_shstrndx][4]:shdrs[e_shstrndx][4] + shdrs[e_shstrndx][5]])
    sec_by_name = {shstr[s[0]:shstr.index(b"\x00", s[0])].decode(): i for i, s in enumerate(shdrs)}

    idx_text = sec_by_name[".text"]
    idx_rodata = sec_by_name[".rodata"]
    idx_rel_rodata = sec_by_name[".rel.rodata"]
    idx_rostr = sec_by_name[".rodata.str1.4"]
    idx_data = sec_by_name[".data"]
    idx_symtab = sec_by_name[".symtab"]
    idx_strtab = sec_by_name[".strtab"]

    sec_bytes = {
        i: (b"" if s[1] == 8 else bytearray(raw[s[4]:s[4] + s[5]]))
        for i, s in enumerate(shdrs)
    }

    txt = sec_bytes[idx_text]
    ro = sec_bytes[idx_rodata]
    rel_ro = sec_bytes[idx_rel_rodata]
    rostr = sec_bytes[idx_rostr]
    dat = sec_bytes[idx_data]

    patches_8822b = [
        (0x0CF8, 0x24020002, 0x24020006),  # blank-eFuse fallback: rfe_option = 6 (Skyworth SE5003L1)
        (0x1934, 0x1062000C, 0x00000000),  # rtw8822b_set_channel_cca: enable REG_L1WT (0x9194b2b9) for RFE 6 on Cut-B (nop beq)
        (0x2928, 0x2EC20006, 0x2EC20007),  # rtw8822b_config_trx_mode: rfe_option < 7
        (0x2EDC, 0x24130064, 0x241303E8),  # rtw8822b_config_trx_mode: 1x1 path timeout counter 100 -> 1000 (Challenger M1-1)
        (0x2F7C, 0x24130064, 0x241303E8),  # rtw8822b_config_trx_mode: RF reg 0x33 polling timeout counter 100 -> 1000 (200 us -> 2 ms for VHT80 lock)
        (0x3218, 0x24050001, 0x92050031),  # rtw8822b_config_trx_mode: center_channel = hal->current_channel (0x31($s0))
        (0x3220, 0x00003025, 0x92060032),  # rtw8822b_config_trx_mode: bw = hal->current_band_width (0x32($s0))
        (0x32B0, 0x3C030000, 0x3C030003),  # HI16(.rodata + 0x30000)
        (0x32BC, 0x247E0CB0, 0x247E0000),  # LO16(.rodata + 0x30000)
        (0x378C, 0x2EC20006, 0x2EC20007),  # rtw8822b_set_channel_bb:  rfe_option < 7
        (0x4650, 0x3C170000, 0x3C170003),  # HI16(.rodata + 0x30000)
        (0x4658, 0x26F70CB0, 0x26F70000),  # LO16(.rodata + 0x30000)
    ]

    words = [struct.unpack_from("<I", txt, off)[0] for off, _, _ in patches_8822b]
    all_old = all(w == old_w for w, (_, old_w, _) in zip(words, patches_8822b))
    all_new = all(w == new_w for w, (_, _, new_w) in zip(words, patches_8822b))

    old_msg = b"rtw88: blank efuse (rfe=0xff), defaulting rfe_option=2\n"
    new_msg = b"rtw88: blank efuse (rfe=0xff), defaulting rfe_option=6\n"
    NEW_RFE_INFO_OFF = 0x30000
    NEW_RFE_DEFS_OFF = 0x30090

    def verify_relocations_elf(elf_bytes):
        v_shoff, = struct.unpack_from("<I", elf_bytes, 32)
        v_shdrs = [struct.unpack_from("<10I", elf_bytes, v_shoff + i * e_shentsize) for i in range(e_shnum)]
        bases, mem, cur_va = {}, {}, 0xC0915000
        for i, s in enumerate(v_shdrs):
            if s[2] & 0x2:
                align = max(s[8], 4)
                cur_va = (cur_va + align - 1) & ~(align - 1)
                bases[i] = cur_va
                mem[i] = bytearray(s[5]) if s[1] == 8 else bytearray(elf_bytes[s[4]:s[4] + s[5]])
                cur_va += s[5]
        v_sym = elf_bytes[v_shdrs[idx_symtab][4]:v_shdrs[idx_symtab][4] + v_shdrs[idx_symtab][5]]
        def sym_va(sidx):
            _, st_val, _, _, _, st_shndx = struct.unpack_from("<IIIBBH", v_sym, sidx * 16)
            return (0x80100000 + sidx * 16) if st_shndx == 0 else (bases[st_shndx] + st_val)
        for i, s in enumerate(v_shdrs):
            if s[1] == 9 and s[7] in mem:
                tbuf = mem[s[7]]; rb = elf_bytes[s[4]:s[4] + s[5]]
                hi_by_sym = defaultdict(list); last_hi = {}
                for j in range(0, len(rb), 8):
                    r_off, r_info = struct.unpack_from("<II", rb, j)
                    sidx = r_info >> 8; rtype = r_info & 0xFF; sva = sym_va(sidx)
                    w, = struct.unpack_from("<I", tbuf, r_off)
                    if rtype == 2:
                        struct.pack_into("<I", tbuf, r_off, (w + sva) & 0xFFFFFFFF)
                    elif rtype == 5:
                        hi_by_sym[sidx].append((r_off, w)); last_hi[sidx] = w & 0xFFFF
                    elif rtype == 6:
                        lo = (w & 0xFFFF) - (0x10000 if (w & 0x8000) else 0)
                        hi0 = last_hi.get(sidx, 0)
                        for h_off, hw in hi_by_sym[sidx]:
                            v = (sva + ((hw & 0xFFFF) << 16) + lo) & 0xFFFFFFFF
                            struct.pack_into("<I", tbuf, h_off, (hw & 0xFFFF0000) | (((v + 0x8000) >> 16) & 0xFFFF))
                        hi_by_sym[sidx].clear()
                        v = (sva + (hi0 << 16) + lo) & 0xFFFFFFFF
                        struct.pack_into("<I", tbuf, r_off, (w & 0xFFFF0000) | (v & 0xFFFF))
        rfe6_info = struct.unpack_from("<5I", mem[idx_rodata], 0x30000 + 6 * 20)
        assert rfe6_info == (bases[idx_rodata] + 0xD58, bases[idx_rodata] + 0xD58, 1, 0, bases[idx_text] + 0x1A4C)
        rfe6_defs = struct.unpack_from("<2I", mem[idx_rodata], 0x30090 + 6 * 8)
        assert rfe6_defs == (bases[idx_rodata] + 0x16204, bases[idx_rodata] + 0x0E50)

    # 1. State A: Already-Patched
    cur_defs_ptr, cur_defs_sz = struct.unpack_from("<II", dat, 0x94)
    if all_new and len(ro) >= NEW_RFE_DEFS_OFF and new_msg in rostr and cur_defs_ptr == NEW_RFE_DEFS_OFF and cur_defs_sz == 7:
        verify_relocations_elf(raw)
        print(f"  [OK] Already patched & relocation-verified rtw88_8822b.ko for Skyworth SE5003L1 RFE Type 6 ({len(raw):,} B)")
        return

    # 2. State B: Verify Pristine Anchors
    if not (all_old and len(ro) == 0x2DF30 and old_msg in rostr and cur_defs_ptr == 0x904 and cur_defs_sz == 6):
        mismatches = []
        for (off, old_w, new_w), cur_w in zip(patches_8822b, words):
            if cur_w != old_w:
                state = "already patched" if cur_w == new_w else "unknown/corrupted"
                mismatches.append(f"    .text+0x{off:x}: got 0x{cur_w:08x} ({state}), expected pristine 0x{old_w:08x} or target 0x{new_w:08x}")
        if len(ro) != 0x2DF30:
            mismatches.append(f"    .rodata length: got 0x{len(ro):x}, expected pristine 0x2DF30")
        if old_msg not in rostr:
            mismatches.append(f"    .rodata.str1.4: fallback string not pristine")
        if cur_defs_ptr != 0x904 or cur_defs_sz != 6:
            mismatches.append(f"    .data definitions pointer/size: got (0x{cur_defs_ptr:x}, {cur_defs_sz}), expected (0x904, 6)")
        raise AssertionError("rtw88_8822b.ko partially patched or unexpected opcode/state:\n" + "\n".join(mismatches))

    # 3. State B Execution: Apply all 12 patches, expand .rodata, add relocations, update .data
    sym_b = sec_bytes[idx_symtab]
    str_b = sec_bytes[idx_strtab]
    sym_idx_by_name, sec_sym_idx = {}, {}
    for j in range(0, len(sym_b), 16):
        st_name, st_val, st_sz, st_info, st_other, st_shndx = struct.unpack_from("<IIIBBH", sym_b, j)
        sidx = j // 16
        if (st_info & 0xF) == 3:
            sec_sym_idx[st_shndx] = sidx
        if st_name:
            nm = str_b[st_name:str_b.index(b"\x00", st_name)].decode()
            sym_idx_by_name[nm] = (sidx, st_val, st_shndx)

    sym_pg5 = sym_idx_by_name["rtw8822b_bb_pg_type5_tbl"][0]
    sym_lmt5 = sym_idx_by_name["rtw8822b_txpwr_lmt_type5_tbl"][0]
    sym_rodata_sec = sec_sym_idx[idx_rodata]
    sym_text_sec = sec_sym_idx[idx_text]

    for off, _, new_w in patches_8822b:
        struct.pack_into("<I", txt, off, new_w)

    msg_idx = rostr.find(old_msg)
    rostr[msg_idx:msg_idx + len(new_msg)] = new_msg

    ro.extend(b"\x00" * (NEW_RFE_INFO_OFF - len(ro)))
    # rfe_info[0..5] + rfe_info[6] (cca_efem_ccut, cca_efem_ccut, RTW_CCA_SRC_EFEM=1, coex_scbd=0, rtw8822b_config_rfe_efem)
    ro.extend(bytes(ro[0xCB0:0xCB0 + 120]) + struct.pack("<IIIII", 0x00000D58, 0x00000D58, 1, 0, 0x00001A4C))
    ro.extend(b"\x00" * (NEW_RFE_DEFS_OFF - len(ro)))
    # rfe_defs[0..5] + rfe_defs[6] (&rtw8822b_bb_pg_type5_tbl, &rtw8822b_txpwr_lmt_type5_tbl)
    ro.extend(bytes(ro[0x904:0x904 + 48]) + struct.pack("<II", 0, 0))
    if len(ro) % 16:
        ro.extend(b"\x00" * (16 - (len(ro) % 16)))

    R_MIPS_32 = 2
    extra_rels = bytearray()
    for j in range(0, len(rel_ro), 8):
        r_off, r_info = struct.unpack_from("<II", rel_ro, j)
        if 0xCB0 <= r_off < 0xD28:
            extra_rels.extend(struct.pack("<II", NEW_RFE_INFO_OFF + (r_off - 0xCB0), r_info))
        elif 0x904 <= r_off < 0x934:
            extra_rels.extend(struct.pack("<II", NEW_RFE_DEFS_OFF + (r_off - 0x904), r_info))

    RFE6_INFO_OFF = NEW_RFE_INFO_OFF + 6 * 20
    extra_rels.extend(struct.pack("<II", RFE6_INFO_OFF + 0x00, (sym_rodata_sec << 8) | R_MIPS_32))
    extra_rels.extend(struct.pack("<II", RFE6_INFO_OFF + 0x04, (sym_rodata_sec << 8) | R_MIPS_32))
    extra_rels.extend(struct.pack("<II", RFE6_INFO_OFF + 0x10, (sym_text_sec << 8) | R_MIPS_32))

    RFE6_DEFS_OFF = NEW_RFE_DEFS_OFF + 6 * 8
    extra_rels.extend(struct.pack("<II", RFE6_DEFS_OFF + 0x00, (sym_pg5 << 8) | R_MIPS_32))
    extra_rels.extend(struct.pack("<II", RFE6_DEFS_OFF + 0x04, (sym_lmt5 << 8) | R_MIPS_32))
    rel_ro.extend(extra_rels)

    struct.pack_into("<II", dat, 0x94, NEW_RFE_DEFS_OFF, 7)

    out = bytearray(raw[:0x40])
    for idx in sorted(range(1, e_shnum), key=lambda k: (shdrs[k][4], k)):
        sh = shdrs[idx]
        align = max(sh[8], 1)
        if len(out) % align:
            out.extend(b"\x00" * (align - (len(out) % align)))
        sh[4] = len(out)
        if sh[1] != 8:
            sh[5] = len(sec_bytes[idx])
            out.extend(sec_bytes[idx])
    if len(out) % 4:
        out.extend(b"\x00" * (4 - (len(out) % 4)))
    struct.pack_into("<I", out, 32, len(out))
    for sh in shdrs:
        out.extend(struct.pack("<10I", *sh))
    open(ko_path, "wb").write(out)

    # Self-test with Linux arch/mips/kernel/module.c relocation rules
    verify_relocations_elf(out)
    print(f"  [OK] Patched & relocation-verified rtw88_8822b.ko for Skyworth SE5003L1 RFE Type 6 ({len(out):,} B)")

patch_and_verify_rtw88_8822b_ko(os.path.join(root, "lib/modules/4.14.187/rtw88_8822b.ko"))

def patch_and_verify_rtw88_core_ko(ko_path: str) -> None:
    raw = bytearray(open(ko_path, "rb").read())
    assert raw[:4] == b"\x7fELF" and raw[4] == 1 and raw[5] == 1, "Expected 32-bit LE ELF"

    e_shoff, = struct.unpack_from("<I", raw, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", raw, 46)
    shdrs = [list(struct.unpack_from("<10I", raw, e_shoff + i * e_shentsize)) for i in range(e_shnum)]
    shstr = bytes(raw[shdrs[e_shstrndx][4]:shdrs[e_shstrndx][4] + shdrs[e_shstrndx][5]])
    sec_by_name = {shstr[s[0]:shstr.index(b"\x00", s[0])].decode(): i for i, s in enumerate(shdrs)}
    text_off = shdrs[sec_by_name[".text"]][4]

    patches_core = [
        # rtw_tx_fill_tx_desc: clamp rate_id to 4 (DESC_RATE6M = 6 Mbps OFDM) if < 4 (prevent invalid CCK 1M on 5 GHz)
        (0x4228, 0x240AFF80, 0x240A0004),  # addiu $t2, $zero, 4 (DESC_RATE6M)
        (0x422C, 0x00CA3024, 0x2C680004),  # sltiu $t0, $v1, 4 (if rate_id < 4)
        (0x4230, 0x3063007F, 0x0148180B),  # movn  $v1, $t2, $t0 (rate_id = 4)
        (0x4234, 0x00661825, 0x7C663004),  # ins   $a2, $v1, 0, 7 (desc[4] bits 0..6 = rate_id)
        (0x4238, 0xAC430010, 0xAC460010),  # sw    $a2, 0x10($v0) (desc[4] = a2)
        # rtw_tx_fill_tx_desc: enforce dis_rate_fallback = 1 for rate_id <= 4 (prevent CCK fallback on 5 GHz)
        (0x437C, 0x2409FFEF, 0x90890008),  # lbu   $t1, 8($a0) (load pkt_info->rate_id)
        (0x4380, 0x00063100, 0x2D290005),  # sltiu $t1, $t1, 5 (if rate_id <= 4)
        (0x4384, 0x01094024, 0x00C93025),  # or    $a2, $a2, $t1 (dis_rate_fallback |= (rate_id <= 4))
        (0x4388, 0x00C84025, 0x7CC82104),  # ins   $t0, $a2, 4, 1 (insert bit 4 into desc[5])
        # rtw_rsvd_page_pkt_info_update: enforce DESC_RATE6M (4) for Beacons and Nullfunc
        (0x4BDC, 0x24030012, 0x24031204),  # addiu $v1, $zero, 0x1204 (rate_id = 4, sec_ch = 0x12)
        (0x4BE0, 0xA0A30009, 0xA4A30008),  # sh    $v1, 8($a1) (store rate_id and sec_ch)
    ]

    words = [struct.unpack_from("<I", raw, text_off + off)[0] for off, _, _ in patches_core]
    all_old = all(w == old_w for w, (_, old_w, _) in zip(words, patches_core))
    all_new = all(w == new_w for w, (_, _, new_w) in zip(words, patches_core))

    if all_new:
        print(f"  [OK] Already patched & verified rtw88_core.ko for 5 GHz DESC_RATE6M ({len(raw):,} B)")
        return

    if not all_old:
        mismatches = []
        for (off, old_w, new_w), cur_w in zip(patches_core, words):
            if cur_w != old_w:
                state = "already patched" if cur_w == new_w else "unknown/corrupted"
                mismatches.append(f"    .text+0x{off:x}: got 0x{cur_w:08x} ({state}), expected pristine 0x{old_w:08x} or target 0x{new_w:08x}")
        raise AssertionError("rtw88_core.ko partially patched or unexpected opcode(s):\n" + "\n".join(mismatches))

    for off, _, new_w in patches_core:
        struct.pack_into("<I", raw, text_off + off, new_w)

    open(ko_path, "wb").write(raw)

    verify_raw = open(ko_path, "rb").read()
    for off, _, new_w in patches_core:
        v_w, = struct.unpack_from("<I", verify_raw, text_off + off)
        assert v_w == new_w, f"rtw88_core.ko post-patch verification failed at .text+0x{off:x}: got 0x{v_w:08x}, expected 0x{new_w:08x}"

    print(f"  [OK] Patched & verified rtw88_core.ko for 5 GHz DESC_RATE6M ({len(raw):,} B)")

patch_and_verify_rtw88_core_ko(os.path.join(root, "lib/modules/4.14.187/rtw88_core.ko"))

# 1. /lib/realtek.sh: detect "Tenda AC10 V1.0" -> "tenda,ac10-v1"
p_rtk = os.path.join(root, "lib/realtek.sh")
s = open(p_rtk, "r", encoding="utf-8").read()
s = s.replace(
    '*"GWR1200AC V1")\n\t\tname="gwr1200ac-v1"\n\t\t;;',
    '*"Tenda AC10 V1"*)\n\t\tname="tenda,ac10-v1"\n\t\t;;\n\t*"GWR1200AC V1")\n\t\tname="gwr1200ac-v1"\n\t\t;;',
)
open(p_rtk, "w", encoding="utf-8").write(s)

# 2. /etc/board.d/01_leds: configure tenda:blue:sys LED
p_leds = os.path.join(root, "etc/board.d/01_leds")
s = open(p_leds, "r", encoding="utf-8").read()
s = s.replace(
    "  gwr1200ac-v1)",
    '  tenda,ac10-v1)\n    ucidef_set_led_default "sys" "sys" "tenda:blue:sys" "1"\n    ;;\n  gwr1200ac-v1)',
)
open(p_leds, "w", encoding="utf-8").write(s)

# 3. /etc/board.d/02_network: read HW_NIC0_ADDR from /dev/mtd1 (neutral OUI fallback 50:0f:f5:00:00:00)
#    Use base+2 for WAN (eth0.1) because Tenda AC10 V1.0 mtd1 assigns:
#      HW_NIC0_ADDR       = base+0 (LAN br-lan / eth0.2)
#      HW_WLAN1_WLAN_ADDR = base+1 (2.4 GHz wlan0)
#      WAN eth0.1         = base+2 (distinct from LAN, 2.4G, and 5G!)
#      HW_WLAN0_WLAN_ADDR = base+5 (5 GHz wlan1)
p_net = os.path.join(root, "etc/board.d/02_network")
s = open(p_net, "r", encoding="utf-8").read()
ac10_net_case = """  tenda,ac10-v1)
    lan_mac=$(dd if=/dev/mtd1 bs=65536 count=1 2>/dev/null | tr '\\0' '\\n' | tr -d '\\r' | grep '^HW_NIC0_ADDR=' | head -n1 | cut -d= -f2 | sed 's/../&:/g;s/:$//' | tr 'A-F' 'a-f')
    case "$lan_mac" in
      [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) ;;
      *) lan_mac="50:0f:f5:00:00:00" ;;
    esac
    wan_mac=$(macaddr_add "$lan_mac" 2)
    ;;
  gwr1200ac-v1)"""
assert "  gwr1200ac-v1)" in s
s = s.replace("  gwr1200ac-v1)", ac10_net_case, 1)
open(p_net, "w", encoding="utf-8").write(s)

# 4. /etc/init.d/dir842-asic: poll BOTH eth0.2 LAN MAC (HW_NIC0_ADDR) AND eth0.1 cloned WAN MAC,
#    synchronize with wireless interfaces in wait_netif_mac() before gw_prog, arm wan_route_mode=1 (ToCpu),
#    and keep hwnat=1 armed with wireless station discrimination in rtl819x_hwnat.c
p_asic = os.path.join(root, "etc/init.d/dir842-asic")
s = open(p_asic, "r", encoding="utf-8").read()
if '*) want="" ;;' in s:
    s = s.replace(
        '*) want="" ;;',
        '*) want=$(dd if=/dev/mtd1 bs=65536 count=1 2>/dev/null | tr \'\\0\' \'\\n\' | tr -d \'\\r\' | grep \'^HW_NIC0_ADDR=\' | head -n1 | cut -d= -f2 | sed \'s/../&:/g;s/:$//\' | tr \'A-F\' \'a-f\') ;;',
    )
wan_poll_snippet = """\tdone
\t# Synchronize with wireless interfaces before ASIC programming (max 15s)
\ti=0
\twhile [ $i -lt 15 ]; do
\t\t[ -d /sys/class/net/br-lan/brif/wlan0 ] && [ -d /sys/class/net/br-lan/brif/wlan1 ] && break
\t\ti=$((i+1)); sleep 1
\tdone
\twan_want=$(uci -q get network.wan.macaddr 2>/dev/null | tr "A-F" "a-f")
\tif [ -n "$wan_want" ]; then
\t\ti=0
\t\twhile [ $i -lt 30 ]; do
\t\t\t[ "$(cat /sys/class/net/eth0.1/address 2>/dev/null)" = "$wan_want" ] && break
\t\t\ti=$((i+1)); sleep 1
\t\tdone
\tfi
\tsleep 2
}"""
if "\tdone\n\tsleep 2\n}" in s:
    s = s.replace("\tdone\n\tsleep 2\n}", wan_poll_snippet, 1)

old_rearm = 'echo 1 > /sys/module/rtl819x/parameters/fabric_gw_rearm 2>/dev/null\n\tfi'
new_rearm = 'echo 1 > /sys/module/rtl819x/parameters/fabric_gw_rearm 2>/dev/null\n\t\techo 1 > /sys/module/rtl819x/parameters/wan_route_mode 2>/dev/null\n\tfi'
if 'wan_route_mode' not in s and old_rearm in s:
    s = s.replace(old_rearm, new_rearm, 1)

open(p_asic, "w", encoding="utf-8").write(s)
os.chmod(p_asic, 0o755)

# 4b. Deploy Milestone 3 differential dir842-l2flush and neutralized asic-wifi-settle
p_settle = os.path.join(root, "etc/init.d/asic-wifi-settle")
open(p_settle, "w", encoding="utf-8").write(
    "#!/bin/sh /etc/rc.common\n"
    "# Non-disruptive ASIC synchronization shim.\n"
    "# Replaces the disruptive 120s wait + full fabric reset with non-disruptive boot synchronization.\n\n"
    "START=99\n\n"
    "start() {\n"
    '\t# Datapath bring-up is synchronized directly in /etc/init.d/dir842-asic at boot.\n'
    '\t# Background restart is omitted to prevent link drops and 2.5s network freezes.\n'
    '\tlogger -t asic-wifi-settle "ASIC synchronization active (non-disruptive, no fabric reset)"\n'
    '\treturn 0\n'
    "}\n\n"
    "stop() {\n\t:\n}\n"
)
os.chmod(p_settle, 0o755)

l2flush_src_path = os.path.join(script_dir, "tools", "scripts", "dir842-l2flush")
l2flush_content = open(l2flush_src_path, "r", encoding="utf-8").read()
p_l2flush = os.path.join(root, "etc/init.d/dir842-l2flush")
p_l2flush_bin = os.path.join(root, "usr/sbin/dir842-l2flush")
open(p_l2flush, "w", encoding="utf-8").write(l2flush_content)
os.chmod(p_l2flush, 0o755)
os.makedirs(os.path.dirname(p_l2flush_bin), exist_ok=True)
open(p_l2flush_bin, "w", encoding="utf-8").write(l2flush_content)
os.chmod(p_l2flush_bin, 0o755)

# 5. /etc/uci-defaults/99-dir842-m5: Switch Port 3 = WAN (vlan 1), Ports 0,1,2 = LAN (vlan 2),
#    Tenda SSID/MAC (neutral fallback 50:0f:f5:00:00:05), bind radio0 by PCIe path (immune to phy0->phy1),
#    VHT80 default on channel 36 + country=US (23 dBm, 866.7 Mbps PHY with extended RF 0x33 poll timeout),
#    software flow_offloading=1, clean IPv4 + RFC 9462 DDR DNS defaults for iOS/macOS compatibility,
#    WAN shared-VLAN socket isolation (dnsmasq notinterface=eth0.1, uhttpd 0.0.0.0:80 / [::]:80 with WAN drop and rfc1918_filter),
#    and 256 KB ring buffer log_size.
p_m5 = os.path.join(root, "etc/uci-defaults/99-dir842-m5")
s = open(p_m5, "r", encoding="utf-8").read()
assert "set network.@switch_vlan[-1].ports='4 6t'" in s
assert "set network.@switch_vlan[-1].ports='0 1 2 3 6t'" in s
s = s.replace("set network.@switch_vlan[-1].ports='4 6t'", "set network.@switch_vlan[-1].ports='3 6t'")
s = s.replace("set network.@switch_vlan[-1].ports='0 1 2 3 6t'", "set network.@switch_vlan[-1].ports='0 1 2 6t'")
s = s.replace("set wireless.radio0.htmode='HT20'", "set wireless.radio0.htmode='VHT80'")
s = s.replace("set wireless.radio0.country='BR'", "set wireless.radio0.country='US'")
s = s.replace("set wireless.default_radio0.ssid='DIR842-OpenWrt'", "set wireless.default_radio0.ssid='Tenda-AC10-5G'")
s = s.replace(
    "DIR842_WIFI_MAC='02:11:22:33:44:56' ;;",
    "DIR842_WIFI_MAC=$(dd if=/dev/mtd1 bs=65536 count=1 2>/dev/null | tr '\\0' '\\n' | tr -d '\\r' | grep '^HW_WLAN0_WLAN_ADDR=' | head -n1 | cut -d= -f2 | sed 's/../&:/g;s/:$//' | tr 'A-F' 'a-f')\n\tcase \"$DIR842_WIFI_MAC\" in [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) ;; *) DIR842_WIFI_MAC='50:0f:f5:00:00:05' ;; esac ;;",
)
s = s.replace(
    "set wireless.default_radio0.macaddr=\"$DIR842_WIFI_MAC\"",
    "set wireless.default_radio0.macaddr=\"$DIR842_WIFI_MAC\"\nset wireless.default_radio0.ifname='wlan1'\nset wireless.default_radio0.wmm='1'\nset wireless.default_radio0.multicast_to_unicast='0'\nset wireless.default_radio0.disassoc_low_ack='0'\nset wireless.default_radio0.ieee80211w='0'",
)
phy_bind_snippet = """_ac10_phy=$(ls /sys/bus/pci/drivers/rtw_8822be/*/ieee80211 2>/dev/null | head -n1)
[ -z "$_ac10_phy" ] && _ac10_phy=$(ls /sys/class/ieee80211 2>/dev/null | head -n1)
if [ -n "$_ac10_phy" ]; then
\t_ac10_path=$(. /lib/netifd/mac80211.sh 2>/dev/null; mac80211_phy_to_path "$_ac10_phy" 2>/dev/null)
\tif [ -n "$_ac10_path" ]; then
\t\tuci -q set wireless.radio0.path="$_ac10_path"
\t\tuci -q delete wireless.radio0.phy
\telse
\t\tuci -q set wireless.radio0.phy="$_ac10_phy"
\tfi
\tuci -q delete wireless.radio0.macaddr
\tuci -q set wireless.radio0.country='US'
\tuci -q set wireless.radio0.channel='36'
\tuci -q set wireless.radio0.htmode='VHT20'
\tuci -q commit wireless
fi
uci -q delete network.globals.ula_prefix
uci -q commit network
uci -q set firewall.@defaults[0].flow_offloading='1'
uci -q set firewall.@defaults[0].flow_offloading_hw='1'
uci -q set firewall.block_wan_http='rule'
uci -q set firewall.block_wan_http.name='Block-WAN-HTTP'
uci -q set firewall.block_wan_http.src='wan'
uci -q set firewall.block_wan_http.proto='tcp'
uci -q set firewall.block_wan_http.dest_port='80'
uci -q set firewall.block_wan_http.target='DROP'
uci -q commit firewall
cat << 'EOF' >> /etc/firewall.user
# Drop incoming HTTP port 80 on physical WAN interface eth0.1
iptables -I INPUT -i eth0.1 -p tcp --dport 80 -j DROP 2>/dev/null || true
ip6tables -I INPUT -i eth0.1 -p tcp --dport 80 -j DROP 2>/dev/null || true
EOF
uci -q set dhcp.@dnsmasq[0].rebind_protection='0'
uci -q set dhcp.@dnsmasq[0].cachesize='1000'
uci -q del_list dhcp.@dnsmasq[0].notinterface='eth0.1' 2>/dev/null || true
uci -q add_list dhcp.@dnsmasq[0].notinterface='eth0.1'
uci -q set dhcp.lan.ra='disabled'
uci -q set dhcp.lan.dhcpv6='disabled'
uci -q delete dhcp.lan.ra_slaac
uci -q delete dhcp.lan.ra_flags
uci -q delete dhcp.lan.dhcp_option
uci -q add_list dhcp.lan.dhcp_option='6,1.1.1.1,8.8.8.8,192.168.0.1'
uci -q commit dhcp
uci -q delete uhttpd.main.listen_http 2>/dev/null || true
uci -q add_list uhttpd.main.listen_http='0.0.0.0:80'
uci -q add_list uhttpd.main.listen_http='[::]:80'
uci -q set uhttpd.main.rfc1918_filter='1'
uci -q delete uhttpd.main.listen_https 2>/dev/null || true
uci -q set uhttpd.main.redirect_https='0'
uci -q commit uhttpd
uci -q set system.@system[0].hostname='Tenda-AC10-V1'
uci -q set system.@system[0].log_size='256'
uci -q set system.@system[0].dir842_m5_seeded='1'"""
s = s.replace(
    "uci -q set system.@system[0].dir842_m5_seeded='1'",
    phy_bind_snippet,
)
open(p_m5, "w", encoding="utf-8").write(s)

# 5b. /etc/uci-defaults/11_dir842-htmode-ht20: do not clobber user-selected VHT40/VHT80 across sysupgrade
p_ht20 = os.path.join(root, "etc/uci-defaults/11_dir842-htmode-ht20")
if os.path.exists(p_ht20):
    open(p_ht20, "w", encoding="utf-8").write("#!/bin/sh\n# Tenda AC10 V1.0: preserve user-selected 5 GHz htmode (VHT80 default; VHT20/VHT40 optional)\nexit 0\n")

# 5c. /lib/preinit/80_mount_root: auto-erase stale stock Tenda SquashFS bytes at rootfs_data before mount_root
p_mr = os.path.join(root, "lib/preinit/80_mount_root")
s_mr = open(p_mr, "r", encoding="utf-8").read()
rfd_guard = """do_mount_root() {
\tlocal _rfd_mtd=$(sed -n 's/^\\(mtd[0-9]\\+\\):.*\\"rootfs_data\\"/\\1/p' /proc/mtd 2>/dev/null | head -n1)
\tif [ -n "$_rfd_mtd" ] && [ -c "/dev/$_rfd_mtd" ]; then
\t\tlocal _rfd_hdr=$(dd if="/dev/$_rfd_mtd" bs=4 count=1 2>/dev/null | hexdump -v -e '4/1 "%02x"')
\t\tcase "$_rfd_hdr" in
\t\t\t1985*|8519*|deadc0de|ffffffff|"") ;;
\t\t\t*)
\t\t\t\techo "ac10-preinit: formatting stale stock bytes on /dev/$_rfd_mtd (hdr=0x$_rfd_hdr) for JFFS2 overlay" > /dev/kmsg
\t\t\t\tmtd erase rootfs_data 2>/dev/null || printf '\\xde\\xad\\xc0\\xde' | mtd write - rootfs_data 2>/dev/null
\t\t\t\t;;
\t\tesac
\tfi
\tmount_root"""
assert "do_mount_root() {\n\tmount_root" in s_mr
s_mr = s_mr.replace("do_mount_root() {\n\tmount_root", rfd_guard, 1)
open(p_mr, "w", encoding="utf-8").write(s_mr)

# 5d. /lib/preinit/00_preinit.conf: prevent floating GPIO 6 (wps) from pausing preinit in failsafe mode
p_pi00 = os.path.join(root, "lib/preinit/00_preinit.conf")
if os.path.exists(p_pi00):
    s_pi00 = open(p_pi00, "r", encoding="utf-8").read()
    s_pi00 = s_pi00.replace('pi_preinit_no_failsafe=""', 'pi_preinit_no_failsafe="y"')
    open(p_pi00, "w", encoding="utf-8").write(s_pi00)

# 6. /etc/uci-defaults/09_wireless-dualband-dir842: 2.4G SSID = Tenda-AC10-2G, keep urban interference-safe HT20 default,
#    and drop D-Link's hardcoded country='1' so rtl8192cd.sh inherits factory HW_WLAN1_REG_DOMAIN from /dev/mtd1.
p_w2 = os.path.join(root, "etc/uci-defaults/09_wireless-dualband-dir842")
s = open(p_w2, "r", encoding="utf-8").read()
s = s.replace("set wireless.default_radio1.ssid='DIR842-2G'", "set wireless.default_radio1.ssid='Tenda-AC10-2G'")
s = s.replace("set wireless.radio1.country='1'\n", "")
assert "set wireless.radio1.htmode='HT20'" in s
open(p_w2, "w", encoding="utf-8").write(s)

# 7. /lib/netifd/wireless/rtl8192cd.sh: inject Tenda AC10 V1.0 2.4G RF calibration (RFE Type 5, XCAP, THER, TX power tables,
#    HW_WLAN1_REG_DOMAIN, HW_WLAN1_WLAN_ADDR MAC) + vladisslav0 4PDA #97815216 & #98016337 UDP/uTP fixes
p_drv = os.path.join(root, "lib/netifd/wireless/rtl8192cd.sh")
s = open(p_drv, "r", encoding="utf-8").read()
assert "json_get_vars channel htmode country band phy macaddr beacon_int dtim_period led_type" in s
s = s.replace(
    "local beacon_int dtim_period v",
    "local beacon_int dtim_period noscan led_type v",
    1,
)
s = s.replace(
    "json_get_vars channel htmode country band phy macaddr beacon_int dtim_period led_type",
    "json_get_vars channel htmode country band phy macaddr beacon_int dtim_period noscan led_type",
    1,
)
cal_snippet = """\t\techo "${phy_ifname}_phyBandSelect=1"
\t\t# Inject Tenda AC10 V1.0 mtd1 2.4 GHz Factory Calibration (RTL8197FS + Skyworth SKY85303-11 RFE Type 5)
\t\t_cal_tmp="/tmp/ac10_2g_cal.$$"
\t\tdd if=/dev/mtd1 bs=65536 count=1 2>/dev/null | tr '\\0' '\\n' | tr -d '\\r' > "$_cal_tmp"
\t\t_xcap=$(grep '^HW_WLAN1_11N_XCAP=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_xcap" ] && _xcap="46"
\t\t_ther=$(grep '^HW_WLAN1_11N_THER=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_ther" ] && _ther="32"
\t\t_regdom=$(grep '^HW_WLAN1_REG_DOMAIN=' "$_cal_tmp" | head -n1 | cut -d= -f2)
\t\tcase "$_regdom" in ''|*[!0-9]*) _regdom="13" ;; esac
\t\t_cck_a=$(grep '^HW_WLAN1_TX_POWER_CCK_A=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_cck_a" ] && _cck_a="2020202222222222222626262626"
\t\t_cck_b=$(grep '^HW_WLAN1_TX_POWER_CCK_B=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_cck_b" ] && _cck_b="1a1a1a1b1b1b1b1b1b1e1e1e1e1e"
\t\t_ht40_a=$(grep '^HW_WLAN1_TX_POWER_HT40_1S_A=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_ht40_a" ] && _ht40_a="1a1a1a1a1a1a1a1a1a1d1d1d1d1d"
\t\t_ht40_b=$(grep '^HW_WLAN1_TX_POWER_HT40_1S_B=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_ht40_b" ] && _ht40_b="1515151616161616161717171717"
\t\t_d_ht20=$(grep '^HW_WLAN1_TX_POWER_DIFF_HT20=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_d_ht20" ] && _d_ht20="0000001111111111112222222222"
\t\t_d_ofdm=$(grep '^HW_WLAN1_TX_POWER_DIFF_OFDM=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_d_ofdm" ] && _d_ofdm="1111112222222222223333333333"
\t\t_d_ht40=$(grep '^HW_WLAN1_TX_POWER_DIFF_HT40_2S=' "$_cal_tmp" | head -n1 | cut -d= -f2); [ -z "$_d_ht40" ] && _d_ht40="0000000000000000000000000000"
\t\t_wmac2g=$(grep '^HW_WLAN1_WLAN_ADDR=' "$_cal_tmp" | head -n1 | cut -d= -f2 | sed 's/../&:/g;s/:$//' | tr 'A-F' 'a-f')
\t\trm -f "$_cal_tmp"
\t\tcase "$_wmac2g" in [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) ;; *) _wmac2g="50:0f:f5:00:00:01" ;; esac
\t\t[ -z "$macaddr" ] && macaddr="$_wmac2g"
\t\techo "${phy_ifname}_xcap=$_xcap"
\t\techo "${phy_ifname}_ther=$_ther"
\t\techo "${phy_ifname}_rfe_type=5"
\t\techo "${phy_ifname}_pwrlevelCCK_A=$_cck_a"
\t\techo "${phy_ifname}_pwrlevelCCK_B=$_cck_b"
\t\techo "${phy_ifname}_pwrlevelHT40_1S_A=$_ht40_a"
\t\techo "${phy_ifname}_pwrlevelHT40_1S_B=$_ht40_b"
\t\techo "${phy_ifname}_pwrdiffHT20=$_d_ht20"
\t\techo "${phy_ifname}_pwrdiffOFDM=$_d_ofdm"
\t\techo "${phy_ifname}_pwrdiffHT40_2S=$_d_ht40"
\t\techo "${phy_ifname}_shortGI20M=1"
\t\techo "${phy_ifname}_shortGI40M=1"
\t\techo "${phy_ifname}_ampdu=1"
\t\techo "${phy_ifname}_manual_edca=1"
\t\techo "${phy_ifname}_disable_txsc=1"
\t\techo "${phy_ifname}_amsdu=1"
\t\techo "${phy_ifname}_trswitch=1"
\t\techo "${phy_ifname}_txbf=0"
\t\techo "${phy_ifname}_led_type=${led_type:-7}"
\t\techo "${phy_ifname}_dtimperiod=${dtim_period:-3}"
\t\t[ "$noscan" = "1" ] && echo "${phy_ifname}_coexist=0" """
assert '\t\techo "${phy_ifname}_phyBandSelect=1"' in s
assert '\t\t[ -n "$country" ] && echo "${phy_ifname}_regdomain=$country"' in s
s = s.replace('\t\techo "${phy_ifname}_phyBandSelect=1"', cal_snippet, 1)
s = s.replace(
    '\t\t[ -n "$country" ] && echo "${phy_ifname}_regdomain=$country"',
    '\t\techo "${phy_ifname}_regdomain=${country:-$_regdom}"',
    1,
)
open(p_drv, "w", encoding="utf-8").write(s)

# 8. /lib/upgrade/platform.sh: accept cs6c / cr6c on tenda,ac10-v1
p_upg = os.path.join(root, "lib/upgrade/platform.sh")
s = open(p_upg, "r", encoding="utf-8").read()
ac10_upg = """\ttenda,ac10-v1)
\t\tlocal magic
\t\tmagic=$(get_magic_long "$1")
\t\tif [ "$magic" != "63733663" ] && [ "$magic" != "63723663" ]; then
\t\t\techo "Invalid image: expected cs6c/cr6c firmware header, got 0x$magic"
\t\t\treturn 1
\t\tfi
\t\treturn 0
\t\t;;
\tgwr1200ac-v1)"""
s = s.replace("\tgwr1200ac-v1)", ac10_upg, 1)
open(p_upg, "w", encoding="utf-8").write(s)
print("  [OK] Customized SquashFS rootfs scripts & patched rtw88_8822b.ko for Tenda AC10 V1.0")
PYEOF

    mksquashfs "$STAGE_DIR/sqfs_root" "$STAGE_DIR/ac10_rootfs.squashfs" \
        -comp xz -b 262144 -noappend -all-root

    # 5. Assemble factory.bin, sysupgrade.bin, and webupgrade.bin
    python3 - "$STAGE_DIR" "$OUT_DIR" << 'PYEOF'
import os, struct, sys, zlib

stage_dir, out_dir = sys.argv[1], sys.argv[2]

def sum16_be(data: bytes) -> int:
    return sum(struct.unpack(f">{len(data)//2}H", data)) & 0xFFFF

stub = open(os.path.join(stage_dir, "loader_stub.bin"), "rb").read()
lzma_padded = open(os.path.join(stage_dir, "kernel_lzma_padded.bin"), "rb").read()
tail_fakeroot = open(os.path.join(stage_dir, "loader_tail_and_fakeroot.bin"), "rb").read()
sqfs = open(os.path.join(stage_dir, "ac10_rootfs.squashfs"), "rb").read()

# Verify exact offsets: 16 (cvimg) + 0x1824 (stub) + 0x1A31E8 (lzma) + 0xB868 (tail_fakeroot) == 0x1B0284
assert 16 + len(stub) + len(lzma_padded) + len(tail_fakeroot) == 0x1B0284

# Pad SquashFS to 4 KB boundary
if len(sqfs) % 4096 != 0:
    sqfs += b"\x00" * (4096 - (len(sqfs) % 4096))

payload = bytearray(stub + lzma_padded + tail_fakeroot + sqfs)
if len(payload) % 2 == 1:
    payload.append(0x00)

chk = (-sum16_be(bytes(payload))) & 0xFFFF
payload.extend(struct.pack(">H", chk))
seg_len = len(payload)
assert sum16_be(bytes(payload)) == 0, "16-bit BE checksum != 0x0000"

cs6c_img = b"cs6c" + struct.pack(">III", 0x80A00000, 0x00030000, seg_len) + bytes(payload)
assert 0x00030000 + len(cs6c_img) <= 0x007E0000, "Firmware exceeds 7,872 KB partition!"

factory_path = os.path.join(out_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
sysupgrade_path = os.path.join(out_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin")
webupgrade_path = os.path.join(out_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin")

open(factory_path, "wb").write(cs6c_img)
open(sysupgrade_path, "wb").write(cs6c_img)

# Construct 64-byte Tenda 'trx2' (fw_type == 2) Web UI header verified against libcommon.so & booter_stage2:
# - check_fw_type @ 0x00010cd8:  ntohl(*(uint32_t*)(hdr + 0x00)) == 0x27051956 (IH_MAGIC)
# - check_fw_type @ 0x00010d10:  *(uint8_t*)(hdr + 0x20) == 0x02 (ih_os == 2 -> returns fw_type = 2)
# - check_fw_valid(2) @ 0x12484: ntohl(*(uint32_t*)(hdr + 0x24)) == 0x00030028 (AC10 V1.0 policy version)
# - check_mtd_size(2) @ 0x11cfc: st_size < 0x7B0000 (8,060,928 B)
# - check_fw_crc(2) @ 0x119d8:   ntohl(*(uint32_t*)(hdr + 0x0C)) == len(cs6c_img)
#                     0x11ab0:   ntohl(*(uint32_t*)(hdr + 0x18)) == zlib.crc32(cs6c_img, 0) & 0xFFFFFFFF
# - AutoBurn @ 0x80001b84:       booter_stage2 ALSO auto-skips 64-byte 0x27051956 header during TFTP!
trx2_hdr = bytearray(64)
struct.pack_into(">I", trx2_hdr, 0x00, 0x27051956)
struct.pack_into(">I", trx2_hdr, 0x0C, len(cs6c_img))
struct.pack_into(">I", trx2_hdr, 0x18, zlib.crc32(cs6c_img, 0) & 0xFFFFFFFF)
trx2_hdr[0x20] = 0x02
struct.pack_into(">I", trx2_hdr, 0x24, 0x00030028)
web_img = bytes(trx2_hdr) + cs6c_img
assert len(web_img) < 0x7B0000
open(webupgrade_path, "wb").write(web_img)

for p in (factory_path, sysupgrade_path, webupgrade_path):
    print(f"  [BUILT] {os.path.basename(p)}: {os.path.getsize(p):,} bytes")
PYEOF
    rm -rf "$STAGE_DIR"
else

# Full source build path (FULL_SOURCE_BUILD=1)
echo "=============================================================================="
echo "[WARNING] EXPERIMENTAL FULL_SOURCE_BUILD=1 MODE SELECTED!"
echo "  Production builds use deterministic [FAST-HYBRID] mode (FULL_SOURCE_BUILD=0),"
echo "  which applies verified binary vmlinux RTL8367RB port-map patches and"
echo "  rtw88_8822b.ko Skyworth SE5003L1 RFE Type 6 ELF relocations directly to the"
echo "  audited 4.14.187 kernel & modules. Ensure equivalent C source patches are"
echo "  applied to your local source tree before flashing a FULL_SOURCE_BUILD image."
echo "=============================================================================="
if [ ! -f "./scripts/feeds" ] && [ -d "./files/target/linux/realtek" ]; then
    echo "[1.5/7] Bootstrapping ggbruno/openwrt (8a0ccb9) base tree and applying ADCDS overlay..."
    git clone https://github.com/ggbruno/openwrt.git _ggbruno_base
    (cd _ggbruno_base && git checkout 8a0ccb93f3431bcf8f5c5d03d4acc2c8e442de67)
    mv files _adcds_overlay
    cp -a _ggbruno_base/. .
    rm -rf _ggbruno_base
    cp -a _adcds_overlay/. .
    rm -rf _adcds_overlay
fi

echo "[2/7] Installing Tenda AC10 V1.0 Device Tree (tenda-ac10-v1.dts) & Image Recipe..."
DTS_DST_DIR="target/linux/realtek/dts"
mkdir -p "$DTS_DST_DIR"
cp -v "$SCRIPT_DIR/tenda-ac10-v1.dts" "$DTS_DST_DIR/tenda-ac10-v1.dts"

IMG_MK="target/linux/realtek/image/Makefile"
mkdir -p "$(dirname "$IMG_MK")"
if [ ! -f "$IMG_MK" ] || ! grep -q "define Device/tenda_ac10-v1" "$IMG_MK"; then
    python3 - "$IMG_MK" << 'PYEOF'
import os, sys
mk_path = sys.argv[1]
stanza = """
define Device/tenda_ac10-v1
  $(Device/RealtekDTS)
  BLOCKSIZE := 64k
  DEVICE_DTS := tenda-ac10-v1
  DEVICE_TITLE := Tenda AC10 V1.0
  SUPPORTED_DEVICES := tenda,ac10-v1
  IMAGE_SIZE := 7872k
  DEV_PROFILE := tenda_ac10-v1
  CMDLINE := console=ttyS0,115200
  KERNEL := kernel-bin | append-dtb | lzma | loader-cmdline-compile
  CVIMG_KERNEL_BURN_ADDR := 0x30000
  CVIMG_LOADER_START_ADDR := 0x80A00000
  DEVICE_PACKAGES := wireless-tools
  IMAGES := factory.bin sysupgrade.bin
  IMAGE/factory.bin = append-kernel | append-fake-rootfs | append-rootfs | cvimg-kernel | cvimg-pad-rootfs
  IMAGE/sysupgrade.bin = append-kernel | append-fake-rootfs | append-rootfs | cvimg-kernel | pad-rootfs
endef
TARGET_DEVICES += tenda_ac10-v1
"""
content = open(mk_path, "r", encoding="utf-8").read() if os.path.exists(mk_path) else ""
marker = "$(eval $(call BuildImage))"
if marker in content:
    content = content.replace(marker, stanza.lstrip("\n") + "\n" + marker, 1)
else:
    content = content + "\n" + stanza.lstrip("\n")
open(mk_path, "w", encoding="utf-8").write(content)
PYEOF
fi

echo "[3/7] Installing POSIX mtd1 RF calibration injector (/bin/set-mib.sh)..."
mkdir -p files/bin files/usr/sbin files/etc/init.d
cp -v "$SCRIPT_DIR/set-mib.sh" files/bin/set-mib.sh
chmod +x files/bin/set-mib.sh
ln -sf /bin/set-mib.sh files/usr/sbin/set-mib.sh

cat > files/etc/init.d/ac10-hwparams << 'EOF'
#!/bin/sh /etc/rc.common
START=18
start() {
    /bin/set-mib.sh
}
boot() {
    /bin/set-mib.sh
}
EOF
chmod +x files/etc/init.d/ac10-hwparams

echo "[4/7] Applying Hybrid OpenWrt 4.14 Config Overrides & Updating Feeds..."
./scripts/feeds update -a
./scripts/feeds install -a
grep -E '^[+-]?(CONFIG_|# CONFIG_)' "$SCRIPT_DIR/kernel-4.14.config.diff" | sed 's/^[+-]//' > .config
mkdir -p target/linux/realtek/rtl8197f
if [ -f target/linux/realtek/rtl8197f/config-4.14 ]; then
    sed -i '/^CONFIG_RTL8192CD=/d' target/linux/realtek/rtl8197f/config-4.14
fi
grep -E '^[+-]?(CONFIG_|# CONFIG_)' "$SCRIPT_DIR/kernel-4.14.config.diff" | sed 's/^[+-]//' >> target/linux/realtek/rtl8197f/config-4.14
make defconfig

echo "[5/7] Building Tenda AC10 V1.0 Hybrid OpenWrt image (cs6c @ 0x00030000) with -j${JOBS}..."
make -j"$JOBS" V=s
fi

echo "[7/7] Validating output images against Realtek Booter v3.4.11B.9 AutoBurn (0x800019d0) & libcommon.so rules..."
python3 - << 'PYEOF'
import glob, os, struct, zlib

def sum16_be(data: bytes) -> int:
    return sum(struct.unpack(f">{len(data)//2}H", data)) & 0xFFFF

bins = sorted(glob.glob("bin/targets/**/*.bin", recursive=True))
if not bins:
    raise SystemExit("ERROR: No .bin firmware artifacts produced under bin/targets/!")

for path in bins:
    raw = open(path, "rb").read()
    if len(raw) < 64:
        raise SystemExit(f"ERROR: {path} too small ({len(raw)} B)")
    magic_u32, = struct.unpack_from(">I", raw, 0)
    inner = raw
    if magic_u32 == 0x27051956:
        ih_size, = struct.unpack_from(">I", raw, 0x0C)
        ih_dcrc, = struct.unpack_from(">I", raw, 0x18)
        ih_os = raw[0x20]
        ih_ver, = struct.unpack_from(">I", raw, 0x24)
        inner = raw[64:]
        assert ih_os == 2, f"{path}: ih_os={ih_os} != 2"
        assert ih_ver == 0x00030028, f"{path}: ih_ver=0x{ih_ver:08X} != 0x00030028"
        assert ih_size == len(inner), f"{path}: ih_size={ih_size} != payload {len(inner)}"
        assert ih_dcrc == (zlib.crc32(inner, 0) & 0xFFFFFFFF), f"{path}: ih_dcrc mismatch!"
        assert len(raw) < 0x7B0000, f"{path}: webupgrade size >= 0x7B0000!"
        print(f"[PASS] {path}: valid 64-byte Tenda 0x27051956 trx2 wrapper (ih_ver=0x00030028, crc32=0x{ih_dcrc:08X})")

    magic = inner[:4]
    start_addr, burn_addr, seg_len = struct.unpack_from(">III", inner, 4)
    if magic not in (b"cs6c", b"cr6c"):
        raise SystemExit(f"ERROR: {path} unexpected inner magic {magic!r}")
    if magic == b"cs6c" and len(inner) > 16 + seg_len + 4 and magic_u32 != 0x27051956:
        print(f"[FIXUP] Repacking multi-segment cs6c -> single-segment cs6c for {path}...")
        payload = bytearray(inner[16:])
        if len(payload) % 2 == 1:
            payload.append(0x00)
        chk = (-sum16_be(bytes(payload))) & 0xFFFF
        payload.extend(struct.pack(">H", chk))
        seg_len = len(payload)
        inner = b"cs6c" + struct.pack(">III", 0x80A00000, 0x00030000, seg_len) + bytes(payload)
        open(path, "wb").write(inner)

    assert burn_addr == 0x00030000, f"{path}: unsafe burnAddr 0x{burn_addr:08X} != 0x00030000"
    assert start_addr == 0x80A00000, f"{path}: unexpected startAddr 0x{start_addr:08X} != 0x80A00000"
    assert 0x00030000 + len(inner) <= 0x007E0000, f"{path}: size {len(inner)} overflows 7,872 KB firmware slot!"
    assert sum16_be(inner[16:16+seg_len]) == 0, f"{path}: 16-bit BE cvimg checksum != 0x0000!"
    if magic == b"cs6c":
        assert len(inner) <= 16 + seg_len + 4, f"{path}: LETHAL multi-segment cs6c still present!"
    print(f"[PASS] {path}: {magic.decode()} single-safe, burn=0x{burn_addr:06X}, size={len(inner):,} B, csum=0x0000")
PYEOF

echo "=============================================================================="
echo "BUILD & BOOTLOADER SAFETY VALIDATION COMPLETE! Images in: $WORK_DIR/openwrt-hybrid/bin/targets/"
find bin/targets/ -type f \( -name "*.bin" -o -name "*.dtb" \) -exec ls -lh {} +
echo "=============================================================================="
