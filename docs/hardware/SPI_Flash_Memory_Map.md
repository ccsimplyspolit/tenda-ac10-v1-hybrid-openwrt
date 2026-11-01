# SPI Flash Memory Map & Forensic Partition Geometry

## 1. SPI Flash Hardware Specifications

The Tenda AC10 V1.0 utilizes an industry-standard 8-megabyte Serial Peripheral Interface (SPI) NOR Flash memory chip:
- **Device Model**: Winbond W25Q64FV / W25Q64JV (or fully compatible GigaDevice GD25Q64C).
- **JEDEC Manufacturer & Device ID**: `0xEF 0x40 0x17` (Winbond W25Q64).
- **Total Capacity**: 8 MB (64 Mbit / 8,388,608 bytes).
- **Physical Sector / Block Geometry**:
  - Total Blocks: 128 erasable 64 KB blocks (`0x10000` bytes each).
  - Sectors per Block: 16 erasable 4 KB uniform sectors (`0x1000` bytes each).
  - Page Size: 256 bytes per programming page.
- **Operating Voltage & Bus Speed**: 3.3V nominal, clocked by the RTL8197FS SPI controller at 41.67 MHz in Fast Read Dual-Output SPI mode.

```
+---------------------------------------------------------------------------------------+
|                 Tenda AC10 V1.0 8 MB (8,388,608 Bytes) SPI Flash Memory Map            |
+---------------------+-------------------+---------------------+-----------------------+
| Offset Range (Hex)  | Partition Name    | Size (Bytes / KB)   | Content Description   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x000000 - 0x020000 | mtd1: Bootloader  |   131,072 (128 KB)  | Stage 1 & Stage 2     |
+---------------------+-------------------+---------------------+-----------------------+
| 0x020000 - 0x030000 | mtd2: CFG (Cal)   |    65,536 (64 KB)   | 40 RF Factory Keys    |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x23BC12 | Kernel (cr6c)     | 2,145,298 (~2.1 MB) | Linux 3.10.90 Kernel  |
+---------------------+-------------------+---------------------+-----------------------+
| 0x23BC12 - 0x76CC14 | RootFS (hsqs)     | 5,443,586 (~5.4 MB) | SquashFS 4.0 Tenda-XZ |
+---------------------+-------------------+---------------------+-----------------------+
| 0x76CC14 - 0x7E0000 | Dirty JFFS2 Gap   |   472,044 (461 KB)  | Manufacturing Residue |
+---------------------+-------------------+---------------------+-----------------------+
| 0x7E0000 - 0x7F0000 | mtd5: CFM Primary |    65,536 (64 KB)   | Primary NVRAM Sector  |
+---------------------+-------------------+---------------------+-----------------------+
| 0x7F0000 - 0x800000 | mtd6: CFM Backup  |    65,536 (64 KB)   | Backup NVRAM Sector   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x7E0000 | mtd3: KernelFS    | 8,060,928 (7,872 KB)| Total Firmware Slot   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x76CC14 | Stock Recovery    | 7,588,884 (7,411 KB)| Clean TFTP Image      |
+---------------------+-------------------+---------------------+-----------------------+
```

---

## 2. Forensic Partition Table & Cryptographic Checksums

Every byte boundary and partition offset has been extracted from the master SPI flash image (`Tenda_AC10_V1_FullFlash_8MB.bin`) and validated bit-for-bit:

| Partition Index | Stock Runtime Label (`vmlinux:0x805A2638`) | OpenWrt DTS Label (`tenda-ac10-v1.dts`) | Flash Start Offset | Flash End Offset | Byte Count | SHA-256 Checksum |
|---|---|---|---|---|---:|---|
| **mtd0** | `ALL` | *(Full Flash)* | `0x00000000` | `0x00800000` | `8,388,608` | `af40888b2a92539ef51218a7ed6dc25c48ac2cd51950ffcf25bec44b98252833` |
| **mtd1** | `Bootloader` | `bootloader` | `0x00000000` | `0x00020000` | `131,072` | `5f351f3bbcfa3a1b2a5f17bdcdd5191deec5685126bb0a5830f96788d8962036` |
| **mtd2** | `CFG` | `calibration` | `0x00020000` | `0x00030000` | `65,536` | `2b0224aff5c250bf10c25d94c38a638496543cc2af1287a692c58855e269aba7` |
| **mtd3** | `KernelFS` | `firmware` | `0x00030000` | `0x007E0000` | `8,060,928` | `4679fa4673696318288896d6518515db7c0db4e5defb88d8bfe552bc98181c45` |
| **Slice** | *(Kernel Slice)* | *(Kernel Sub-slice)* | `0x00030000` | `0x0023BC12` | `2,145,298` | `023bc89c65c7c0c00ee6ca34b65c07644c3df62f3c38e76e760bcef54248dd33` |
| **mtd4** | `RootFS` (Dynamic) | *(RootFS Sub-slice)* | `0x0023BC12` | `0x007E0000` | `5,915,630` | *(Dynamic MTD container created at boot)* |
| **Slice** | `SquashFS Actual` | *(SquashFS Payload)* | `0x0023BC12` | `0x0076CC14` | `5,443,586` | `fcbf377debd9ab7d819c186c15660a65d5a32b579310f758d2c764505f728749` |
| **Gap** | `Dirty JFFS2 Gap` | *(Writable JFFS2)* | `0x0076CC14` | `0x007E0000` | `472,044` | *(423,839 dirty bytes from factory testing)* |
| **mtd5** | `CFM` | `cfm_primary` | `0x007E0000` | `0x007F0000` | `65,536` | `289e4321ec0c5b656c9f5e57c56279846387dbcd4b8cab1f89d843fb04faa457` |
| **mtd6** | `CFM_BACKUP` | `cfm_backup` | `0x007F0000` | `0x00800000` | `65,536` | `26bfb1cd0995670092040bf550adaef538f8bbe8590f7e2dfc0e7153acdc1564` |
| **Image** | `Stock Recovery` | *(TFTP Recovery)* | `0x00030000` | `0x0076CC14` | `7,588,884` | `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa` |

---

## 3. Dynamic Partition Parsing: Stock Kernel vs OpenWrt DTS

A fundamental difference exists between how the stock Realtek kernel determines partition boundaries versus how OpenWrt parses flash.

### 3.1 Stock Runtime Parsing (`rtkxxpart_parse` at `0x801A8FD0`)
In stock firmware, the Linux kernel does **not** rely on a static device tree for partition offsets:
1. It reads the static base descriptor table at `0x805A2638`:
   - `ALL`: `0x00000000` to `0x00800000`
   - `Bootloader`: `0x00000000` to `0x00020000`
   - `CFG`: `0x00020000` to `0x00030000`
   - `KernelFS`: `0x00030000` to `0x007E0000`
   - `CFM`: `0x007E0000` to `0x007F0000`
   - `CFM_BACKUP`: `0x007F0000` to `0x00800000`
2. Next, `rtkxxpart_parse` inspects the 16-byte `cr6c` image header at `0x00030000`.
3. It reads the 32-bit big-endian length of the kernel payload (at header offset `+12`: `0x0020BC02` = `2,145,282` bytes).
4. Adding the 16-byte header size (`0x10`), it calculates the exact boundary of the kernel as:
   `0x00030000 + 0x0020BC12 = 0x0023BC12`.
5. It dynamically registers a synthetic partition **`RootFS`** spanning from `0x0023BC12` to `0x007E0000` (length `5,915,630` bytes).
6. SquashFS mounts directly at `0x0023BC12`. Any unallocated flash beyond the SquashFS filesystem end (`0x0076CC14`) up to `0x007E0000` is formatted as a writable JFFS2 overlay.

### 3.2 OpenWrt DTS Partition Model
In OpenWrt 19.07 (Linux 4.14), partitions are declared explicitly in the device tree (`tenda-ac10-v1.dts`):
```dts
&spi0 {
    status = "okay";
    flash@0 {
        compatible = "jedec,spi-nor";
        reg = <0>;
        spi-max-frequency = <41666667>;

        partitions {
            compatible = "fixed-partitions";
            #address-cells = <1>;
            #size-cells = <1>;

            partition@0 {
                label = "bootloader";
                reg = <0x00000000 0x00020000>;
                read-only;
            };

            partition@20000 {
                label = "calibration";
                reg = <0x00020000 0x00010000>;
                read-only;
            };

            partition@30000 {
                label = "firmware";
                reg = <0x00030000 0x007B0000>; // 7,872 KB
                compatible = "openwrt,uimage", "denx,uimage";
            };

            partition@7e0000 {
                label = "cfm";
                reg = <0x007E0000 0x00020000>; // 128 KB (Primary + Backup)
            };
        };
    };
};
```
OpenWrt's split firmware parser automatically detects the rootfs magic (`hsqs`) following the kernel and dynamically splits `firmware` into `kernel` and `rootfs_data`.

---

## 4. The 472 KB Dirty Gap & The Flashing Trap

A common failure mode when flashing stock firmware via the Realtek Bootloader involves the **472,044-byte gap** between `0x0076CC14` and `0x007E0000`.

### 4.1 Origin of the Gap
When Tenda factory-programs the router:
1. The SquashFS 4.0 filesystem ends cleanly at byte `5,443,586` (flash address `0x0076CC14`).
2. During factory Quality Assurance testing, the router boots into Linux and mounts a writable JFFS2 filesystem in the remaining flash space up to `0x007E0000`.
3. When the router is packaged and shipped, this 472 KB space contains **423,839 non-0xFF residual bytes** consisting of dirty JFFS2 nodes, log fragments, and calibration logs.

### 4.2 The Flashing Trap: `mtd3_kernelfs.bin` vs `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`
If an operator dumps raw partition `mtd3` (spanning `0x00030000` to `0x007E0000`, 8,060,928 bytes) and attempts to upload it via TFTP:
1. Booter `AutoBurn` parses Segment 1 (`cr6c`, length 2,145,282 B), verifies checksum, and burns it to `0x00030000`.
2. `AutoBurn` advances to offset `2,145,298` (`0x0023BC12`) and encounters `hsqs`.
3. `check_rootfs_image` calculates expected SquashFS length = `5,443,586` bytes.
4. Because `8,060,928 - (2,145,298 + 5,443,586) = 472,044` bytes remain, `AutoBurn` expects another valid image header at `0x0076CC14`.
5. At `0x0076CC14`, it finds dirty JFFS2 bytes rather than a recognized magic (`cr6c`, `cs6c`, `hsqs`).
6. **Failure**: `AutoBurn` throws an image header error, enters an infinite loop, and fails to reboot.

In contrast, **`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`** (`7,588,884` bytes) is cleanly truncated at byte `7,588,884` (offset `0x0076CC14`). It has **zero trailing bytes**. Both segments evaluate to valid additive 16-bit checksums of `0x0000`, and `AutoBurn` completes successfully with an automatic reboot.
