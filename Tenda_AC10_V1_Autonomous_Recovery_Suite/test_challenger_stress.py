#!/usr/bin/env python3
"""
Challenger Adversarial Stress Test Suite
Target: tftp_emergency_engine.py in K:\\aoe4_dlc\\Tenda_AC10_V1_Autonomous_Recovery_Suite\\
Author: challenger_o21_iter2_1
"""

import os
import sys
import time
import socket
import struct
import hashlib
import unittest
import threading

SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from tftp_emergency_engine import (
    TftpClient, TftpServer, TftpError,
    OPCODE_RRQ, OPCODE_WRQ, OPCODE_DATA, OPCODE_ACK, OPCODE_ERROR
)


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestChallengerStress(unittest.TestCase):
    """Rigorous empirical challenge of tftp_emergency_engine.py."""

    # -------------------------------------------------------------------------
    # TEST 1: CLOSED UDP PORT TIMING & RETRY BURNING
    # -------------------------------------------------------------------------
    def test_01_closed_port_retry_duration(self):
        """
        Stress-test retry backoff against closed UDP port (Winsock WSAECONNRESET).
        With retries=5 and timeout=1.0s, the client should back off and not exhaust
        all 5 retries in < 0.1s.
        """
        port = get_free_port()
        client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=5, quiet=True)

        t0 = time.time()
        try:
            client.push_bytes(b"probe", remote_filename="probe.bin")
        except TimeoutError:
            pass
        elapsed = time.time() - t0

        print(f"\n[STRESS 1] Closed port probe elapsed: {elapsed:.4f}s (configured timeout=1.0s, retries=5)")
        # If it burns retries without waiting on WSAECONNRESET, elapsed is ~0.001s
        if elapsed < 0.1:
            print("[-] VULNERABILITY DETECTED: WSAECONNRESET instantly burned 5 retries in < 0.1s!")
        self.assertGreaterEqual(elapsed, 0.1,
                                f"Retries burned through instantly on WSAECONNRESET ({elapsed:.4f}s < 0.1s)!")

    def test_02_delayed_router_boot_simulation(self):
        """
        Simulate real-world bootloader race condition:
        User holds reset and powers on router. The router bootloader takes 0.5s to open UDP 69.
        Client has timeout=1.5s, retries=5 (configured to wait up to 7.5s+).
        Verify whether client successfully connects or prematurely fails in < 0.5s.
        """
        port = get_free_port()

        def delayed_server():
            time.sleep(0.5)
            srv = TftpServer(bind_ip="127.0.0.1", bind_port=port, default_payload=b"ok", quiet=True)
            srv.start_background()
            time.sleep(2.0)
            srv.stop()

        t = threading.Thread(target=delayed_server, daemon=True)
        t.start()

        client = TftpClient(host="127.0.0.1", port=port, timeout=1.5, retries=5, quiet=True)
        t0 = time.time()
        connected = False
        error_msg = ""
        try:
            connected = client.push_bytes(b"data", remote_filename="delayed.bin")
        except Exception as e:
            error_msg = str(e)
        elapsed = time.time() - t0

        print(f"\n[STRESS 2] Delayed router boot (0.5s): connected={connected}, elapsed={elapsed:.4f}s, error='{error_msg}'")
        self.assertTrue(connected, f"Client failed to connect to router delayed by 0.5s: {error_msg}")

    # -------------------------------------------------------------------------
    # TEST 2: DELAYED DUPLICATE ACK RESILIENCE
    # -------------------------------------------------------------------------
    def test_03_delayed_duplicate_acks_multi_block(self):
        """
        Send a multi-block payload where server sends duplicate ACKs for block 1,
        block 2, and block 3. Verify transfer finishes with 100% byte integrity.
        """
        port = get_free_port()
        payload = b"X" * 1500  # 3 blocks: 512, 512, 476
        received = bytearray()

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_sock.bind(("127.0.0.1", port))
        server_sock.settimeout(2.0)

        def dup_server():
            req, client_addr = server_sock.recvfrom(1024)
            sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sess.settimeout(2.0)
            sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

            expected_block = 1
            while True:
                pkt, sender = sess.recvfrom(1024)
                op, blk = struct.unpack(">HH", pkt[:4])
                chunk = pkt[4:]
                if blk == expected_block:
                    received.extend(chunk)
                    # Send correct ACK
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    # Send duplicate ACK of previous block immediately after
                    prev_blk = (blk - 1) & 0xFFFF
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, prev_blk), sender)
                    expected_block = (expected_block + 1) & 0xFFFF
                    if len(chunk) < 512:
                        break
            sess.close()

        t = threading.Thread(target=dup_server, daemon=True)
        t.start()
        time.sleep(0.05)

        client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=5, quiet=True)
        res = client.push_bytes(payload, remote_filename="dup_multi.bin")
        t.join(timeout=3.0)
        server_sock.close()

        self.assertTrue(res)
        self.assertEqual(len(payload), len(received))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), hashlib.sha256(received).hexdigest())
        print(f"\n[STRESS 3] Duplicate ACK flood handled successfully. Transferred {len(received)} bytes.")

    # -------------------------------------------------------------------------
    # TEST 3: PATH TRAVERSAL AND DIRECTORY REQUESTS
    # -------------------------------------------------------------------------
    def test_04_path_traversal_relative_and_absolute(self):
        """
        Verify RRQ path traversal attempts are strictly rejected with ERROR opcode.
        """
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        traversal_attempts = [
            r"..\..\..\..\Windows\win.ini",
            r"/etc/passwd",
            r"..\tftp_emergency_engine.py",
            r"C:\Windows\System32\drivers\etc\hosts",
            r"....//....//something"
        ]

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)

        for path in traversal_attempts:
            rrq = struct.pack(">H", OPCODE_RRQ) + path.encode("ascii") + b"\x00octet\x00"
            sock.sendto(rrq, ("127.0.0.1", port))
            try:
                resp, _ = sock.recvfrom(1024)
                opcode, err_code = struct.unpack(">HH", resp[:4])
                self.assertEqual(opcode, OPCODE_ERROR, f"Path traversal '{path}' did not return ERROR opcode!")
            except socket.timeout:
                self.fail(f"Path traversal '{path}' caused server to hang/crash without response!")

        sock.close()
        server.stop()
        print(f"\n[STRESS 4] Path traversal tests passed: all {len(traversal_attempts)} paths blocked with ERROR.")

    def test_05_directory_rrq_unhandled_exception(self):
        """
        Stress test: Requesting an existing directory via RRQ.
        Checks whether server crashes with PermissionError or returns ERROR opcode.
        """
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        # Existing directory: 'backups' in SUITE_DIR or '.' or '..'
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)

        # Send RRQ for 'backups' or '.'
        rrq = struct.pack(">H", OPCODE_RRQ) + b".\x00octet\x00"
        sock.sendto(rrq, ("127.0.0.1", port))

        resp_received = False
        try:
            resp, _ = sock.recvfrom(1024)
            opcode, err_code = struct.unpack(">HH", resp[:4])
            self.assertEqual(opcode, OPCODE_ERROR)
            resp_received = True
            print("\n[STRESS 5] Server handled directory RRQ and returned ERROR opcode.")
        except socket.timeout:
            print("\n[-] VULNERABILITY DETECTED: Server thread crashed on directory RRQ without response!")

        sock.close()
        server.stop()
        self.assertTrue(resp_received, "Server thread hung or crashed when handling directory RRQ")

    # -------------------------------------------------------------------------
    # TEST 4: MULTI-MEGABYTE TRANSFER & 100% SHA-256 INTEGRITY
    # -------------------------------------------------------------------------
    def test_06_large_loopback_transfer_sha256(self):
        """
        Push 7,588,884 bytes (exact stock recovery firmware size) over loopback.
        Verify 100% SHA-256 byte integrity across 14,823 blocks and rollover.
        """
        port = get_free_port()
        payload = bytes((i * 37 + 13) % 256 for i in range(7588884))
        expected_hash = hashlib.sha256(payload).hexdigest()

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_sock.bind(("127.0.0.1", port))
        server_sock.settimeout(2.0)

        received_bytes = bytearray()

        def sink_server():
            req, client_addr = server_sock.recvfrom(1024)
            sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sess.settimeout(2.0)
            sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

            expected_block = 1
            while True:
                pkt, sender = sess.recvfrom(1024)
                op, blk = struct.unpack(">HH", pkt[:4])
                chunk = pkt[4:]
                if blk == expected_block:
                    received_bytes.extend(chunk)
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    expected_block = (expected_block + 1) & 0xFFFF
                    if len(chunk) < 512:
                        break
                else:
                    last_blk = (expected_block - 1) & 0xFFFF
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, last_blk), sender)
            sess.close()

        t = threading.Thread(target=sink_server, daemon=True)
        t.start()
        time.sleep(0.05)

        client = TftpClient(host="127.0.0.1", port=port, timeout=2.0, retries=5, quiet=True)
        t0 = time.time()
        res = client.push_bytes(payload, remote_filename="stock_recovery.bin")
        elapsed = time.time() - t0
        t.join(timeout=5.0)
        server_sock.close()

        self.assertTrue(res)
        self.assertEqual(len(payload), len(received_bytes))
        actual_hash = hashlib.sha256(received_bytes).hexdigest()
        self.assertEqual(expected_hash, actual_hash)
        rate_mb = (len(payload) / (1024 * 1024)) / elapsed
        print(f"\n[STRESS 6] 7.58 MB transfer verified: SHA256={actual_hash} ({elapsed:.2f}s, {rate_mb:.1f} MB/s)")

    # -------------------------------------------------------------------------
    # TEST 5: ABORTED WRQ SERVER SUCCESS FLAG DEFECT
    # -------------------------------------------------------------------------
    def test_07_aborted_wrq_should_not_set_success(self):
        """
        Verify that if an incoming WRQ transfer is aborted midway (by client sending
        OPCODE_ERROR or timing out), server does NOT set last_transfer_success = True.
        """
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, timeout=0.2, quiet=True)
        server.start_background()
        time.sleep(0.05)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        wrq = struct.pack(">H", OPCODE_WRQ) + b"test.bin\x00octet\x00"
        sock.sendto(wrq, ("127.0.0.1", port))

        ack0, sess_addr = sock.recvfrom(1024)

        # Abort transfer immediately with ERROR opcode
        err_pkt = struct.pack(">HH", OPCODE_ERROR, 0) + b"Transfer cancelled\x00"
        sock.sendto(err_pkt, sess_addr)
        time.sleep(0.1)

        print(f"\n[STRESS 7] Aborted WRQ: server.last_transfer_success={server.last_transfer_success}")
        if server.last_transfer_success:
            print("[-] VULNERABILITY DETECTED: Aborted WRQ transfer falsely marked as successful!")
        self.assertFalse(server.last_transfer_success,
                         "TftpServer must NOT set last_transfer_success=True when transfer is aborted!")
        server.stop()
        sock.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
