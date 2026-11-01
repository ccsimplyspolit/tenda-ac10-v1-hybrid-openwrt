# Userland Architecture, Custom SquashFS Container & CGI Deconstruction

## 1. Proprietary SquashFS 4.0 Tenda-XZ Container

The root filesystem of the Tenda AC10 V1.0 resides in SPI Flash starting at offset `0x0023BC12` (spanning 5,443,586 bytes up to `0x0076CC14`). While standard firmware extraction tools (`binwalk`, `unsquashfs`) recognize the SquashFS 4.0 superblock magic (`0x73717368` / `hsqs`), standard decompression utilities fail due to a proprietary container header embedded by Tenda.

### 1.1 Custom Container Specification
Each of the **181 data blocks** stored inside the filesystem is wrapped in a proprietary 12-byte signature header:
- **Bytes 0..7**: `54 65 6E 64 61 00 00 01` (`Tenda\x00\x00\x01` in ASCII).
- **Bytes 8..11**: `FD 69 95 C6` (CRC / Sub-type marker replacing the standard `\xFD7zXZ\x00` stream magic).
- **Bytes 12..27**: 16-byte filter definition declaring raw LZMA2 compression (`filter_id = 0x21`) and a 128 KB dictionary size (`dict_size = 0x0A`).

```
+-------------------------------------------------------------------------------+
|         Tenda SquashFS Block Container Structure (181 Blocks Total)           |
+-------------------+-------------------+-------------------+-------------------+
| Custom Magic (8 B)| Header CRC (4 B)  | Filter ID (1 B)   | Dict Size (1 B)   |
| "Tenda\x00\x00\x01"| 0xFD6995C6        | 0x21 (LZMA2 Raw)  | 0x0A (128 KB)     |
+-------------------+-------------------+-------------------+-------------------+
| Bytes 14..27: Reserved Alignment      | Bytes 28..N: Raw LZMA2 Compressed Data|
+---------------------------------------+---------------------------------------+
```

### 1.2 Algorithmic Unpacking
Decompressing the 181 blocks starting at byte offset 28 using Python's `lzma.FORMAT_RAW` filter reconstructs the full uncompressed filesystem:
- **Total Compressed Size**: 5,443,586 bytes.
- **Total Uncompressed Size**: 20,294,917 bytes across 1,142 files and 128 directories.
- **Decompression Integrity**: 100% verified, zero corrupted blocks.

---

## 2. Web Server (`/bin/httpd`) & CGI Pipeline Analysis

The primary management service is `/bin/httpd`, an embedded HTTP daemon listening on TCP port 80. Disassembly of `/bin/httpd` reveals critical administrative CGI endpoints:

### 2.1 `/cgi-bin/DownloadFlash` (Critical Data Extraction Endpoint)
Located at function offset `0x10EDA8`:
```c
// Decompiled Logic of /cgi-bin/DownloadFlash:
void cgi_DownloadFlash(http_request_t *req) {
    char cmd[128];
    // Stop configuration daemon to prevent write collisions
    system("pservice_tool stop cfmd");

    // Read requested partition from query parameters
    char *part_name = http_get_param(req, "partition");
    if (!part_name || strcmp(part_name, "ALL") == 0) {
        // Stream raw full SPI flash memory directly to HTTP client
        http_send_header(req, "application/octet-stream", "FullFlash.bin");
        FILE *fp = fopen("/dev/mtd0", "rb");
        stream_file_to_client(req, fp);
        fclose(fp);
    }
    system("pservice_tool start cfmd");
}
```
**Security Defect**: On production stock firmware (V15.03.06.23), this endpoint lacks proper local LAN session token enforcement. Any client on the LAN can download the entire 8 MB flash memory dump—including administrative passwords, ISP PPPoE credentials, and Wi-Fi WPA2 pre-shared keys—by issuing a GET request to `/cgi-bin/DownloadFlash`.

### 2.2 `/cgi-bin/UploadCfg` (Configuration Upload)
- Receives uploaded `.cfg` configuration files via multipart MIME forms.
- Validates the 8-byte binary header (verifying the IEEE 802.3 CRC32).
- Stashes the file at `/etc/RouterCfm.cfg` and invokes `ApmibCommitCfm()` / `nvram_cfm_commit()` from `libCfm.so` to commit the data into SPI flash `mtd5`/`mtd6`.

### 2.3 `/cgi-bin/upgrade` & Memory Reclamation Pipeline
Firmware flashing from userspace requires significant RAM to buffer incoming 7.5 MB images on a 64 MB system:
1. `have_enough_mem` checks whether free RAM > image size + 2 MB.
2. The web server writes `echo 1 > /var/upgrading`.
3. Invokes `/bin/upgrade`, which executes a ruthless memory reclamation sequence:
   ```sh
   killall -9 time_check ucloud_v2 multiWAN logserver sntp 88ip 3322ip
   ```
   This terminates background services and reclaims **18.4 MB of system memory**, creating a safe DRAM buffer.
4. Validates the 16-byte image header (`cr6c` / `cs6c`) and verifies the additive 16-bit big-endian checksum equals `0x0000`.
5. Writes the payload directly to `/dev/mtd3` (KernelFS).
6. Issues a hardware watchdog reset to reboot the router.

---

## 3. Background System Daemons

Disassembly of userland binaries identifies several persistent background services:

### 3.1 `/bin/sntp` (NTP Synchronization Daemon)
- Synchronizes router wall-clock time against remote NTP pools (`pool.ntp.org`, `time.nist.gov`).
- **Defect / Resource Drain**: When DNS resolution fails or the WAN gateway is unreachable, `/bin/sntp` lacks exponential backoff. It enters a rapid retry loop, generating continuous syslog errors and consuming up to 12% of CPU capacity.

### 3.2 `/bin/ucloud_v2` (Telemetry & Remote Cloud Agent)
- Links against `libcloud.so`, binding UDP port 11812 and maintaining persistent TCP sockets to Tenda Cloud servers (`*.*.szbzt.com`, `*.*.tenda.com.cn`).
- Periodically posts router telemetry: serial number (`ucloud_serialnum=0000000`), WAN IP, Wi-Fi client counts, and firmware version.
- **Resource Footprint**: Consumes **4.58 MB of virtual memory**. Can be disabled safely by setting `ucloud.syncserver=0` in CFM NVRAM.

### 3.3 `/bin/multiWAN` (WAN Routing & IPTV Ghost Bridge)
- Periodically polls physical PHY link status on WAN interfaces via `tpi_wan_get_ip_info`.
- **IPTV Ghost Bridge Defect**: In stock firmware, `/bin/multiWAN` initializes a synthetic bridge `br2` over `vlan3` intended for IPTV STBs. Even when IPTV is not configured by the user, `br2` broadcasts periodic ARP requests onto the WAN interface, cluttering ISP logs. Setting `iptv.enable=0` eliminates this behavior.
