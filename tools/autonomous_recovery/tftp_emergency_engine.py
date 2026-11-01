#!/usr/bin/env python3
"""
TFTP Emergency Engine for Tenda AC10 V1.0 Recovery
Pure Python 3 RFC 1350 Dual-Mode TFTP Client and Server (Zero External Dependencies)

Features:
- 100% standard library (socket, struct, os, sys, time, threading, argparse, hashlib, logging).
- Zero external pip requirements; operates completely offline.
- Client Mode: Pushes firmware via WRQ to Realtek Booter (192.168.1.6:69).
  Handles ephemeral source ports, 512-byte blocks, trailing zero-length termination packet
  on exact 512-byte multiples, 16-bit block rollover modulo 65536, exponential backoff retries.
- Server Mode: Listens on UDP 0.0.0.0:69 for incoming RRQ/WRQ.
- Dual Mode: Background RRQ listener with active WRQ client push.
- Terminal Progress Bar: Real-time byte count, percentage, transfer rate (KB/s), ETA.
"""

import os
import sys
import time
import socket
import struct
import threading
import argparse
import hashlib
import logging

# RFC 1350 Opcodes
OPCODE_RRQ   = 1
OPCODE_WRQ   = 2
OPCODE_DATA  = 3
OPCODE_ACK   = 4
OPCODE_ERROR = 5

# RFC 1350 Error Codes
ERR_NOT_DEFINED       = 0
ERR_FILE_NOT_FOUND    = 1
ERR_ACCESS_VIOLATION  = 2
ERR_DISK_FULL         = 3
ERR_ILLEGAL_OPERATION = 4
ERR_UNKNOWN_TID       = 5
ERR_FILE_EXISTS       = 6
ERR_NO_SUCH_USER      = 7

DEFAULT_BLOCK_SIZE = 512
DEFAULT_TIMEOUT    = 1.5
MAX_TIMEOUT        = 5.0
DEFAULT_RETRIES    = 5

logger = logging.getLogger("TFTP_Engine")


class TftpError(Exception):
    """Custom exception for TFTP protocol errors."""
    def __init__(self, code, message):
        super().__init__(f"TFTP Error {code}: {message}")
        self.code = code
        self.message = message


class ProgressBar:
    """Terminal progress bar using standard library carriage returns."""
    def __init__(self, total_bytes, prefix="Transferring", quiet=False):
        self.total_bytes = max(1, total_bytes)
        self.prefix = prefix
        self.quiet = quiet
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.current_bytes = 0

    def update(self, current_bytes, force=False):
        if self.quiet:
            return
        self.current_bytes = current_bytes
        now = time.time()
        if not force and (now - self.last_update_time < 0.1):
            return
        self.last_update_time = now

        elapsed = max(0.001, now - self.start_time)
        rate_kb = (current_bytes / 1024.0) / elapsed
        pct = min(100.0, (current_bytes / self.total_bytes) * 100.0)

        remaining_bytes = max(0, self.total_bytes - current_bytes)
        eta_sec = int(remaining_bytes / (rate_kb * 1024.0)) if rate_kb > 0 else 0

        bar_width = 30
        filled = int(bar_width * (pct / 100.0))
        bar = "=" * filled + (">" if filled < bar_width else "") + " " * (bar_width - filled - (1 if filled < bar_width else 0))

        cur_mb = current_bytes / (1024.0 * 1024.0)
        tot_mb = self.total_bytes / (1024.0 * 1024.0)

        sys.stdout.write(
            f"\r{self.prefix} [{bar}] {pct:5.1f}% | {cur_mb:5.2f}/{tot_mb:5.2f} MB | "
            f"{rate_kb:6.1f} KB/s | ETA: {eta_sec:3d}s"
        )
        sys.stdout.flush()

    def finish(self, success=True):
        if self.quiet:
            return
        now = time.time()
        elapsed = max(0.001, now - self.start_time)
        rate_kb = (self.current_bytes / 1024.0) / elapsed
        tot_mb = self.total_bytes / (1024.0 * 1024.0)
        status = "COMPLETED" if success else "FAILED"
        sys.stdout.write(
            f"\n[*] Transfer {status}: {tot_mb:.2f} MB in {elapsed:.2f}s (Average {rate_kb:.1f} KB/s)\n"
        )
        sys.stdout.flush()


def create_udp_socket():
    """Creates a UDP socket with Windows WSAECONNRESET disabled if applicable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if sys.platform == "win32":
        try:
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except Exception:
            pass
    return sock


class TftpClient:
    """
    RFC 1350 TFTP Client implementation.
    Optimized for router firmware uploading (WRQ push).
    """
    def __init__(self, host="192.168.1.6", port=69, timeout=DEFAULT_TIMEOUT,
                 retries=DEFAULT_RETRIES, block_size=DEFAULT_BLOCK_SIZE, quiet=False):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.block_size = block_size
        self.quiet = quiet

    def push_file(self, file_path, remote_filename="firmware.bin", progress_cb=None):
        """
        Pushes a local file to the remote TFTP server via WRQ.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            payload = f.read()

        return self.push_bytes(payload, remote_filename=remote_filename, progress_cb=progress_cb)

    def push_bytes(self, payload, remote_filename="firmware.bin", progress_cb=None):
        """
        Pushes an in-memory byte buffer to the remote TFTP server via WRQ.
        """
        total_len = len(payload)
        logger.info(f"Initiating TFTP WRQ push of {total_len} bytes to {self.host}:{self.port} as '{remote_filename}'")

        sock = create_udp_socket()
        sock.settimeout(self.timeout)

        pb = ProgressBar(total_len, prefix="TFTP WRQ Push", quiet=self.quiet)

        try:
            # Build WRQ packet: opcode 2 (uint16_BE) + filename + 0 + "octet" + 0
            wrq_packet = struct.pack(">H", OPCODE_WRQ) + remote_filename.encode("ascii", "ignore") + b"\x00octet\x00"

            # Step 1: Send WRQ to destination host and port (typically 69)
            # The server will acknowledge block 0 from its ephemeral transfer port.
            server_tid = None
            cur_timeout = self.timeout

            for attempt in range(1, self.retries + 1):
                try:
                    sock.sendto(wrq_packet, (self.host, self.port))
                except OSError as e:
                    logger.debug(f"WRQ sendto failed on attempt {attempt}: {e}")

                start_attempt = time.time()
                while True:
                    time_left = cur_timeout - (time.time() - start_attempt)
                    if time_left <= 0:
                        cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                        logger.warning(f"WRQ attempt {attempt}/{self.retries} timed out. Retrying with timeout {cur_timeout:.1f}s...")
                        break
                    try:
                        sock.settimeout(time_left)
                        resp_data, sender = sock.recvfrom(1024)
                        if sender[0] != self.host:
                            # Ignore responses from unexpected hosts
                            continue
                        if len(resp_data) >= 4:
                            opcode, ack_block = struct.unpack(">HH", resp_data[:4])
                            if opcode == OPCODE_ACK and ack_block == 0:
                                server_tid = sender  # Ephemeral port acquired
                                logger.debug(f"Connected to router TID {server_tid}")
                                break
                            elif opcode == OPCODE_ERROR:
                                err_code = ack_block
                                err_msg = resp_data[4:].decode("ascii", "replace").rstrip("\x00")
                                raise TftpError(err_code, err_msg)
                    except socket.timeout:
                        cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                        logger.warning(f"WRQ attempt {attempt}/{self.retries} timed out. Retrying with timeout {cur_timeout:.1f}s...")
                        break
                    except (ConnectionResetError, OSError):
                        # Destination port closed or router still booting (WSAECONNRESET / 10054 on Windows)
                        if time_left > 0.1:
                            time.sleep(0.1)
                            # Re-probe WRQ to detect when router bootloader opens port 69
                            try:
                                sock.sendto(wrq_packet, (self.host, self.port))
                            except OSError:
                                pass
                            continue
                        else:
                            if time_left > 0:
                                time.sleep(time_left)
                            cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                            logger.warning(f"WRQ attempt {attempt}/{self.retries} timed out. Retrying with timeout {cur_timeout:.1f}s...")
                            break
                if server_tid:
                    break

            if not server_tid:
                pb.finish(success=False)
                raise TimeoutError(f"Router at {self.host}:{self.port} did not respond to TFTP WRQ after {self.retries} attempts.")

            # Step 2: Transmit DATA blocks
            offset = 0
            block_num = 1
            cur_timeout = self.timeout

            while True:
                chunk = payload[offset : offset + self.block_size]
                chunk_len = len(chunk)

                # Construct DATA packet: opcode 3 + block_num (16-bit) + chunk
                data_packet = struct.pack(">HH", OPCODE_DATA, block_num) + chunk

                # Transmit block with retry loop
                acked = False
                cur_timeout = self.timeout
                for attempt in range(1, self.retries + 1):
                    try:
                        sock.sendto(data_packet, server_tid)
                    except OSError as e:
                        logger.debug(f"Block {block_num} sendto failed on attempt {attempt}: {e}")

                    start_attempt = time.time()
                    while True:
                        time_left = cur_timeout - (time.time() - start_attempt)
                        if time_left <= 0:
                            cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                            logger.debug(f"Block {block_num} attempt {attempt}/{self.retries} timed out.")
                            break
                        try:
                            sock.settimeout(time_left)
                            ack_data, sender = sock.recvfrom(1024)
                            if sender != server_tid:
                                # If duplicate from port 69 or another TID, ignore
                                continue
                            if len(ack_data) >= 4:
                                opcode, ack_block = struct.unpack(">HH", ack_data[:4])
                                if opcode == OPCODE_ACK:
                                    if ack_block == block_num:
                                        acked = True
                                        break
                                    elif ack_block == ((block_num - 1) & 0xFFFF):
                                        # Delayed duplicate ACK from previous block, decouple from retry attempts
                                        continue
                                elif opcode == OPCODE_ERROR:
                                    err_code = ack_block
                                    err_msg = ack_data[4:].decode("ascii", "replace").rstrip("\x00")
                                    raise TftpError(err_code, err_msg)
                        except (socket.timeout, ConnectionResetError, OSError):
                            cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                            logger.debug(f"Block {block_num} attempt {attempt}/{self.retries} timed out.")
                            break
                    if acked:
                        break

                if not acked:
                    pb.finish(success=False)
                    raise TimeoutError(f"Transfer timed out on block {block_num} ({offset} bytes transferred).")

                offset += chunk_len
                pb.update(offset)
                if progress_cb:
                    progress_cb(offset, total_len)

                # RFC 1350 Termination: chunk < block_size
                if chunk_len < self.block_size:
                    break

                # Advance block number with 16-bit rollover
                block_num = (block_num + 1) & 0xFFFF

            pb.update(total_len, force=True)
            pb.finish(success=True)
            return True

        finally:
            sock.close()


class TftpServer:
    """
    RFC 1350 TFTP Server implementation.
    Listens on UDP port 69, serving firmware images to clients issuing RRQ.
    """
    def __init__(self, bind_ip="0.0.0.0", bind_port=69, default_payload=None,
                 served_file=None, block_size=DEFAULT_BLOCK_SIZE, timeout=DEFAULT_TIMEOUT,
                 retries=DEFAULT_RETRIES, quiet=False):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.default_payload = default_payload
        self.served_file = served_file
        self.block_size = block_size
        self.timeout = timeout
        self.retries = retries
        self.quiet = quiet
        self.running = False
        self.server_sock = None
        self._thread = None
        self.transfer_completed = threading.Event()
        self.last_transfer_success = False

    def start_background(self):
        """Starts server in a background daemon thread."""
        self.running = True
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        logger.info(f"TFTP Server background listener started on {self.bind_ip}:{self.bind_port}")

    def stop(self):
        """Stops the server listener."""
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("TFTP Server stopped.")

    def run(self):
        """Main server listening loop."""
        self.server_sock = create_udp_socket()
        try:
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass

        try:
            self.server_sock.bind((self.bind_ip, self.bind_port))
        except OSError as e:
            logger.error(f"Cannot bind TFTP Server to {self.bind_ip}:{self.bind_port}: {e}")
            self.running = False
            return

        self.server_sock.settimeout(1.0)
        logger.info(f"TFTP Server listening on {self.bind_ip}:{self.bind_port}")

        while self.running:
            try:
                req_data, client_addr = self.server_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(req_data) < 4:
                continue

            opcode = struct.unpack(">H", req_data[:2])[0]

            if opcode == OPCODE_RRQ:
                # Handle Read Request (Client wants to download from server)
                filename, mode = self._parse_rq(req_data[2:])
                logger.info(f"Received TFTP RRQ from {client_addr} for '{filename}' (mode: {mode})")
                threading.Thread(
                    target=self._handle_rrq,
                    args=(client_addr, filename),
                    daemon=True
                ).start()

            elif opcode == OPCODE_WRQ:
                # Handle Write Request (Client wants to upload to server)
                filename, mode = self._parse_rq(req_data[2:])
                logger.info(f"Received TFTP WRQ from {client_addr} for '{filename}'")
                threading.Thread(
                    target=self._handle_wrq,
                    args=(client_addr, filename),
                    daemon=True
                ).start()

            else:
                # Send illegal operation error
                err_pkt = struct.pack(">HH", OPCODE_ERROR, ERR_ILLEGAL_OPERATION) + b"Illegal TFTP operation\x00"
                self.server_sock.sendto(err_pkt, client_addr)

    def _parse_rq(self, data):
        """Extracts filename and mode from request payload."""
        parts = data.split(b"\x00")
        filename = parts[0].decode("ascii", "replace") if len(parts) > 0 else ""
        mode = parts[1].decode("ascii", "replace").lower() if len(parts) > 1 else "octet"
        return filename, mode

    def _get_payload(self, filename):
        """Resolves requested payload either from file or default in-memory buffer."""
        if self.default_payload is not None:
            return self.default_payload
        # Strictly reject path traversal attempts or directory requests
        if (
            not filename
            or ".." in filename
            or "/" in filename
            or "\\" in filename
            or os.path.isabs(filename)
            or filename in (".", "..")
        ):
            return None
        if self.served_file and os.path.isfile(self.served_file):
            try:
                with open(self.served_file, "rb") as f:
                    return f.read()
            except (OSError, PermissionError):
                return None
        if os.path.isfile(filename):
            try:
                with open(filename, "rb") as f:
                    return f.read()
            except (OSError, PermissionError):
                return None
        return None

    def _handle_rrq(self, client_addr, filename):
        """Handles single RRQ transfer on a dedicated ephemeral UDP socket."""
        try:
            payload = self._get_payload(filename)
        except (OSError, PermissionError, Exception) as e:
            logger.warning(f"Error accessing payload for '{filename}': {e}")
            payload = None
        sess_sock = create_udp_socket()
        sess_sock.settimeout(self.timeout)

        try:
            if payload is None:
                err_pkt = struct.pack(">HH", OPCODE_ERROR, ERR_FILE_NOT_FOUND) + b"File not found\x00"
                sess_sock.sendto(err_pkt, client_addr)
                logger.warning(f"RRQ file not found: '{filename}' for {client_addr}")
                return

            total_len = len(payload)
            logger.info(f"Serving {total_len} bytes to {client_addr}")
            pb = ProgressBar(total_len, prefix=f"TFTP RRQ Serve ({filename})", quiet=self.quiet)

            offset = 0
            block_num = 1

            while True:
                chunk = payload[offset : offset + self.block_size]
                chunk_len = len(chunk)
                data_pkt = struct.pack(">HH", OPCODE_DATA, block_num) + chunk

                acked = False
                cur_timeout = self.timeout
                for attempt in range(1, self.retries + 1):
                    try:
                        sess_sock.sendto(data_pkt, client_addr)
                    except OSError:
                        return
                    try:
                        sess_sock.settimeout(cur_timeout)
                        ack_data, sender = sess_sock.recvfrom(516)
                        if sender != client_addr:
                            continue
                        if len(ack_data) >= 4:
                            opcode, ack_block = struct.unpack(">HH", ack_data[:4])
                            if opcode == OPCODE_ACK and ack_block == block_num:
                                acked = True
                                break
                            elif opcode == OPCODE_ERROR:
                                err_code = ack_block
                                err_msg = ack_data[4:].decode("ascii", "replace").rstrip("\x00")
                                logger.error(f"Client {client_addr} error {err_code}: {err_msg}")
                                pb.finish(success=False)
                                return
                    except socket.timeout:
                        cur_timeout = min(MAX_TIMEOUT, cur_timeout * 1.5)
                    except OSError:
                        return

                if not acked:
                    logger.error(f"RRQ transfer to {client_addr} timed out at block {block_num}")
                    pb.finish(success=False)
                    return

                offset += chunk_len
                pb.update(offset)

                if chunk_len < self.block_size:
                    break

                block_num = (block_num + 1) & 0xFFFF

            pb.update(total_len, force=True)
            pb.finish(success=True)
            self.last_transfer_success = True
            self.transfer_completed.set()

        finally:
            sess_sock.close()

    def _handle_wrq(self, client_addr, filename):
        """Handles incoming WRQ, acknowledging block 0 and receiving blocks."""
        sess_sock = create_udp_socket()
        sess_sock.settimeout(self.timeout)
        received_data = bytearray()
        clean_finish = False

        try:
            # Send ACK 0
            ack_0 = struct.pack(">HH", OPCODE_ACK, 0)
            sess_sock.sendto(ack_0, client_addr)

            expected_block = 1
            consecutive_timeouts = 0
            while True:
                try:
                    data_pkt, sender = sess_sock.recvfrom(self.block_size + 4)
                    if sender != client_addr:
                        continue
                    if len(data_pkt) < 4:
                        continue
                    consecutive_timeouts = 0
                    opcode, block_num = struct.unpack(">HH", data_pkt[:4])
                    if opcode == OPCODE_DATA and block_num == expected_block:
                        chunk = data_pkt[4:]
                        received_data.extend(chunk)

                        # Send ACK
                        ack_pkt = struct.pack(">HH", OPCODE_ACK, block_num)
                        sess_sock.sendto(ack_pkt, client_addr)

                        expected_block = (expected_block + 1) & 0xFFFF

                        if len(chunk) < self.block_size:
                            # Transfer complete
                            clean_finish = True
                            break
                    elif opcode == OPCODE_ERROR:
                        logger.warning(f"WRQ from {client_addr} aborted with ERROR packet")
                        break
                except socket.timeout:
                    consecutive_timeouts += 1
                    if consecutive_timeouts > self.retries:
                        logger.warning(f"WRQ from {client_addr} timed out after {self.retries} retransmissions")
                        break
                    # Resend last ACK
                    last_ack = (expected_block - 1) & 0xFFFF
                    try:
                        sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, last_ack), client_addr)
                    except OSError:
                        break
                except OSError:
                    break

            if clean_finish:
                logger.info(f"WRQ from {client_addr} completed successfully, received {len(received_data)} bytes")
            else:
                logger.warning(f"WRQ from {client_addr} aborted or timed out after receiving {len(received_data)} bytes")
            self.last_transfer_success = clean_finish
            self.transfer_completed.set()
        finally:
            sess_sock.close()


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous TFTP Emergency Engine for Tenda AC10 V1.0"
    )
    parser.add_argument("--mode", choices=["client", "server", "dual"], default="client",
                        help="Operating mode: client (WRQ push), server (RRQ pull), dual (both)")
    parser.add_argument("--ip", default="192.168.1.6",
                        help="Target IP for client, or bind IP for server (default: 192.168.1.6)")
    parser.add_argument("--port", type=int, default=69,
                        help="UDP port (default: 69)")
    parser.add_argument("--file", required=True,
                        help="Firmware file to upload (client) or serve (server)")
    parser.add_argument("--remote-name", default="firmware.bin",
                        help="Remote filename in TFTP request (default: firmware.bin)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"Base socket timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                        help=f"Retries per block (default: {DEFAULT_RETRIES})")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress terminal progress bar")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not os.path.exists(args.file):
        print(f"[-] Error: File not found: {args.file}")
        sys.exit(1)

    if args.mode == "client":
        client = TftpClient(host=args.ip, port=args.port, timeout=args.timeout,
                            retries=args.retries, quiet=args.quiet)
        try:
            client.push_file(args.file, remote_filename=args.remote_name)
            print("[+] TFTP Upload Completed Successfully!")
        except Exception as e:
            print(f"[-] TFTP Client Error: {e}")
            sys.exit(1)

    elif args.mode == "server":
        server = TftpServer(bind_ip=args.ip, bind_port=args.port, served_file=args.file,
                            timeout=args.timeout, retries=args.retries, quiet=args.quiet)
        print(f"[*] Starting TFTP Server on {args.ip}:{args.port} serving '{args.file}'...")
        print("[*] Press Ctrl+C to terminate.")
        try:
            server.run()
        except KeyboardInterrupt:
            print("\n[*] Server stopped by user.")

    elif args.mode == "dual":
        # Launch server in background, then attempt client push
        server = TftpServer(bind_ip="0.0.0.0", bind_port=args.port, served_file=args.file,
                            timeout=args.timeout, retries=args.retries, quiet=args.quiet)
        server.start_background()
        client = TftpClient(host=args.ip, port=args.port, timeout=args.timeout,
                            retries=args.retries, quiet=args.quiet)
        print("[*] Dual-mode active: TFTP Server listening on port 69, attempting Client WRQ push...")
        try:
            client.push_file(args.file, remote_filename=args.remote_name)
            print("[+] TFTP Client Push Succeeded!")
        except Exception as e:
            print(f"[*] Client push did not engage ({e}); remaining in Server mode...")
            try:
                while server.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        finally:
            server.stop()


if __name__ == "__main__":
    main()
