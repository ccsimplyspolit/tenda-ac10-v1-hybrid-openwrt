# Technical Report: Tenda AC10 V1.0 SPI Flash Survey, Factory RF Calibration (mtd1), and SquashFS Custom XZ Architecture

**Author**: `explorer_survey_flash`  
**Milestone**: M0 — Full Flash Survey, Factory RF Calibration, and SquashFS Decompression  
**Target Firmware**: Tenda AC10 V1.0 (`V15.03.06.52_multi`, Linux 3.10.90 MIPS32 LE)  
**Binary Image**: `Tenda_AC10_V1_FullFlash_8MB.bin` (8,388,608 bytes)  
**Kernel Dump**: `vmlinux_stock.bin` (7,253,712 bytes)  

---

## 1. Observation

### 1.1 Flash Physical Partition Map (8,388,608 bytes)
Direct byte-level inspection of `Tenda_AC10_V1_FullFlash_8MB.bin` across all 128 erase blocks (64 KB each) and cross-referencing with the static MTD partition array at virtual address `0x805A2638` in `vmlinux_stock.bin` (`struct mtd_partition`) revealed the following flash layout:

| MTD Partition | Internal Name | Flash Offset Range | Size (Bytes) | Size (KB / MB) | Purpose / Content Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `mtd0` | `ALL` | `0x00000000 - 0x00800000` | 8,388,608 | 8,192 KB (8.00 MB) | Full SPI Flash Image |
| `mtd1` | `Bootloader` | `0x00000000 - 0x00020000` | 131,072 | 128 KB (0.125 MB) | Realtek RTL8197F Booter v3.4.11B.9 |
| `mtd2` | `CFG` | `0x00020000 - 0x00030000` | 65,536 | 64 KB (0.0625 MB) | Factory RF Calibration & Board MIBs (`mtd1` in userland/OpenWrt) |
| `mtd3` | `KernelFS` | `0x00030000 - 0x007E0000` | 8,060,928 | 7,872 KB (7.6875 MB) | Combined Linux Kernel + SquashFS RootFS Container |
| — | `(Kernel)` | `0x00030000 - 0x0023BC12` | 2,145,300 | 2,095 KB (2.046 MB) | `cr6c` compressed Linux 3.10.90 MIPS32 LE kernel image |
| `mtd4` | `RootFS` | `0x0023BC12 - 0x0076BD76` | 5,439,844 | 5,312 KB (5.188 MB) | SquashFS 4.0 LE Root Filesystem (custom Tenda XZ compression) |
| — | `(Free Space)`| `0x0076BD76 - 0x007E0000` | 475,786 | 464.6 KB (0.454 MB) | Unallocated zero/FF padding space inside KernelFS |
| `mtd5` | `CFM` | `0x007E0000 - 0x007F0000` | 65,536 | 64 KB (0.0625 MB) | Primary Runtime NVRAM / User Configuration (`RouterCfm.cfg`) |
| `mtd6` | `CFM_BACKUP` | `0x007F0000 - 0x00800000` | 65,536 | 64 KB (0.0625 MB) | Backup Runtime NVRAM / User Configuration |

#### Evidence: Kernel In-Memory Partition Table
At file offset `0x005A2638` (Virtual Address `0x805A2638`) in `vmlinux_stock.bin`, the Linux kernel defines the master partition table parsed by `rtkxxpart` (`drivers/mtd/mtd_blkdevs.c`):
```c
struct mtd_partition {
    const char *name;                 /* offset +0x00 (32-bit pointer) */
    uint32_t pad0;                    /* offset +0x04 (64-bit alignment) */
    uint64_t size;                    /* offset +0x08 (64-bit unsigned) */
    uint64_t offset;                  /* offset +0x10 (64-bit unsigned) */
    uint32_t mask_flags;              /* offset +0x18 */
    struct nand_ecclayout *ecclayout; /* offset +0x1C */
};
```
Hex dump at `0x805A2638`:
```
0x805A2638: 20 E9 53 80 00 00 00 00 00 00 80 00 00 00 00 00  (name: "ALL", size: 0x800000, offset: 0x0)
0x805A2648: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A2658: 24 E9 53 80 00 00 00 00 00 00 02 00 00 00 00 00  (name: "Bootloader", size: 0x20000, offset: 0x0)
0x805A2668: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A2678: 30 E9 53 80 00 00 00 00 00 00 01 00 00 00 00 00  (name: "CFG", size: 0x10000, offset: 0x20000)
0x805A2688: 00 00 02 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A2698: 34 E9 53 80 00 00 00 00 00 00 7B 00 00 00 00 00  (name: "KernelFS", size: 0x7B0000, offset: 0x30000)
0x805A26A8: 00 00 03 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A26B8: 40 E9 53 80 00 00 00 00 00 00 00 00 00 00 00 00  (name: "RootFS", dynamic offset/size)
0x805A26C8: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A26D8: 48 E9 53 80 00 00 00 00 00 00 01 00 00 00 00 00  (name: "CFM", size: 0x10000, offset: 0x7E0000)
0x805A26E8: 00 00 7E 00 00 00 00 00 00 00 00 00 00 00 00 00
0x805A26F8: 4C E9 53 80 00 00 00 00 00 00 01 00 00 00 00 00  (name: "CFM_BACKUP", size: 0x10000, offset: 0x7F0000)
0x805A2708: 00 00 7F 00 00 00 00 00 00 00 00 00 00 00 00 00
```

#### Evidence: Realtek `cr6c` Kernel Header
At flash offset `0x030000`, the kernel contains a 64-byte `cr6c` image descriptor (Big-Endian format):
- Bytes `0x00..0x03`: `63 72 36 63` (`cr6c` signature)
- Bytes `0x04..0x07`: `80 A0 00 00` (RAM Load Address: `0x80A00000`)
- Bytes `0x08..0x0B`: `00 03 00 00` (Flash Start Offset: `0x00030000`)
- Bytes `0x0C..0x0F`: `00 20 BC 02` (Payload Length: `2,145,282` bytes = `0x20BC02`)
- Kernel End Calculation: `0x030000 + 0x20BC02 = 0x23BC02`.
- Following `0x23BC02`, 16 bytes of trailer (`21 80 00 00 ... 00 00 00 00`) pad the stream to `0x23BC12`, where the SquashFS superblock begins.

---

### 1.2 MTD1 Factory RF Calibration Partition Dissection (0x020000 - 0x030000)
- Partition size: `65,536` bytes (`64 KB`).
- Offset: `0x020000` to `0x030000`.
- Extracted binary saved: `k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\mtd1_factory_calibration.bin`.
- Header:
  - First 4 bytes (0x020000..0x020003): `7D 2A ED DE` (`0xDEED2A7D` Little-Endian, `0x7D2AEDDE` Big-Endian).
  - Next 4 bytes (0x020004..0x020007): `00 00 00 00`.
- Structure: Text-based MIB key-value format. Contains exactly 40 newline-separated (`\x0A`) entries spanning offset `0x020008` to `0x0208B4` (2,221 bytes of text). All remaining bytes (`0x0208B5` to `0x02FFFF`) are padded with `0xFF`.

#### Complete Inventory of MTD1 Entries (All 40 Keys)

| Rel Offset | Flash Offset | Key Name | Value | Description / Hardware Impact |
| :--- | :--- | :--- | :--- | :--- |
| `+0x0008` | `0x020008` | `HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_A` | `0101010101010101010101010101` | 5G Path A 40MHz vs 20MHz power delta (14 channels) |
| `+0x004F` | `0x02004F` | `HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_B` | `0101010101010101010101010101` | 5G Path B 40MHz vs 20MHz power delta (14 channels) |
| `+0x0096` | `0x020096` | `HW_WLAN1_TX_POWER_DIFF_HT20` | `0000001111111111112222222222` | 2.4G HT20 power delta across 14 channels |
| `+0x00CF` | `0x0200CF` | `TD_WLAN0_COUNTRY_PWR_POWER` | `92.100` | Tenda country power limit multiplier for 5G |
| `+0x00F1` | `0x0200F1` | `TD_WLAN1_COUNTRY_PWR_POWER` | `72,92,100` | Tenda country power limit multiplier for 2.4G |
| `+0x0116` | `0x020116` | `HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_A` | `1212121212121212121212121212` | 5G Path A 20MHz 1S vs OFDM delta |
| `+0x015D` | `0x02015D` | `HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_B` | `1212121212121212121212121212` | 5G Path B 20MHz 1S vs OFDM delta |
| `+0x01A4` | `0x0201A4` | `HW_WLAN1_TX_POWER_HT40_1S_A` | `1A1A1A1A1A1A1A1A1A1D1D1D1D1D` | 2.4G Path A HT40 base TX power (14 channels: ch1-9=26, ch10-14=29) |
| `+0x01DD` | `0x0201DD` | `HW_WLAN1_TX_POWER_HT40_1S_B` | `1515151616161616161717171717` | 2.4G Path B HT40 base TX power (14 channels: ch1-3=21, ch4-9=22, ch10-14=23) |
| `+0x0216` | `0x020216` | `TD_WLAN0_POWER` | `0` | Tenda 5G power mode offset |
| `+0x0227` | `0x020227` | `TD_WLAN1_POWER` | `0` | Tenda 2.4G power mode offset |
| `+0x0238` | `0x020238` | `HW_WLAN1_TX_POWER_DIFF_OFDM` | `1111112222222222223333333333` | 2.4G OFDM power delta across 14 channels |
| `+0x0271` | `0x020271` | `TD_ACCESS_WRITE` | `on` | Factory write permission flag |
| `+0x0284` | `0x020284` | `HW_WLAN0_WSC_PIN` | `16588547` | WPS PIN for 5 GHz interface |
| `+0x029E` | `0x02029E` | `HW_WLAN1_WSC_PIN` | `16588547` | WPS PIN for 2.4 GHz interface |
| `+0x02B8` | `0x0202B8` | `HW_WLAN0_11N_XCAP` | `27` | **5 GHz (RTL8822BE) Crystal Oscillator Capacitor (0x1B = 27)** |
| `+0x02CD` | `0x0202CD` | `HW_WLAN1_11N_XCAP` | `46` | **2.4 GHz (RTL8197FS) Crystal Oscillator Capacitor (0x2E = 46)** |
| `+0x02E2` | `0x0202E2` | `HW_WLAN0_11N_THER` | `25` | **5 GHz (RTL8822BE) Thermal Sensor Base Value (0x19 = 25)** |
| `+0x02F7` | `0x0202F7` | `HW_WLAN1_11N_THER` | `32` | **2.4 GHz (RTL8197FS) Thermal Sensor Base Value (0x20 = 32)** |
| `+0x030C` | `0x02030C` | `HW_WLAN1_TX_POWER_DIFF_HT40_2S` | `0000000000000000000000000000` | 2.4G HT40 2S delta (all zeroes) |
| `+0x0348` | `0x020348` | `HW_WLAN0_TX_POWER_5G_HT40_1S_A` | *(392 hex characters)* | **5 GHz Path A TX Power Table (196 channel slots)** |
| `+0x04F0` | `0x0204F0` | `HW_WLAN0_TX_POWER_5G_HT40_1S_B` | *(392 hex characters)* | **5 GHz Path B TX Power Table (196 channel slots)** |
| `+0x0698` | `0x020698` | `TD_FINISH_TSTFLAG` | `20181020161140500` | Factory ATE production test timestamp (2018-10-20 16:11:40) |
| `+0x06BC` | `0x0206BC` | `TD_THRPUT_TSTFLAG` | `20181020152952177` | Factory throughput test timestamp (2018-10-20 15:29:52) |
| `+0x06E0` | `0x0206E0` | `TD_WLAN0_SSID0_PWD` | `<YOUR_WIFI_PASSWORD>` | Factory default 5 GHz Wi-Fi password printed on sticker |
| `+0x06FC` | `0x0206FC` | `TD_WLAN1_SSID0_PWD` | `<YOUR_WIFI_PASSWORD>` | Factory default 2.4 GHz Wi-Fi password printed on sticker |
| `+0x0718` | `0x020718` | `HW_WLAN0_WLAN_ADDR` | `500FF5000005` | **5 GHz Wi-Fi MAC Address: `50:0F:F5:00:00:05`** |
| `+0x0738` | `0x020738` | `HW_WLAN1_WLAN_ADDR` | `500FF5000001` | **2.4 GHz Wi-Fi MAC Address: `50:0F:F5:00:00:01`** |
| `+0x0758` | `0x020758` | `HW_WLAN0_REG_DOMAIN` | `13` | Regulatory domain ID 13 |
| `+0x076F` | `0x02076F` | `HW_WLAN1_REG_DOMAIN` | `13` | Regulatory domain ID 13 |
| `+0x0786` | `0x020786` | `TD_WLAN0_WLAN_COUNTRY` | `US` | Factory default regulatory country for 5 GHz |
| `+0x079F` | `0x02079F` | `TD_WLAN1_WLAN_COUNTRY` | `US` | Factory default regulatory country for 2.4 GHz |
| `+0x07B8` | `0x0207B8` | `ucloud_serialnum` | `6590985` | Tenda Cloud registration serial number |
| `+0x07D1` | `0x0207D1` | `FLAG_OF_CE_LIMIT_POWER` | `open` | CE power limit bypass flag (`open` = full power allowed) |
| `+0x07ED` | `0x0207ED` | `TD_ATE_SN` | *(empty)* | Factory ATE serial number field |
| `+0x07F8` | `0x0207F8` | `HW_WLAN1_TX_POWER_CCK_A` | `2020202222222222222626262626` | 2.4G Path A CCK base TX power (14 channels: ch1-3=32, ch4-9=34, ch10-14=38) |
| `+0x082D` | `0x02082D` | `HW_WLAN1_TX_POWER_CCK_B` | `1A1A1A1B1B1B1B1B1B1E1E1E1E1E` | 2.4G Path B CCK base TX power (14 channels: ch1-3=26, ch4-9=27, ch10-14=30) |
| `+0x0862` | `0x020862` | `HW_NIC0_ADDR` | `500FF5000000` | **Base LAN/WAN Ethernet MAC Address: `50:0F:F5:00:00:00`** |
| `+0x087C` | `0x02087C` | `HW_NIC1_ADDR` | `00e04c8196c9` | Realtek secondary NIC MAC: `00:E0:4C:81:96:C9` |
| `+0x0896` | `0x020896` | `TD_RF_TSFLAG` | `20181020152200000` | Factory RF calibration timestamp (2018-10-20 15:22:00) |

#### Dissection of 5 GHz (RTL8822BE) TX Power Table (`196` Byte Channel Index)
The 5 GHz power tables `HW_WLAN0_TX_POWER_5G_HT40_1S_A` and `HW_WLAN0_TX_POWER_5G_HT40_1S_B` each consist of 392 hexadecimal characters (196 byte indices) corresponding to the IEEE 802.11a/n/ac 5 GHz channel allocation:
- **Indices `0..34` (Channels 1..35, invalid in 5 GHz)**: `0x00`
- **Indices `35..143` (Channels 36..144 — U-NII-1, U-NII-2A, U-NII-2C DFS)**:
  - Path A: `0x1B` (Decimal `27` power steps)
  - Path B: `0x1E` (Decimal `30` power steps)
- **Indices `144..152` (Channels 145..153 — Lower U-NII-3 Transition)**:
  - Path A: `0x19` (Decimal `25` power steps)
  - Path B: `0x1B` (Decimal `27` power steps)
- **Indices `153..176` (Channels 154..177 — U-NII-3: Ch 157, 161, 165, 173, 177)**:
  - Path A: `0x18` (Decimal `24` power steps)
  - Path B: `0x19` (Decimal `25` power steps)
- **Indices `177..195` (Channels 178..196, invalid)**: `0x00`

---

### 1.3 SquashFS 4.0 Custom XZ Compression & Block Header Architecture
- Superblock offset: `0x0023BC12`.
- Magic: `0x73717368` (`hsqs`, SquashFS 4.0 Little-Endian).
- Inode count: `1,296`.
- Block size: `131,072` bytes (`128 KB`, `block_log = 17`).
- Compression ID: `4` (`XZ`).
- Flags: `0x00E0` (`SQUASHFS_NOF | SQUASHFS_ALWAYS_FRAG | SQUASHFS_DUPLICATES | SQUASHFS_EXPORTABLE`).
- Compression options flag (`0x0400`): **NOT set**. Data blocks immediately follow the 96-byte superblock at `0x0023BC72`.
- Total filesystem size: `5,439,844` bytes (`0x530164`), ending at `0x0076BD76`.
- Total compressed blocks: **181 blocks**.

#### Block-Level Anatomy of Tenda Custom XZ Stream
Each compressed block in Tenda's SquashFS is a standalone customized `.xz` stream container:
```
+-----------------------------------------------------------------------------------------+
| STREAM HEADER (12 Bytes)                                                                |
|   0..5   : Magic: 54 65 6E 64 61 00 ("Tenda\x00", replaces standard "\xFD7zXZ\x00")     |
|   6..7   : Stream Flags: 00 01 (CRC32 Check enabled)                                    |
|   8..11  : Stream Header CRC: FD 69 95 C6                                               |
+-----------------------------------------------------------------------------------------+
| BLOCK HEADER (16 Bytes)                                                                 |
|   12     : Encoded Header Size: 0x03 ((3 + 1) * 4 = 16 bytes total Block Header)        |
|   13     : Block Flags: 0xC0 (Has Compressed Size + Has Uncompressed Size, 1 Filter)    |
|   14..16 : Compressed Size (VLI): e.g. 46,675 bytes (0xD3 0xEC 0x02)                   |
|   17..19 : Uncompressed Size (VLI): e.g. 131,072 bytes (0x80 0x80 0x08 = 128 KB)       |
|   20     : Filter ID (VLI): 0x21 (FILTER_LZMA2)                                         |
|   21     : Filter Property Size (VLI): 0x01 (1 byte)                                    |
|   22     : Filter Properties: 0x0A (Dictionary Size = 128 KB)                          |
|   23     : Header Padding: 0x00                                                         |
|   24..27 : Block Header CRC32: 57 FB 18 DF                                              |
+-----------------------------------------------------------------------------------------+
| RAW LZMA2 COMPRESSED DATA STREAM (Compressed Size Bytes)                                |
|   28 .. (28 + Compressed Size): Raw LZMA2 payload                                      |
+-----------------------------------------------------------------------------------------+
| BLOCK TRAILER & STREAM FOOTER (24 Bytes)                                                |
|   Block Padding: 0 to 3 bytes (4-byte alignment)                                        |
|   Block Check: 4 bytes (CRC32 of uncompressed data)                                     |
|   Index: 12 bytes                                                                       |
|   Stream Footer: 12 bytes ending in 00 01 59 5A ("\x00\x01YZ")                          |
+-----------------------------------------------------------------------------------------+
```

#### Decompression Empirical Proof
Running `k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\tenda_squashfs_extractor.py` against all 181 blocks:
- Total blocks extracted: **181 / 181 (100.0% success rate, 0 corrupt blocks)**.
- Total uncompressed filesystem size: **20,294,917 bytes (19.35 MB)**.
- Compression ratio: **0.27x (26.8%)**.
- First decompressed block output: Valid MIPS ELF binary header `\x7fELF\x01\x01\x01\x00` (`dev_svr` linking against `/lib/ld-uClibc.so.0`).

---

### 1.4 Wireless Initialization Architecture Traced
Tracing `/etc_ro/init.d/rcS`, `/bin/wlan.sh`, `/bin/wlanapp.sh`, `/bin/flash`, `/lib/libapmib.so`, and `/lib/libmtdapi.so`:
1. **Kernel Boot Stage**:
   - The kernel statically initializes the `rtl8192cd` unified wireless driver.
   - Probes SoC internal RTL8197FS (registers interface `wlan1` for 2.4 GHz) and PCIe RTL8822BE (registers interface `wlan0` for 5 GHz).
   - Creates the `/proc/wlan0/` and `/proc/wlan1/` procfs trees for register access, statistics, and hardware monitoring (`led`, `acs_score`, `stats`).
2. **Userland Init Stage (`rcS` -> `inittab` -> `monitor` -> `cfmd`)**:
   - `rcS` loads hardware acceleration modules (`fastnat.ko`, `bm.ko`, `mac_filter.ko`, `privilege_ip.ko`, `qos.ko`, `loadbalance.ko`).
   - `monitor` spawns `cfmd` (Tenda Configuration Manager daemon).
3. **Wireless Parameter Injection (`wlan.sh` -> `flash get` -> `iwpriv set_mib`)**:
   - `wlan.sh` calls `flash get <MIB_NAME>`.
   - `bin/flash` calls `apmib_get()` in `libapmib.so`.
   - `libapmib.so` uses `libmtdapi.so` (`rtl_name_to_mtdchar`) to parse `/proc/mtd`, locates partition `"CFG"` (which corresponds to `mtd1` / `0x020000`), opens `/dev/mtd2` (or `/dev/mtdblock2`), verifies magic `0xDEED2A7D`, and returns the unit's calibrated values.
   - `wlan.sh` sets MAC addresses:
     - `ifconfig wlan0 hw ether 50:0F:F5:00:00:05`
     - `ifconfig wlan1 hw ether 50:0F:F5:00:00:01`
   - `wlan.sh` pushes all calibration tables directly into the driver:
     - `iwpriv wlan0 set_mib regdomain=13`
     - `iwpriv wlan0 set_mib RFChipID=$HW_RF_TYPE`
     - `iwpriv wlan0 set_mib TxPowerOFDM_1SS=$HW_WLAN0_TX_POWER_OFDM_1S`
     - `iwpriv wlan0 set_mib TxPowerOFDM_2SS=$HW_WLAN0_TX_POWER_OFDM_2S`
     - `iwpriv wlan0 set_mib ther=25`
     - `iwpriv wlan1 set_mib TxPowerCCK=2020202222...`
     - `iwpriv wlan1 set_mib ther=32`
4. **Daemon Launch (`wlanapp.sh`)**:
   - Generates `/var/wsc.conf` via `flash upd-wsc-conf`.
   - Launches `wscd` (WPS daemon) and `iwcontrol` (Realtek wireless monitor daemon).

---

## 2. Logic Chain

1. **Partition Table Derivation**:
   - From Observation 1.1, the flash dump exhibits string tables and magic numbers at `0x00000` (`Realtek Booter`), `0x20000` (`HW_WLAN` MIB text), `0x30000` (`cr6c` kernel), `0x23BC12` (`hsqs` SquashFS), `0x7E0000` (`adv.iptv` CFM NVRAM), and `0x7F0000` (backup CFM).
   - In `vmlinux_stock.bin` at `0x805A2638`, the kernel's own static partition array explicitly defines `ALL` (8MB), `Bootloader` (128KB @ 0x0), `CFG` (64KB @ 0x20000), `KernelFS` (7,872KB @ 0x30000), `CFM` (64KB @ 0x7E0000), and `CFM_BACKUP` (64KB @ 0x7F0000).
   - Therefore, the partition boundaries are hardware-level and exact.

2. **RootFS Offset Alignment**:
   - The kernel header at `0x030000` specifies `image_len = 0x0020BC02` (2,145,282 bytes).
   - Adding `0x030000 + 0x20BC02 = 0x23BC02`.
   - With 16 bytes of trailer alignment, the dynamic partition parser `rtkxxpart` calculates `RootFS` offset as `0x23BC12`.
   - Observation 1.3 proves the SquashFS superblock resides at precisely `0x23BC12`.

3. **Factory RF Calibration Format Contrast**:
   - Standard Realtek reference boards store calibration as a binary struct `HW_SETTING` starting with `HS` or `HS0`.
   - Observation 1.2 demonstrates Tenda AC10 V1.0 uses a text-based MIB format with magic `7D 2A ED DE` (`0xDEED2A7D`), containing 40 keys.
   - In `webroot_ro/apmib.cfg`, the firmware includes a default template with dummy MACs (`00:90:4C:88:88:88`) and generic RF values.
   - Observation 1.2 proves that `mtd1` overrides this template with the router's individual hardware calibrations (e.g. MAC `50:0F:F5:00:00:00`, crystal caps 27 and 46, thermal baseline 25 and 32).
   - In OpenWrt 2026 ports (`ADCDS` / `Putpocket`), the open-source driver `rtw88` attempts to read eFuse from the RTL8822BE PCIe card. Because Tenda leaves the physical eFuse blank and places all calibration in `mtd1`, `rtw88` fails to load RF parameters, dropping 5 GHz to 58 Mbps HT20 with a 17 dB power deficit.

4. **SquashFS Custom XZ Decompression Mechanism**:
   - Standard tools (`unsquashfs`, `lzma`, `7z`) fail on the SquashFS partition because Tenda modified the XZ container header.
   - By disassembling `xz_dec_run` at `0x8015C930` in `vmlinux_stock.bin` (Observation 1.3), we proved the kernel expects `b"Tenda\x00"` at the stream start instead of `b"\xfd7zXZ\x00"`.
   - By dissecting the block header at index 12, we showed that each block is an XZ container with a 12-byte stream header, a 16-byte block header with LZMA2 filter `0x21` and dictionary size 128 KB (`0x0A`), followed by the raw LZMA2 stream at byte 28.
   - Decompressing byte 28 using raw LZMA2 with a 128 KB dictionary yields valid rootfs data across all 181 blocks with 100% success.

---

## 3. Caveats

1. **eFuse Immutability**:
   The RTL8822BE PCIe card in Tenda AC10 V1.0 has a blank physical eFuse. Modifying open-source drivers (`rtw88`) requires writing a kernel shim to parse `mtd1` and feed the MIB tables into `rtw88` platform data; eFuse cannot be programmed via software in-field without risk of bricking.
2. **CFM Configuration Integrity**:
   Partitions `mtd4` (`0x7E0000`) and `mtd5` (`0x7F0000`) use a proprietary 8-byte header consisting of a 4-byte CRC32 followed by a 4-byte length. Manual edits to `RouterCfm.cfg` must maintain this CRC header or the firmware will reject the block and revert to defaults.

---

## 4. Conclusion

1. **Partition Table**: The flash partition layout is definitively verified:
   - `0x000000 - 0x020000`: `Bootloader` (128 KB)
   - `0x020000 - 0x030000`: `CFG` (Factory Calibration, 64 KB, magic `0xDEED2A7D`)
   - `0x030000 - 0x23BC12`: `KernelFS` / Linux Kernel (2,095 KB, `cr6c`)
   - `0x23BC12 - 0x76BD76`: `RootFS` / SquashFS 4.0 LE (5,312 KB, custom Tenda XZ)
   - `0x76BD76 - 0x7E0000`: Unused / Free Flash (464.6 KB)
   - `0x7E0000 - 0x7F0000`: `CFM` Primary NVRAM (64 KB)
   - `0x7F0000 - 0x800000`: `CFM_BACKUP` Secondary NVRAM (64 KB)
2. **Factory Calibration (`mtd1`)**: Contains 40 critical text keys, including base MAC `50:0F:F5:00:00:00`, 5G MAC `50:0F:F5:00:00:05`, 2.4G MAC `50:0F:F5:00:00:01`, 196-channel 5 GHz power tables, and crystal/thermal coefficients (`XCAP=27/46`, `THER=25/32`).
3. **SquashFS Custom Format**: Fully solved. The custom format uses a 12-byte stream header (`Tenda\x00`) and 16-byte block header; raw LZMA2 data begins at byte 28. All 181 blocks decompress cleanly.
4. **Tooling Produced**:
   - `tenda_squashfs_extractor.py`: Automated decompressor for Tenda SquashFS.
   - `parse_mtd1.py`: Full MTD1 factory calibration parser.
   - `mtd1_factory_calibration.bin`: Raw binary backup of factory calibration partition.

---

## 5. Verification Method

To independently reproduce and verify all findings:

1. **Verify Flash Partitions & Kernel Table**:
   ```powershell
   python k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\analyze_partitions.py
   python k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\dump_mtd_table.py
   ```
   *Expected Output*: MTD partitions match exact offsets `0x0`, `0x20000`, `0x30000`, `0x23BC12`, `0x7E0000`, `0x7F0000`.

2. **Verify MTD1 Factory Calibration Extraction**:
   ```powershell
   python k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\parse_mtd1.py
   python k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\dissect_rf.py
   ```
   *Expected Output*: Exactly 40 parsed keys, magic `0xDEED2A7D`, MAC addresses `500FF5000000` / `500FF5000005` / `500FF5000001`, and 196-channel 5G power tables.

3. **Verify SquashFS Decompression**:
   ```powershell
   python k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_flash\tenda_squashfs_extractor.py
   ```
   *Expected Output*: `Valid blocks: 181 / 181 (100.0%)`, `Total Uncompressed Data: 20,294,917 bytes`.

4. **Invalidation Conditions**:
   - If any block in `tenda_squashfs_extractor.py` throws `Corrupt input data`, the LZMA2 filter parameters or header offset calculation is invalid.
   - If the first 4 bytes of `mtd1` differ from `7D 2A ED DE`, the factory partition magic definition is invalid.
