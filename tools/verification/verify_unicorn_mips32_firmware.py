#!/usr/bin/env python3
"""
Standalone Unicorn MIPS32r2 CPU Emulation Verifier for Tenda AC10 V1.0 Hybrid OpenWrt 4.14
==========================================================================================

Executes real MIPS32EL machine instructions from the shipped firmware binaries inside the
Unicorn CPU emulator (zero mocks of target binary logic) across three verification suites:

  Suite A — Stock Bootloader Stage-2 (`booter_stage2_v3.4.11B.9_0x80000000.bin` @ 0x80000000):
    1. `AutoBurn` (0x800019D0) + `check_image` (0x8000DD10) on Hybrid `factory.bin`
       -> proves single-segment `cs6c` burns cleanly to SPI NOR `0x030000` and passes cold-boot checksum.
    2. `AutoBurn` (0x800019D0) + `check_image` (0x8000DD10) on Hybrid `webupgrade.bin`
       -> proves `0x80001B84` (`addiu $v1, $zero, 0x40`) natively skips the 64-byte `0x27051956`
          Tenda WebUI wrapper and burns identical bytes to `0x030000`.
    3. `AutoBurn` (0x800019D0) + `check_image` (0x8000DD10) on `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`
       -> proves two-segment `cr6c + hsqs` burns `cr6c` to `0x030000` and `hsqs` to `0x23BC12`
          (including partial-sector read-modify-write at `0x230000`) and passes dual cold-boot checks.
    4. Corrupted `cs6c` payload checksum -> proves `AutoBurn` aborts with `-2` and 0 SPI flash writes.
    5. Adversarial two-segment `cs6c + hsqs` brick reproducer -> proves `0x80001C2C` (`move $s7, $s2`
       with `$s2 == 0`) leaves `0x6c($sp) == 0`, causing segment 2 to target flash `0x00000000` (mtd0!).

  Suite B — Stock `/lib/libcommon.so` WebUI Upgrade Validators (self-extracted in pure Python
            from Tenda-XZ SquashFS 4.0 `rootfs_squashfs_tenda_xz_0x23BC12.bin`):
    1. `check_fw_type` (0x10AFC), `check_mtd_size` (0x11CFC), `check_fw_crc` (0x11894),
       `check_fw_valid` (0x122F4) on real Hybrid `webupgrade.bin` -> `fw_type == 2`, all return `1`.
    2. Raw `factory.bin` (`cs6c` without 64-byte wrapper) -> rejected by WebUI (`check_fw_type == -1`).
    3. Corrupted `ih_dcrc` -> rejected by `check_fw_crc == -1`.
    4. Wrong `ih_ver != 0x00030028` (e.g. AC10U/foreign model header) -> rejected by `check_fw_valid == -1`.
    5. Oversized payload (`>= 0x7B0000`, exceeding 8 MB flash budget) -> rejected by `check_mtd_size == -1`.
    6. Legacy `"TRX2"` header -> recognized as `fw_type == 1` by `check_fw_type`.

  Suite C — Hybrid OpenWrt 4.14 `rtw88_8822b.ko` (self-extracted in pure Python from standard XZ
            SquashFS 4.0 inside `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` and relocated via
            MIPS32 ELF `.rel.text` / `.rel.rodata` / `.rel.data`):
    1. `ops->read_efuse` (`rtw8822b_read_efuse` @ `.text+0x0CC4`) on blank `0xFF` PCIe eFuse
       -> proves `efuse.rfe_option` (`rtwdev + 0x3582`) is forced to `6` (Tenda AC10 V1.0).
    2. `ops->read_efuse` on programmed non-`0xFF` eFuse (`0x02`) -> preserves `efuse.rfe_option == 2`.
    3. `ops->set_channel` (`rtw8822b_set_channel` @ `.text+0x375C`) with `rfe_option == 6`, 5 GHz
       Channel 36, 80 MHz (`bw=2`), `2T2R` (`hal.rf_type=3`) -> proves real MIPS32 execution programs:
         - `BB 0x083C == 0x9194B2B9` (`ccapar_cfg[6]` calibration)
         - `BB 0x0CB0[23:0] == 0x177517` & `BB 0x0EB0[23:0] == 0x177517` (Skyworth SE5003L1 5G eFEM)
         - `BB 0x0CB4[15:8] == 0x75`     & `BB 0x0EB4[15:8] == 0x75`     (Skyworth SE5003L1 PAPE/LNA)
"""

from __future__ import annotations

import argparse
import lzma
import struct
import sys
import zlib
from pathlib import Path

from unicorn import (
    UC_ARCH_MIPS,
    UC_HOOK_CODE,
    UC_MODE_LITTLE_ENDIAN,
    UC_MODE_MIPS32,
    Uc,
)
from unicorn.mips_const import (
    UC_MIPS_REG_A0,
    UC_MIPS_REG_A1,
    UC_MIPS_REG_A2,
    UC_MIPS_REG_A3,
    UC_MIPS_REG_PC,
    UC_MIPS_REG_RA,
    UC_MIPS_REG_SP,
    UC_MIPS_REG_T9,
    UC_MIPS_REG_V0,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STOCK_DIR = REPO_ROOT / "01_Stock_Firmware_and_Partitions"
HYBRID_DIR = REPO_ROOT / "02_Compiled_Hybrid_OpenWrt_4.14_Firmware"


# ==============================================================================
# Pure-Python SquashFS 4.0 Reader (Standard XZ + Tenda Custom LZMA2 Container)
# ==============================================================================
def _parse_xz_vli(buf: bytes, offset: int) -> tuple[int, int]:
    res, shift = 0, 0
    while True:
        b = buf[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, offset
        shift += 7


class SquashFS4Reader:
    """Minimal self-contained SquashFS 4.0 extractor supporting standard XZ and Tenda-XZ."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        (
            self.s_magic,
            self.inodes,
            self.mkfs_time,
            self.block_size,
            self.fragments,
            self.compression,
            self.block_log,
            self.flags,
            self.no_ids,
            self.s_major,
            self.s_minor,
            self.root_inode,
            self.bytes_used,
            self.id_table_start,
            self.xattr_id_table_start,
            self.inode_table_start,
            self.directory_table_start,
            self.fragment_table_start,
            self.lookup_table_start,
        ) = struct.unpack_from("<IIIIIHHHHHHQQQQQQQQ", blob, 0)
        if self.s_magic != 0x73717368:
            raise ValueError(f"Invalid SquashFS 4.0 magic: 0x{self.s_magic:08x}")
        self._meta_cache: dict[int, tuple[bytes, int]] = {}
        self._frag_table = self._load_fragment_table()

    def _decompress_chunk(self, raw: bytes) -> bytes:
        if raw[:6] == b"Tenda\x00":
            bh_size = (raw[12] + 1) * 4
            bflags = raw[13]
            curr = 14
            comp_size = None
            if bflags & 0x40:
                comp_size, curr = _parse_xz_vli(raw, curr)
            pstart = 12 + bh_size
            payload = raw[pstart : pstart + comp_size] if comp_size else raw[pstart:]
            dec = lzma.LZMADecompressor(
                format=lzma.FORMAT_RAW,
                filters=[{"id": lzma.FILTER_LZMA2, "dict_size": max(self.block_size, 131072)}],
            )
            return dec.decompress(payload)
        return lzma.decompress(raw, format=lzma.FORMAT_XZ)

    def _read_meta_block(self, disk_pos: int) -> tuple[bytes, int]:
        if disk_pos not in self._meta_cache:
            (hdr,) = struct.unpack_from("<H", self.blob, disk_pos)
            csize = hdr & 0x7FFF
            uncomp = (hdr & 0x8000) != 0
            raw = self.blob[disk_pos + 2 : disk_pos + 2 + csize]
            data = raw if uncomp else self._decompress_chunk(raw)
            self._meta_cache[disk_pos] = (data, disk_pos + 2 + csize)
        return self._meta_cache[disk_pos]

    def _read_meta_bytes(self, table_start: int, block_rel: int, offset: int, length: int) -> bytes:
        pos = table_start + block_rel
        out = bytearray()
        cur_off = offset
        while len(out) < length:
            data, next_pos = self._read_meta_block(pos)
            if cur_off >= len(data):
                cur_off -= len(data)
                pos = next_pos
                continue
            take = min(length - len(out), len(data) - cur_off)
            out.extend(data[cur_off : cur_off + take])
            cur_off = 0
            pos = next_pos
        return bytes(out)

    def _load_fragment_table(self) -> list[tuple[int, int]]:
        if self.fragments == 0 or self.fragment_table_start == 0xFFFFFFFFFFFFFFFF:
            return []
        idx_blocks = (self.fragments * 16 + 8191) // 8192
        ptrs = struct.unpack_from(f"<{idx_blocks}Q", self.blob, self.fragment_table_start)
        raw = bytearray()
        for p in ptrs:
            data, _ = self._read_meta_block(p)
            raw.extend(data)
        return [struct.unpack_from("<QI", raw, i * 16) for i in range(self.fragments)]

    def _read_inode(self, inode_ref: int) -> dict:
        blk_rel = (inode_ref >> 16) & 0xFFFFFFFF
        off = inode_ref & 0xFFFF
        hdr = self._read_meta_bytes(self.inode_table_start, blk_rel, off, 16)
        itype, _, _, _, _, _ = struct.unpack("<HHHHII", hdr)
        if itype == 1:
            body = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 16, 16)
            start_block, _, file_size, offset, _ = struct.unpack("<IIHHI", body)
            return {"type": 1, "start_block": start_block, "file_size": file_size, "offset": offset}
        if itype == 8:
            body = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 16, 24)
            _, file_size, start_block, _, _, offset, _ = struct.unpack("<IIIIHHI", body)
            return {"type": 8, "start_block": start_block, "file_size": file_size, "offset": offset}
        if itype == 2:
            body = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 16, 16)
            blocks_start, fragment, block_offset, file_size = struct.unpack("<IIII", body)
            nblocks = (
                (file_size // self.block_size)
                if fragment != 0xFFFFFFFF
                else ((file_size + self.block_size - 1) // self.block_size)
            )
            bs_raw = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 32, nblocks * 4)
            bsizes = list(struct.unpack(f"<{nblocks}I", bs_raw)) if nblocks else []
            return {
                "type": 2,
                "blocks_start": blocks_start,
                "fragment": fragment,
                "block_offset": block_offset,
                "file_size": file_size,
                "bsizes": bsizes,
            }
        if itype == 9:
            body = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 16, 40)
            blocks_start, file_size, _, _, fragment, block_offset, _ = struct.unpack("<QQQIIII", body)
            nblocks = (
                (file_size // self.block_size)
                if fragment != 0xFFFFFFFF
                else ((file_size + self.block_size - 1) // self.block_size)
            )
            bs_raw = self._read_meta_bytes(self.inode_table_start, blk_rel, off + 56, nblocks * 4)
            bsizes = list(struct.unpack(f"<{nblocks}I", bs_raw)) if nblocks else []
            return {
                "type": 9,
                "blocks_start": blocks_start,
                "fragment": fragment,
                "block_offset": block_offset,
                "file_size": file_size,
                "bsizes": bsizes,
            }
        raise ValueError(f"Unsupported SquashFS inode type: {itype}")

    def _list_dir(self, dir_ino: dict) -> dict[str, tuple[int, int]]:
        total = dir_ino["file_size"] - 3
        raw = self._read_meta_bytes(
            self.directory_table_start, dir_ino["start_block"], dir_ino["offset"], total
        )
        pos = 0
        entries: dict[str, tuple[int, int]] = {}
        while pos < len(raw):
            count, start_block, _ = struct.unpack_from("<III", raw, pos)
            pos += 12
            for _ in range(count + 1):
                off, _, etype, name_size = struct.unpack_from("<HhHH", raw, pos)
                pos += 8
                name = raw[pos : pos + name_size + 1].decode("utf-8", errors="replace")
                pos += name_size + 1
                entries[name] = ((start_block << 16) | off, etype)
        return entries

    def extract_file(self, path: str) -> bytes:
        parts = [p for p in path.strip("/").split("/") if p]
        cur_ref = self.root_inode
        for part in parts:
            ino = self._read_inode(cur_ref)
            listing = self._list_dir(ino)
            if part not in listing:
                raise FileNotFoundError(f"'{part}' not found in SquashFS path '{path}'")
            cur_ref, _ = listing[part]
        ino = self._read_inode(cur_ref)
        out = bytearray()
        disk_pos = ino["blocks_start"]
        for bs in ino["bsizes"]:
            csize = bs & 0xFFFFFF
            uncomp = (bs & (1 << 24)) != 0
            if csize == 0:
                out.extend(b"\x00" * self.block_size)
            else:
                chunk = self.blob[disk_pos : disk_pos + csize]
                out.extend(chunk if uncomp else self._decompress_chunk(chunk))
                disk_pos += csize
        if ino["fragment"] != 0xFFFFFFFF:
            fstart, fsize = self._frag_table[ino["fragment"]]
            fcsize = fsize & 0xFFFFFF
            funcomp = (fsize & (1 << 24)) != 0
            fchunk = self.blob[fstart : fstart + fcsize]
            fdata = fchunk if funcomp else self._decompress_chunk(fchunk)
            rem = ino["file_size"] - len(out)
            out.extend(fdata[ino["block_offset"] : ino["block_offset"] + rem])
        return bytes(out[: ino["file_size"]])


def _find_hybrid_squashfs_offset(factory_bin: bytes) -> int:
    pos = 0
    while True:
        idx = factory_bin.find(b"hsqs", pos)
        if idx < 0:
            raise ValueError("No valid SquashFS 4.0 superblock found in factory.bin")
        if idx + 96 <= len(factory_bin):
            _, inodes, _, block_size, _, comp = struct.unpack_from("<IIIIIH", factory_bin, idx)
            if inodes != 0x454B4146 and block_size in (65536, 131072, 262144, 524288, 1048576) and comp == 4:
                return idx
        pos = idx + 4


def _mips_pa(addr: int) -> int:
    addr &= 0xFFFFFFFF
    if 0x80000000 <= addr < 0xC0000000:
        return addr & 0x1FFFFFFF
    return addr


def _read_cstr(mu: Uc, addr: int, max_len: int = 256) -> str:
    if addr == 0:
        return ""
    raw = bytes(mu.mem_read(_mips_pa(addr), max_len))
    end = raw.find(b"\x00")
    if end >= 0:
        raw = raw[:end]
    return raw.decode("latin1", errors="replace")


def _to_s32(val: int) -> int:
    val &= 0xFFFFFFFF
    return val - 0x100000000 if (val & 0x80000000) else val


# ==============================================================================
# Suite A: Stock Bootloader Stage-2 (`AutoBurn` @ 0x800019D0 & `check_image` @ 0x8000DD10)
# ==============================================================================
MIPS_JR_RA_NOP = struct.pack("<II", 0x03E00008, 0x00000000)


class BooterStage2Harness:
    RETURN_SENTINEL = 0x807FF000
    IMG_RAM_BASE = 0x80800000

    def __init__(self, booter_bytes: bytes) -> None:
        self.booter_bytes = booter_bytes

    def _new_vm(self, flash_init: bytes | None = None):
        mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        # MIPS32 hardware translates KSEG0 (0x80000000..) -> PA 0x00000000.. and KSEG1 (0xB8003000) -> PA 0x18003000
        mu.mem_map(0x00000000, 0x02000000)
        mu.mem_map(0x18003000, 0x1000)
        mu.mem_write(_mips_pa(0x80000000), self.booter_bytes)
        mu.mem_write(_mips_pa(self.RETURN_SENTINEL), b"\x00\x00\x00\x00")

        # Install native `jr $ra; nop` at hooked hardware/console entry points so MIPS branch delay slots execute cleanly
        for stub_va in (0x8000C764, 0x8000C970, 0x80002D80, 0x8000D79C, 0x80008940, 0x80008B8C, 0x80001200):
            mu.mem_write(_mips_pa(stub_va), MIPS_JR_RA_NOP)

        spi_flash = bytearray(b"\xFF" * (8 * 1024 * 1024))
        if flash_init:
            spi_flash[: len(flash_init)] = flash_init
        flash_writes: list[tuple[int, int, int, int]] = []
        console_logs: list[str] = []

        def hook_code(uc: Uc, address: int, size: int, user_data: object) -> None:
            va = address & 0xFFFFFFFF
            if va in (0x8000C764, 0x8000C970):  # prom_printf / dprintf
                fmt = _read_cstr(uc, uc.reg_read(UC_MIPS_REG_A0))
                console_logs.append(fmt.strip())
                uc.reg_write(UC_MIPS_REG_V0, 0)
            elif va in (0x80002D80, 0x8000D79C):  # LED GPIO / watchdog kick
                uc.reg_write(UC_MIPS_REG_V0, 0)
            elif va == 0x80008940:  # spi_flr_image(dst_ram, flash_off, byte_len)
                dst = uc.reg_read(UC_MIPS_REG_A0)
                foff = uc.reg_read(UC_MIPS_REG_A1) & 0x00FFFFFF
                length = uc.reg_read(UC_MIPS_REG_A2)
                uc.mem_write(_mips_pa(dst), bytes(spi_flash[foff : foff + length]))
                uc.reg_write(UC_MIPS_REG_V0, 1)
            elif va == 0x80008B8C:  # spi_flw_image(chip, flash_dst_off, ram_src, byte_len)
                chip = uc.reg_read(UC_MIPS_REG_A0)
                foff = uc.reg_read(UC_MIPS_REG_A1)
                src = uc.reg_read(UC_MIPS_REG_A2)
                length = uc.reg_read(UC_MIPS_REG_A3)
                flash_writes.append((chip, foff, src & 0xFFFFFFFF, length))
                if foff + length <= len(spi_flash):
                    spi_flash[foff : foff + length] = uc.mem_read(_mips_pa(src), length)
                uc.reg_write(UC_MIPS_REG_V0, 1)
            elif va == 0x80001200:  # reboot hook if $a2 == 1
                uc.reg_write(UC_MIPS_REG_V0, 0)
                uc.emu_stop()

        mu.hook_add(UC_HOOK_CODE, hook_code)
        return mu, spi_flash, flash_writes, console_logs

    def run_autoburn_and_check(self, image: bytes, run_check_image: bool = True) -> dict:
        mu, spi_flash, flash_writes, console_logs = self._new_vm()
        mu.mem_write(_mips_pa(self.IMG_RAM_BASE), image)
        mu.reg_write(UC_MIPS_REG_SP, 0x80700000)
        mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
        mu.reg_write(UC_MIPS_REG_A0, self.IMG_RAM_BASE)
        mu.reg_write(UC_MIPS_REG_A1, len(image))
        mu.reg_write(UC_MIPS_REG_A2, 0)  # return cleanly without calling reset
        mu.emu_start(0x800019D0, self.RETURN_SENTINEL)
        autoburn_ret = _to_s32(mu.reg_read(UC_MIPS_REG_V0))

        check_ret = None
        if run_check_image:
            sys_hdr_buf = 0x80710000
            root_hdr_buf = 0x80710100
            mu.reg_write(UC_MIPS_REG_SP, 0x80700000)
            mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
            mu.reg_write(UC_MIPS_REG_A0, sys_hdr_buf)
            mu.reg_write(UC_MIPS_REG_A1, root_hdr_buf)
            mu.emu_start(0x8000DD10, self.RETURN_SENTINEL)
            check_ret = _to_s32(mu.reg_read(UC_MIPS_REG_V0))

        return {
            "autoburn_ret": autoburn_ret,
            "check_image_ret": check_ret,
            "flash_writes": flash_writes,
            "spi_flash": spi_flash,
            "logs": console_logs,
        }


# ==============================================================================
# Suite B: Stock `/lib/libcommon.so` WebUI Upgrade Validators
# ==============================================================================
class LibcommonHarness:
    BASE = 0x10000000
    STACK_TOP = 0x12000000
    RETURN_SENTINEL = 0x120FF000
    ARG_STR_ADDR = 0x12100000
    OUT_BUF_ADDR = 0x12101000
    ERRNO_ADDR = 0x12102000
    HEAP_BASE = 0x12200000

    def __init__(self, elf_bytes: bytes) -> None:
        self.elf = elf_bytes
        self.stubs = self._parse_dynsym_stubs()

    def _parse_dynsym_stubs(self) -> dict[int, str]:
        _, e_shoff, _, _, _, _, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            "<IIIHHHHHH", self.elf, 28
        )
        shdrs = [
            struct.unpack_from("<IIIIIIIIII", self.elf, e_shoff + i * e_shentsize)
            for i in range(e_shnum)
        ]
        shstr = self.elf[shdrs[e_shstrndx][4] : shdrs[e_shstrndx][4] + shdrs[e_shstrndx][5]]
        sec_names = [shstr[s[0] : shstr.find(b"\x00", s[0])].decode() for s in shdrs]
        stubs: dict[int, str] = {}
        for i, s in enumerate(shdrs):
            if sec_names[i] == ".dynsym":
                str_s = shdrs[s[6]]
                strtab = self.elf[str_s[4] : str_s[4] + str_s[5]]
                for j in range(s[5] // 16):
                    st_name, st_val, _, _, _, st_shndx = struct.unpack_from(
                        "<IIIBBH", self.elf, s[4] + j * 16
                    )
                    name = strtab[st_name : strtab.find(b"\x00", st_name)].decode()
                    if st_shndx == 0 and st_val != 0 and name:
                        stubs[self.BASE + st_val] = name
        return stubs

    def call_validator(self, func_rva: int, fw_blob: bytes, pass_out_buf: bool = False) -> tuple[int, str]:
        mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(self.BASE, 0x00100000)
        mu.mem_map(0x11F00000, 0x01800000)

        # Load PT_LOAD segments
        e_phoff, _, _, _, e_phentsize, e_phnum = struct.unpack_from("<IIIHHH", self.elf, 28)
        for i in range(e_phnum):
            pt, poff, pvaddr, _, pfilesz, _ = struct.unpack_from(
                "<IIIIII", self.elf, e_phoff + i * e_phentsize
            )
            if pt == 1 and pfilesz > 0:
                mu.mem_write(self.BASE + pvaddr, self.elf[poff : poff + pfilesz])

        # Relocate MIPS GOT (.got @ vaddr 0x34890, size 0x2c4)
        got_vaddr = 0x34890
        got_size = 0x2C4
        for off in range(8, got_size, 4):
            (val,) = struct.unpack_from("<I", mu.mem_read(self.BASE + got_vaddr + off, 4), 0)
            if val != 0:
                mu.mem_write(self.BASE + got_vaddr + off, struct.pack("<I", (self.BASE + val) & 0xFFFFFFFF))

        # Patch `.MIPS.stubs` external entries with `jr $ra; nop`
        for stub_va in self.stubs:
            mu.mem_write(stub_va, MIPS_JR_RA_NOP)

        mu.mem_write(self.RETURN_SENTINEL, b"\x00\x00\x00\x00")
        vfs: dict[str, bytes] = {"/tmp/fw.bin": fw_blob}
        fds: dict[int, list] = {}
        next_fd = [10]
        heap_ptr = [self.HEAP_BASE]

        def _ret(uc: Uc, val: int) -> None:
            uc.reg_write(UC_MIPS_REG_V0, val & 0xFFFFFFFF)

        def _write_mips_stat(uc: Uc, stat_ptr: int, file_len: int) -> None:
            # Linux MIPS32 `struct stat`: st_mode @ +16 (u32), st_size @ +48 (off_t i32)
            buf = bytearray(144)
            struct.pack_into("<I", buf, 16, 0o100644)
            struct.pack_into("<I", buf, 48, file_len)
            uc.mem_write(stat_ptr, bytes(buf))

        def hook_stubs(uc: Uc, address: int, size: int, user_data: object) -> None:
            fn = self.stubs.get(address)
            if fn is None:
                return
            a0 = uc.reg_read(UC_MIPS_REG_A0)
            a1 = uc.reg_read(UC_MIPS_REG_A1)
            a2 = uc.reg_read(UC_MIPS_REG_A2)
            a3 = uc.reg_read(UC_MIPS_REG_A3)

            if fn == "memset":
                uc.mem_write(a0, bytes([a1 & 0xFF]) * a2)
                _ret(uc, a0)
            elif fn == "bzero":
                uc.mem_write(a0, b"\x00" * a1)
                _ret(uc, 0)
            elif fn == "memcpy":
                uc.mem_write(a0, bytes(uc.mem_read(a1, a2)))
                _ret(uc, a0)
            elif fn == "memcmp":
                b0 = bytes(uc.mem_read(a0, a2))
                b1 = bytes(uc.mem_read(a1, a2))
                _ret(uc, 0 if b0 == b1 else (-1 if b0 < b1 else 1))
            elif fn == "strlen":
                _ret(uc, len(_read_cstr(uc, a0)))
            elif fn == "strcmp":
                s0, s1 = _read_cstr(uc, a0), _read_cstr(uc, a1)
                _ret(uc, 0 if s0 == s1 else (-1 if s0 < s1 else 1))
            elif fn == "strncmp":
                s0, s1 = _read_cstr(uc, a0, a2)[:a2], _read_cstr(uc, a1, a2)[:a2]
                _ret(uc, 0 if s0 == s1 else (-1 if s0 < s1 else 1))
            elif fn == "strcpy":
                s = _read_cstr(uc, a1).encode("latin1") + b"\x00"
                uc.mem_write(a0, s)
                _ret(uc, a0)
            elif fn == "strncpy":
                s = _read_cstr(uc, a1, a2).encode("latin1")[:a2]
                s = s + b"\x00" * max(0, a2 - len(s))
                uc.mem_write(a0, s)
                _ret(uc, a0)
            elif fn in ("ntohl", "htonl"):
                _ret(uc, struct.unpack("<I", struct.pack(">I", a0 & 0xFFFFFFFF))[0])
            elif fn == "htons":
                _ret(uc, struct.unpack("<H", struct.pack(">H", a0 & 0xFFFF))[0])
            elif fn == "crc32":
                if a1 == 0:
                    _ret(uc, 0)
                else:
                    data = bytes(uc.mem_read(a1, a2))
                    _ret(uc, zlib.crc32(data, a0 & 0xFFFFFFFF) & 0xFFFFFFFF)
            elif fn == "open":
                path = _read_cstr(uc, a0)
                if path not in vfs:
                    _ret(uc, -1)
                else:
                    fd = next_fd[0]
                    next_fd[0] += 1
                    fds[fd] = [path, 0]
                    _ret(uc, fd)
            elif fn == "fopen":
                path = _read_cstr(uc, a0)
                if path not in vfs:
                    _ret(uc, 0)
                else:
                    fd = next_fd[0]
                    next_fd[0] += 1
                    fds[fd] = [path, 0]
                    _ret(uc, fd)
            elif fn == "read":
                if a0 not in fds:
                    _ret(uc, -1)
                else:
                    path, pos = fds[a0]
                    chunk = vfs[path][pos : pos + a2]
                    if chunk:
                        uc.mem_write(a1, chunk)
                    fds[a0][1] = pos + len(chunk)
                    _ret(uc, len(chunk))
            elif fn == "fread":
                # size_t fread(void *ptr=a0, size_t size=a1, size_t nmemb=a2, FILE *stream=a3)
                if a3 not in fds or a1 == 0:
                    _ret(uc, 0)
                else:
                    path, pos = fds[a3]
                    total = a1 * a2
                    chunk = vfs[path][pos : pos + total]
                    nitems = len(chunk) // a1
                    take = nitems * a1
                    if take > 0:
                        uc.mem_write(a0, chunk[:take])
                    fds[a3][1] = pos + take
                    _ret(uc, nitems)
            elif fn == "lseek":
                if a0 not in fds:
                    _ret(uc, -1)
                else:
                    path, pos = fds[a0]
                    off = _to_s32(a1)
                    new_pos = off if a2 == 0 else (pos + off if a2 == 1 else len(vfs[path]) + off)
                    fds[a0][1] = max(0, new_pos)
                    _ret(uc, fds[a0][1])
            elif fn == "fseek":
                if a0 not in fds:
                    _ret(uc, -1)
                else:
                    path, pos = fds[a0]
                    off = _to_s32(a1)
                    new_pos = off if a2 == 0 else (pos + off if a2 == 1 else len(vfs[path]) + off)
                    fds[a0][1] = max(0, new_pos)
                    _ret(uc, 0)
            elif fn in ("close", "fclose"):
                fds.pop(a0, None)
                _ret(uc, 0)
            elif fn == "stat":
                path = _read_cstr(uc, a0)
                if path not in vfs:
                    _ret(uc, -1)
                else:
                    _write_mips_stat(uc, a1, len(vfs[path]))
                    _ret(uc, 0)
            elif fn == "fstat":
                if a0 not in fds:
                    _ret(uc, -1)
                else:
                    path, _ = fds[a0]
                    _write_mips_stat(uc, a1, len(vfs[path]))
                    _ret(uc, 0)
            elif fn in ("malloc", "calloc"):
                sz = (a0 * a1) if fn == "calloc" else a0
                sz = max(16, (sz + 15) & ~15)
                ptr = heap_ptr[0]
                heap_ptr[0] += sz
                uc.mem_write(ptr, b"\x00" * sz)
                _ret(uc, ptr)
            elif fn == "free":
                _ret(uc, 0)
            elif fn == "__errno_location":
                _ret(uc, self.ERRNO_ADDR)
            elif fn in ("printf", "fprintf", "puts", "fputs", "perror", "fflush"):
                _ret(uc, 0)
            elif fn in ("sprintf", "snprintf"):
                # Copy format string as message summary for diagnostic verification
                fmt = _read_cstr(uc, a1 if fn == "sprintf" else a2)
                raw = fmt.encode("latin1")[:120] + b"\x00"
                uc.mem_write(a0, raw)
                _ret(uc, len(raw) - 1)
            else:
                _ret(uc, 0)

        mu.hook_add(UC_HOOK_CODE, hook_stubs)
        mu.mem_write(self.ARG_STR_ADDR, b"/tmp/fw.bin\x00")
        mu.mem_write(self.OUT_BUF_ADDR, b"\x00" * 256)

        entry = self.BASE + func_rva
        mu.reg_write(UC_MIPS_REG_SP, self.STACK_TOP)
        mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
        mu.reg_write(UC_MIPS_REG_T9, entry)
        mu.reg_write(UC_MIPS_REG_A0, self.ARG_STR_ADDR)
        if pass_out_buf:
            mu.reg_write(UC_MIPS_REG_A1, self.OUT_BUF_ADDR)

        mu.emu_start(entry, self.RETURN_SENTINEL)
        ret = _to_s32(mu.reg_read(UC_MIPS_REG_V0))
        out_msg = _read_cstr(mu, self.OUT_BUF_ADDR) if pass_out_buf else ""
        return ret, out_msg


# ==============================================================================
# Suite C: Relocated Hybrid `rtw88_8822b.ko` (`read_efuse` & `set_channel`)
# ==============================================================================
class Rtw8822bKoHarness:
    MOD_BASE = 0x20000000
    EXT_STUB_BASE = 0x20300000
    HCI_STUB_BASE = 0x20310000
    RTWDEV_ADDR = 0x20400000
    HCI_OPS_ADDR = 0x20410000
    EFUSE_MAP_ADDR = 0x20411000
    STACK_TOP = 0x205F0000
    RETURN_SENTINEL = 0x205FF000

    R_MIPS_32 = 2
    R_MIPS_26 = 4
    R_MIPS_HI16 = 5
    R_MIPS_LO16 = 6

    def __init__(self, ko_bytes: bytes) -> None:
        self.ko = ko_bytes
        self.sec_addrs: dict[int, int] = {}
        self.ext_stubs: dict[int, str] = {}
        self.ops_ptrs: list[int] = []
        self.relocated_image = self._relocate_ko()

    def _relocate_ko(self) -> bytearray:
        _, e_shoff, _, _, _, _, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            "<IIIHHHHHH", self.ko, 28
        )
        shdrs = [
            struct.unpack_from("<IIIIIIIIII", self.ko, e_shoff + i * e_shentsize)
            for i in range(e_shnum)
        ]
        shstr = self.ko[shdrs[e_shstrndx][4] : shdrs[e_shstrndx][4] + shdrs[e_shstrndx][5]]
        sec_names = [shstr[s[0] : shstr.find(b"\x00", s[0])].decode() for s in shdrs]

        mem = bytearray(0x00100000)
        cursor = 0
        for i, s in enumerate(shdrs):
            sh_type, sh_flags, _, sh_offset, sh_size, _, _, sh_addralign, _ = s[1:]
            if (sh_flags & 0x2) and sh_size > 0:  # SHF_ALLOC
                align = max(16, sh_addralign)
                cursor = (cursor + align - 1) & ~(align - 1)
                self.sec_addrs[i] = self.MOD_BASE + cursor
                if sh_type != 8:  # !SHT_NOBITS
                    mem[cursor : cursor + sh_size] = self.ko[sh_offset : sh_offset + sh_size]
                cursor += sh_size

        # Parse .symtab
        sym_idx = sec_names.index(".symtab")
        sym_s = shdrs[sym_idx]
        str_s = shdrs[sym_s[6]]
        strtab = self.ko[str_s[4] : str_s[4] + str_s[5]]
        syms: list[tuple[str, int, int]] = []
        next_stub = self.EXT_STUB_BASE
        sym_addrs: list[int] = []
        for j in range(sym_s[5] // 16):
            st_name, st_val, _, _, _, st_shndx = struct.unpack_from(
                "<IIIBBH", self.ko, sym_s[4] + j * 16
            )
            name = strtab[st_name : strtab.find(b"\x00", st_name)].decode()
            syms.append((name, st_val, st_shndx))
            if st_shndx == 0:
                if name:
                    self.ext_stubs[next_stub] = name
                    sym_addrs.append(next_stub)
                    next_stub += 8
                else:
                    sym_addrs.append(0)
            elif st_shndx in self.sec_addrs:
                sym_addrs.append(self.sec_addrs[st_shndx] + st_val)
            else:
                sym_addrs.append(st_val)

        # Apply MIPS32 REL relocations (handling paired R_MIPS_HI16 + R_MIPS_LO16)
        for i, s in enumerate(shdrs):
            if s[1] != 9:  # SHT_REL
                continue
            target_sec = s[7]
            if target_sec not in self.sec_addrs:
                continue
            t_base = self.sec_addrs[target_sec] - self.MOD_BASE
            rels = [
                struct.unpack_from("<II", self.ko, s[4] + k)
                for k in range(0, s[5], 8)
            ]
            pending_hi: list[tuple[int, int]] = []
            for r_off, r_info in rels:
                s_i = r_info >> 8
                rtype = r_info & 0xFF
                S = sym_addrs[s_i]
                pos = t_base + r_off
                (insn,) = struct.unpack_from("<I", mem, pos)

                if rtype == self.R_MIPS_32:
                    val = (S + insn) & 0xFFFFFFFF
                    struct.pack_into("<I", mem, pos, val)
                elif rtype == self.R_MIPS_26:
                    addend = (insn & 0x03FFFFFF) << 2
                    target = (S + addend) & 0xFFFFFFFF
                    insn = (insn & 0xFC000000) | ((target >> 2) & 0x03FFFFFF)
                    struct.pack_into("<I", mem, pos, insn)
                elif rtype == self.R_MIPS_HI16:
                    pending_hi.append((pos, insn & 0xFFFF))
                elif rtype == self.R_MIPS_LO16:
                    lo = insn & 0xFFFF
                    lo_signed = lo - 0x10000 if (lo & 0x8000) else lo
                    for hi_pos, hi_imm in pending_hi:
                        ahl = (hi_imm << 16) + lo_signed
                        v = (S + ahl) & 0xFFFFFFFF
                        new_hi = ((v + 0x8000) >> 16) & 0xFFFF
                        (hi_insn,) = struct.unpack_from("<I", mem, hi_pos)
                        struct.pack_into("<I", mem, hi_pos, (hi_insn & 0xFFFF0000) | new_hi)
                    pending_hi.clear()
                    # Recompute LO16 using AHL from last HI16 if present, else signed lo
                    v_lo = (S + lo_signed) & 0xFFFF
                    struct.pack_into("<I", mem, pos, (insn & 0xFFFF0000) | v_lo)

        # Read relocated `rtw8822b_hw_spec.ops` from `.data + 0x00`
        data_idx = sec_names.index(".data")
        data_base = self.sec_addrs[data_idx] - self.MOD_BASE
        (ops_va,) = struct.unpack_from("<I", mem, data_base)
        ops_rel = ops_va - self.MOD_BASE
        self.ops_ptrs = list(struct.unpack_from("<28I", mem, ops_rel))
        return mem

    def _new_vm(self):
        mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(self.MOD_BASE, 0x00600000)
        mu.mem_write(self.MOD_BASE, bytes(self.relocated_image))
        mu.mem_write(self.RETURN_SENTINEL, b"\x00\x00\x00\x00")

        # Populate `rtwdev->hci.ops` (`*(rtwdev + 0x08)`) function pointers:
        # +0x28: read8, +0x2c: read16, +0x30: read32, +0x34: write8, +0x38: write16, +0x3c: write32
        hci_stubs = {
            0x28: ("read8", self.HCI_STUB_BASE + 0x00),
            0x2C: ("read16", self.HCI_STUB_BASE + 0x08),
            0x30: ("read32", self.HCI_STUB_BASE + 0x10),
            0x34: ("write8", self.HCI_STUB_BASE + 0x18),
            0x38: ("write16", self.HCI_STUB_BASE + 0x20),
            0x3C: ("write32", self.HCI_STUB_BASE + 0x28),
        }
        addr_to_hci = {stub: name for _, (name, stub) in hci_stubs.items()}
        for off, (_, stub) in hci_stubs.items():
            mu.mem_write(self.HCI_OPS_ADDR + off, struct.pack("<I", stub))
            mu.mem_write(stub, MIPS_JR_RA_NOP)
        for stub_va in self.ext_stubs:
            mu.mem_write(stub_va, MIPS_JR_RA_NOP)
        mu.mem_write(self.RTWDEV_ADDR + 0x08, struct.pack("<I", self.HCI_OPS_ADDR))

        bb_regs: dict[int, int] = {}
        reg_writes: list[tuple[str, int, int]] = []
        kernel_calls: list[str] = []

        def hook_code(uc: Uc, address: int, size: int, user_data: object) -> None:
            if address in addr_to_hci:
                op = addr_to_hci[address]
                reg = uc.reg_read(UC_MIPS_REG_A1) & 0xFFFF
                val = uc.reg_read(UC_MIPS_REG_A2) & 0xFFFFFFFF
                if op.startswith("read"):
                    cur = bb_regs.get(reg, 0)
                    uc.reg_write(UC_MIPS_REG_V0, cur)
                else:
                    if op == "write8":
                        aligned = reg & ~3
                        shift = (reg & 3) * 8
                        old = bb_regs.get(aligned, 0)
                        bb_regs[aligned] = (old & ~(0xFF << shift)) | ((val & 0xFF) << shift)
                        bb_regs[reg] = val & 0xFF
                    elif op == "write16":
                        bb_regs[reg] = val & 0xFFFF
                    else:
                        bb_regs[reg] = val
                    reg_writes.append((op, reg, val))
                    uc.reg_write(UC_MIPS_REG_V0, 0)
            elif address in self.ext_stubs:
                fn = self.ext_stubs[address]
                kernel_calls.append(fn)
                if fn == "printk":
                    fmt = _read_cstr(uc, uc.reg_read(UC_MIPS_REG_A0))
                    kernel_calls.append(f"printk:{fmt.strip()}")
                uc.reg_write(UC_MIPS_REG_V0, 0)

        mu.hook_add(UC_HOOK_CODE, hook_code)
        return mu, bb_regs, reg_writes, kernel_calls

    def run_read_efuse(self, efuse_bytes: bytes) -> tuple[int, int, list[str]]:
        mu, _, _, kernel_calls = self._new_vm()
        mu.mem_write(self.EFUSE_MAP_ADDR, efuse_bytes)
        read_efuse_va = self.ops_ptrs[2]  # ops->read_efuse
        mu.reg_write(UC_MIPS_REG_SP, self.STACK_TOP)
        mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
        mu.reg_write(UC_MIPS_REG_A0, self.RTWDEV_ADDR)
        mu.reg_write(UC_MIPS_REG_A1, self.EFUSE_MAP_ADDR)
        mu.emu_start(read_efuse_va, self.RETURN_SENTINEL)
        ret = _to_s32(mu.reg_read(UC_MIPS_REG_V0))
        rfe_opt = mu.mem_read(self.RTWDEV_ADDR + 0x3582, 1)[0]
        return ret, rfe_opt, kernel_calls

    def run_set_channel_rfe6(self, channel: int = 36, bw: int = 2, primary_ch_idx: int = 1) -> tuple[dict[int, int], list[str]]:
        mu, bb_regs, _, kernel_calls = self._new_vm()
        # First populate efuse via real `ops->read_efuse` on blank 0xFF map
        mu.mem_write(self.EFUSE_MAP_ADDR, b"\xFF" * 512)
        mu.reg_write(UC_MIPS_REG_SP, self.STACK_TOP)
        mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
        mu.reg_write(UC_MIPS_REG_A0, self.RTWDEV_ADDR)
        mu.reg_write(UC_MIPS_REG_A1, self.EFUSE_MAP_ADDR)
        mu.emu_start(self.ops_ptrs[2], self.RETURN_SENTINEL)

        # Configure `rtwdev->hal` for 2T2R (rf_type = RF_2T2R = 3 at +0x38, rf_path_num = 2 at +0x39, cut_version = 1 at +0x28)
        mu.mem_write(self.RTWDEV_ADDR + 0x28, b"\x01")
        mu.mem_write(self.RTWDEV_ADDR + 0x38, struct.pack("<BB", 3, 2))
        mu.mem_write(self.RTWDEV_ADDR + 0x3C, struct.pack("<II", 3, 3))  # antenna_tx, antenna_rx = BB_PATH_AB

        # Seed initial BB register values so bitmask updates (`0xff000000`, `~0xff00`) are observable
        bb_regs[0x0CB0] = 0xAA000000
        bb_regs[0x0EB0] = 0x55000000
        bb_regs[0x0CB4] = 0x12340056
        bb_regs[0x0EB4] = 0x9ABC00DE

        # Execute real `ops->set_channel(rtwdev, channel, bw, primary_chan_idx)`
        set_channel_va = self.ops_ptrs[4]
        mu.reg_write(UC_MIPS_REG_SP, self.STACK_TOP)
        mu.reg_write(UC_MIPS_REG_RA, self.RETURN_SENTINEL)
        mu.reg_write(UC_MIPS_REG_A0, self.RTWDEV_ADDR)
        mu.reg_write(UC_MIPS_REG_A1, channel)
        mu.reg_write(UC_MIPS_REG_A2, bw)
        mu.reg_write(UC_MIPS_REG_A3, primary_ch_idx)
        mu.emu_start(set_channel_va, self.RETURN_SENTINEL)
        return bb_regs, kernel_calls


# ==============================================================================
# Runner & Assertions
# ==============================================================================
class VerificationRunner:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, cond: bool, msg: str) -> None:
        if cond:
            self.passed += 1
            print(f"  [PASS] {msg}")
        else:
            self.failed += 1
            print(f"  [FAIL] {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unicorn MIPS32r2 CPU emulation verifier for Tenda AC10 V1.0 firmware & RE claims."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    stock_dir = args.repo_root / "01_Stock_Firmware_and_Partitions"
    hybrid_dir = args.repo_root / "02_Compiled_Hybrid_OpenWrt_4.14_Firmware"

    booter_bin = (stock_dir / "booter_stage2_v3.4.11B.9_0x80000000.bin").read_bytes()
    stock_recovery = (stock_dir / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin").read_bytes()
    stock_sqfs = (stock_dir / "rootfs_squashfs_tenda_xz_0x23BC12.bin").read_bytes()
    factory_bin = (hybrid_dir / "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin").read_bytes()
    webupgrade_bin = (hybrid_dir / "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin").read_bytes()

    vr = VerificationRunner()
    print("=" * 84)
    print("  TENDA AC10 V1.0 — UNICORN MIPS32EL CPU EMULATION VERIFICATION SUITE")
    print("=" * 84)

    # ------------------------------------------------------------------
    # Suite A: Stock Bootloader Stage-2 (`AutoBurn` + `check_image`)
    # ------------------------------------------------------------------
    print("\n[Suite A] Stock Bootloader Stage-2 (`AutoBurn` @ 0x800019D0 & `check_image` @ 0x8000DD10)")
    booter = BooterStage2Harness(booter_bin)

    res_factory = booter.run_autoburn_and_check(factory_bin)
    vr.check(
        res_factory["autoburn_ret"] == 0
        and res_factory["flash_writes"] == [(0, 0x00030000, BooterStage2Harness.IMG_RAM_BASE, len(factory_bin))]
        and res_factory["check_image_ret"] == 1,
        f"AutoBurn + check_image on factory.bin ({len(factory_bin):,} B): burned to SPI 0x030000, cold-boot check_image == 1",
    )

    res_web = booter.run_autoburn_and_check(webupgrade_bin)
    vr.check(
        res_web["autoburn_ret"] == 0
        and len(res_web["flash_writes"]) == 1
        and res_web["flash_writes"][0]
        == (0, 0x00030000, BooterStage2Harness.IMG_RAM_BASE + 0x40, len(factory_bin))
        and res_web["spi_flash"][0x030000 : 0x030000 + len(factory_bin)] == factory_bin
        and res_web["check_image_ret"] == 1,
        "AutoBurn @ 0x80001B84 natively skips 64-byte 0x27051956 header on webupgrade.bin -> burns identical factory.bin to 0x030000",
    )

    res_stock = booter.run_autoburn_and_check(stock_recovery)
    vr.check(
        res_stock["autoburn_ret"] == 0
        and res_stock["flash_writes"][0][1] == 0x00030000
        and res_stock["flash_writes"][1][1] == 0x00230000
        and res_stock["flash_writes"][2][1] == 0x00240000
        and res_stock["spi_flash"][0x23BC12 : 0x23BC12 + 4] == b"hsqs"
        and res_stock["check_image_ret"] == 2,
        "AutoBurn + check_image on Tenda_AC10_V1_Stock_TFTP_Recovery.bin (cr6c + hsqs): burns 0x030000 + RMW 0x23BC12, check_image == 2",
    )

    corrupted_factory = bytearray(factory_bin)
    corrupted_factory[0x100] ^= 0xFF
    res_corrupt = booter.run_autoburn_and_check(bytes(corrupted_factory), run_check_image=False)
    vr.check(
        res_corrupt["autoburn_ret"] == -2 and len(res_corrupt["flash_writes"]) == 0,
        "AutoBurn rejects 1-byte corrupted cs6c payload (ret == -2, 0 SPI flash writes)",
    )

    # Construct minimal valid 2-segment `cs6c + hsqs` image to prove the 0x80001C2C flash-0x0 brick hazard
    seg1_body = b"\xAA\x55" * 16
    seg1_sum = sum((seg1_body[i] << 8) | seg1_body[i + 1] for i in range(0, len(seg1_body), 2)) & 0xFFFF
    seg1_csum = struct.pack(">H", (-seg1_sum) & 0xFFFF)
    seg1_cs6c = b"cs6c" + struct.pack(">III", 0x80000000, 0x00030000, len(seg1_body) + 2) + seg1_body + seg1_csum
    seg2_body = b"hsqs" + b"\x00" * 27
    seg2_csum = bytes([(-sum(seg2_body)) & 0xFF])
    seg2_hsqs = b"hsqs" + struct.pack(">III", 0x00000000, 0x00200000, len(seg2_body) + 1) + seg2_body + seg2_csum
    res_brick = booter.run_autoburn_and_check(seg1_cs6c + seg2_hsqs, run_check_image=False)
    vr.check(
        len(res_brick["flash_writes"]) >= 2
        and res_brick["flash_writes"][0][1] == 0x00030000
        and res_brick["flash_writes"][1][1] == 0x00000000,
        "Adversarial 2-segment `cs6c + hsqs` reproducer: AutoBurn @ 0x80001C2C writes segment 2 to SPI 0x00000000 (mtd0 brick proven!)",
    )

    # ------------------------------------------------------------------
    # Suite B: Stock `/lib/libcommon.so` WebUI Upgrade Validators
    # ------------------------------------------------------------------
    print("\n[Suite B] Stock `/lib/libcommon.so` WebUI Validators (Self-Extracted from Tenda-XZ SquashFS)")
    libcommon_elf = SquashFS4Reader(stock_sqfs).extract_file("lib/libcommon.so")
    vr.check(
        len(libcommon_elf) == 157_056 and libcommon_elf[:4] == b"\x7fELF",
        f"Self-extracted stock /lib/libcommon.so from Tenda-XZ SquashFS ({len(libcommon_elf):,} B ELF32 MIPS)",
    )
    libc_h = LibcommonHarness(libcommon_elf)

    fw_type, _ = libc_h.call_validator(0x10AFC, webupgrade_bin)
    mtd_ok, _ = libc_h.call_validator(0x11CFC, webupgrade_bin, pass_out_buf=True)
    crc_ok, _ = libc_h.call_validator(0x11894, webupgrade_bin, pass_out_buf=True)
    valid_ok, _ = libc_h.call_validator(0x122F4, webupgrade_bin, pass_out_buf=True)
    vr.check(
        fw_type == 2 and mtd_ok == 1 and crc_ok == 1 and valid_ok == 1,
        f"Hybrid webupgrade.bin passes all 4 stock WebUI validators (type={fw_type}, mtd={mtd_ok}, crc={crc_ok}, valid={valid_ok})",
    )

    raw_type, _ = libc_h.call_validator(0x10AFC, factory_bin)
    vr.check(
        raw_type == -1,
        f"Raw factory.bin (no 64-byte 0x27051956 header) rejected by WebUI check_fw_type (ret == {raw_type})",
    )

    bad_crc_web = bytearray(webupgrade_bin)
    bad_crc_web[0x80] ^= 0x55
    bad_crc_ret, _ = libc_h.call_validator(0x11894, bytes(bad_crc_web), pass_out_buf=True)
    vr.check(
        bad_crc_ret == -1,
        f"Corrupted payload CRC32 rejected by WebUI check_fw_crc (ret == {bad_crc_ret})",
    )

    bad_ver_web = bytearray(webupgrade_bin)
    # Offset 48..52 in Tenda 64-byte image_header is `ih_ver` (must equal 0x00030028 BE for AC10 V1.0)
    struct.pack_into(">I", bad_ver_web, 48, 0x00030099)
    bad_ver_web[4:8] = b"\x00\x00\x00\x00"
    hdr_crc = zlib.crc32(bytes(bad_ver_web[:64])) & 0xFFFFFFFF
    struct.pack_into(">I", bad_ver_web, 4, hdr_crc)
    bad_ver_ret, bad_ver_msg = libc_h.call_validator(0x122F4, bytes(bad_ver_web), pass_out_buf=True)
    vr.check(
        bad_ver_ret == -1 and "Format error" in bad_ver_msg,
        f"Foreign model ih_ver != 0x00030028 rejected by check_fw_valid (ret == {bad_ver_ret}, msg='{bad_ver_msg}')",
    )

    oversized_hdr = bytearray(webupgrade_bin[:64])
    struct.pack_into(">I", oversized_hdr, 12, 0x007C0000)  # > 0x7B0000 8MB flash partition budget
    oversized_blob = bytes(oversized_hdr) + b"\x00" * 256
    # check_mtd_size inspects file stat / header size against flash budget
    oversized_full = bytes(oversized_hdr) + b"\xFF" * 0x007C0000
    over_ret, _ = libc_h.call_validator(0x11CFC, oversized_full, pass_out_buf=True)
    vr.check(
        over_ret == -1,
        f"Oversized >= 0x7B0000 (16MB AC10U-sized) image rejected by check_mtd_size (ret == {over_ret})",
    )

    trx2_blob = b"TRX2" + struct.pack("<III", 256, 0, 0x00020000) + b"\x00" * 240
    trx2_type, _ = libc_h.call_validator(0x10AFC, trx2_blob)
    vr.check(
        trx2_type == 1,
        f"Legacy TRX2 magic recognized as fw_type == {trx2_type} by check_fw_type",
    )

    # ------------------------------------------------------------------
    # Suite C: Relocated Hybrid `rtw88_8822b.ko` (`RFE Type 6` eFuse & eFEM)
    # ------------------------------------------------------------------
    print("\n[Suite C] Relocated Hybrid `rtw88_8822b.ko` (`RFE Type 6` eFuse Override & Skyworth SE5003L1 eFEM)")
    hyb_sq_off = _find_hybrid_squashfs_offset(factory_bin)
    ko_elf = SquashFS4Reader(factory_bin[hyb_sq_off:]).extract_file("lib/modules/4.14.187/rtw88_8822b.ko")
    vr.check(
        len(ko_elf) > 200_000 and ko_elf[:4] == b"\x7fELF",
        f"Self-extracted Hybrid rtw88_8822b.ko from factory.bin SquashFS @ 0x{hyb_sq_off:x} ({len(ko_elf):,} B ELF32)",
    )
    rtw_h = Rtw8822bKoHarness(ko_elf)

    ef_ret, rfe_blank, kcalls_blank = rtw_h.run_read_efuse(b"\xFF" * 512)
    vr.check(
        ef_ret == 0
        and rfe_blank == 6
        and any("RFE Type 6" in c for c in kcalls_blank),
        f"ops->read_efuse on blank 0xFF PCIe eFuse forces efuse.rfe_option == {rfe_blank} with kernel log confirmation",
    )

    ef_prog = bytearray(b"\xFF" * 512)
    ef_prog[0xCA] = 0x02
    ef_ret2, rfe_prog, _ = rtw_h.run_read_efuse(bytes(ef_prog))
    vr.check(
        ef_ret2 == 0 and rfe_prog == 2,
        f"ops->read_efuse on programmed eFuse (0xCA=0x02) preserves efuse.rfe_option == {rfe_prog}",
    )

    bb_regs, kcalls_ch36 = rtw_h.run_set_channel_rfe6(channel=36, bw=2, primary_ch_idx=1)
    vr.check(
        "warn_slowpath_fmt" not in kcalls_ch36
        and bb_regs.get(0x083C) == 0x9194B2B9
        and (bb_regs.get(0x0CB0, 0) & 0x00FFFFFF) == 0x00177517
        and (bb_regs.get(0x0EB0, 0) & 0x00FFFFFF) == 0x00177517
        and ((bb_regs.get(0x0CB4, 0) >> 8) & 0xFF) == 0x75
        and ((bb_regs.get(0x0EB4, 0) >> 8) & 0xFF) == 0x75,
        (
            f"ops->set_channel(ch=36, 80MHz, RFE=6): BB 0x83C=0x{bb_regs.get(0x083C, 0):08x}, "
            f"0xCB0=0x{bb_regs.get(0x0CB0, 0):08x}, 0xEB0=0x{bb_regs.get(0x0EB0, 0):08x}, "
            f"0xCB4=0x{bb_regs.get(0x0CB4, 0):08x}, 0xEB4=0x{bb_regs.get(0x0EB4, 0):08x}"
        ),
    )

    print("\n" + "=" * 84)
    print(f"  UNICORN MIPS32 VERIFICATION SUMMARY: {vr.passed} PASSED, {vr.failed} FAILED")
    print("=" * 84)
    return 0 if vr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
