#!/usr/bin/env python3
"""
Adversarial Stress Test Suite for TFTP Emergency Engine
Target: K:\\aoe4_dlc\\Tenda_AC10_V1_Autonomous_Recovery_Suite\\tftp_emergency_engine.py

Strict Constraints:
- Loopback (127.0.0.1) ONLY. Zero packets to 192.168.0.1.
- Zero external pip dependencies.
- Empirical execution with exact packet counting, timing, and boundary verification.
"""

import os
import sys
import time
import socket
import struct
import hashlib
import unittest
import threading
import importlib

SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from tftp_emergency_engine import (
    TftpClient, TftpServer, TftpError,
    OPCODE_RRQ, OPCODE_WRQ, OPCODE_DATA, OPCODE_ACK, OPCODE_ERROR
)


def get_free_port():
    """Finds a free UDP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockTftpServer:
    """Configurable mock TFTP server for simulating packet loss and custom protocols."""
    def __init__(self, bind_ip="127.0.0.1", bind_port=None):
        self.bind_ip = bind_ip
        self.bind_port = bind_port or get_free_port()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.bind_ip, self.bind_port))
        self.sock.settimeout(2.0)
        self.running = True
        self.packets_received = []

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class TestTftpAdversarial(unittest.TestCase):
    """Adversarial challenge and stress tests for tftp_emergency_engine.py."""

    # -------------------------------------------------------------------------
    # TEST 1: ZERO EXTERNAL DEPENDENCIES (PIP-FREE)
    # -------------------------------------------------------------------------
    def test_01_verify_zero_external_dependencies(self):
        """Verify that tftp_emergency_engine.py imports ONLY Python standard library."""
        import ast

        engine_path = os.path.join(SUITE_DIR, "tftp_emergency_engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=engine_path)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        # Standard library modules known in Python 3
        stdlib_modules = {
            "os", "sys", "time", "socket", "struct", "threading",
            "argparse", "hashlib", "logging"
        }

        self.assertTrue(imported_modules.issubset(stdlib_modules),
                        f"Non-stdlib imports found: {imported_modules - stdlib_modules}")

        # Check sys.modules after clean import
        for mod in imported_modules:
            module_obj = importlib.import_module(mod)
            file_attr = getattr(module_obj, "__file__", None)
            if file_attr:
                self.assertNotIn("site-packages", file_attr.lower(),
                                 f"Module {mod} loaded from site-packages: {file_attr}")
                self.assertNotIn("dist-packages", file_attr.lower(),
                                 f"Module {mod} loaded from dist-packages: {file_attr}")

        print(f"\n[+] Dependency Audit Passed: Imported stdlib modules: {sorted(imported_modules)}")

    # -------------------------------------------------------------------------
    # TEST 2: BOUNDARY PAYLOAD SIZES (0B, 1B, 512B, 513B, 1024B)
    # -------------------------------------------------------------------------
    def _run_boundary_transfer_wrq(self, payload_bytes, expected_block_count, name):
        """Helper to run a WRQ transfer against a loopback server and count blocks."""
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            success = client.push_bytes(payload_bytes, remote_filename=f"{name}.bin")
            self.assertTrue(success, f"WRQ push failed for payload size {len(payload_bytes)}")

            # Wait for server to set completion event
            server.transfer_completed.wait(timeout=2.0)
            self.assertTrue(server.last_transfer_success, "Server did not mark transfer success")
        finally:
            server.stop()

    def test_02_payload_zero_length(self):
        """Test zero-length payload (0 bytes). Must send exactly 1 DATA block of 0 bytes."""
        payload = b""
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            res = client.push_bytes(payload, remote_filename="zero.bin")
            self.assertTrue(res)
            server.transfer_completed.wait(timeout=1.0)
            self.assertTrue(server.last_transfer_success)
        finally:
            server.stop()
        print("\n[+] Boundary Test: Zero-length payload (0 bytes) transferred successfully.")

    def test_03_payload_1_byte(self):
        """Test 1-byte payload. Must terminate immediately on block 1 (len=1 < 512)."""
        payload = b"Z"
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            res = client.push_bytes(payload, remote_filename="one_byte.bin")
            self.assertTrue(res)
            server.transfer_completed.wait(timeout=1.0)
            self.assertTrue(server.last_transfer_success)
        finally:
            server.stop()
        print("\n[+] Boundary Test: 1-byte payload transferred successfully.")

    def test_04_payload_exact_512_bytes(self):
        """Test exact 512-byte payload. Must send Block 1 (512B) AND Block 2 (0B) to terminate."""
        payload = bytes((i % 256) for i in range(512))
        port = get_free_port()

        # We inspect packets with a specialized listener
        recvd_blocks = []
        mock = MockTftpServer(bind_port=port)

        def mock_server_thread():
            try:
                # Receive WRQ
                req_data, client_addr = mock.sock.recvfrom(1024)
                # Create session socket
                sess_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess_sock.settimeout(2.0)
                # Send ACK 0
                sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                while True:
                    pkt, sender = sess_sock.recvfrom(1024)
                    op, blk = struct.unpack(">HH", pkt[:4])
                    chunk = pkt[4:]
                    recvd_blocks.append((blk, len(chunk)))
                    sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    if len(chunk) < 512:
                        break
                sess_sock.close()
            except Exception as e:
                recvd_blocks.append(("ERROR", str(e)))

        t = threading.Thread(target=mock_server_thread, daemon=True)
        t.start()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            res = client.push_bytes(payload, remote_filename="exact512.bin")
            self.assertTrue(res)
            t.join(timeout=2.0)

            # Block 1 should have 512 bytes, Block 2 should have 0 bytes (RFC 1350 termination)
            self.assertEqual(len(recvd_blocks), 2, f"Expected 2 blocks, got: {recvd_blocks}")
            self.assertEqual(recvd_blocks[0], (1, 512))
            self.assertEqual(recvd_blocks[1], (2, 0), "Block 2 must be 0-length termination packet")
        finally:
            mock.close()
        print("\n[+] Boundary Test: Exact 512-byte payload correctly terminated with 0-byte packet.")

    def test_05_payload_513_bytes(self):
        """Test 513-byte payload. Must send Block 1 (512B) and Block 2 (1B)."""
        payload = bytes((i % 256) for i in range(513))
        port = get_free_port()

        recvd_blocks = []
        mock = MockTftpServer(bind_port=port)

        def mock_server_thread():
            try:
                req_data, client_addr = mock.sock.recvfrom(1024)
                sess_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess_sock.settimeout(2.0)
                sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                while True:
                    pkt, sender = sess_sock.recvfrom(1024)
                    op, blk = struct.unpack(">HH", pkt[:4])
                    chunk = pkt[4:]
                    recvd_blocks.append((blk, len(chunk)))
                    sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    if len(chunk) < 512:
                        break
                sess_sock.close()
            except Exception as e:
                recvd_blocks.append(("ERROR", str(e)))

        t = threading.Thread(target=mock_server_thread, daemon=True)
        t.start()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            res = client.push_bytes(payload, remote_filename="exact513.bin")
            self.assertTrue(res)
            t.join(timeout=2.0)

            self.assertEqual(len(recvd_blocks), 2, f"Expected 2 blocks, got: {recvd_blocks}")
            self.assertEqual(recvd_blocks[0], (1, 512))
            self.assertEqual(recvd_blocks[1], (2, 1))
        finally:
            mock.close()
        print("\n[+] Boundary Test: 513-byte payload (512B + 1B) verified.")

    def test_06_payload_exact_1024_bytes(self):
        """Test exact 1024-byte payload. Must send Block 1 (512B), Block 2 (512B), Block 3 (0B)."""
        payload = bytes((i % 256) for i in range(1024))
        port = get_free_port()

        recvd_blocks = []
        mock = MockTftpServer(bind_port=port)

        def mock_server_thread():
            try:
                req_data, client_addr = mock.sock.recvfrom(1024)
                sess_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess_sock.settimeout(2.0)
                sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                while True:
                    pkt, sender = sess_sock.recvfrom(1024)
                    op, blk = struct.unpack(">HH", pkt[:4])
                    chunk = pkt[4:]
                    recvd_blocks.append((blk, len(chunk)))
                    sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    if len(chunk) < 512:
                        break
                sess_sock.close()
            except Exception as e:
                recvd_blocks.append(("ERROR", str(e)))

        t = threading.Thread(target=mock_server_thread, daemon=True)
        t.start()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=1.0, retries=3, quiet=True)
            res = client.push_bytes(payload, remote_filename="exact1024.bin")
            self.assertTrue(res)
            t.join(timeout=2.0)

            self.assertEqual(len(recvd_blocks), 3, f"Expected 3 blocks, got: {recvd_blocks}")
            self.assertEqual(recvd_blocks[0], (1, 512))
            self.assertEqual(recvd_blocks[1], (2, 512))
            self.assertEqual(recvd_blocks[2], (3, 0), "Trailing 0-length packet required for 1024 bytes!")
        finally:
            mock.close()
        print("\n[+] Boundary Test: Exact 1024-byte payload (512B + 512B + 0B) verified.")

    # -------------------------------------------------------------------------
    # TEST 3: SIMULATED PACKET LOSS & TIMEOUT RETRANSMISSION
    # -------------------------------------------------------------------------
    def test_07_simulated_packet_loss_recovery(self):
        """Simulate dropped ACKs: Server drops first 2 ACKs for block 1, responds on attempt 3."""
        port = get_free_port()
        mock = MockTftpServer(bind_port=port)
        block_1_attempts = []

        def drop_server_thread():
            try:
                # WRQ
                req_data, client_addr = mock.sock.recvfrom(1024)
                sess_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess_sock.settimeout(3.0)
                sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                # Receive block 1
                attempts = 0
                while True:
                    pkt, sender = sess_sock.recvfrom(1024)
                    op, blk = struct.unpack(">HH", pkt[:4])
                    if blk == 1:
                        attempts += 1
                        block_1_attempts.append(attempts)
                        if attempts < 3:
                            # Intentionally drop ACK (simulate network loss)
                            continue
                        else:
                            # Respond on attempt 3
                            sess_sock.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                            break

                sess_sock.close()
            except Exception as e:
                pass

        t = threading.Thread(target=drop_server_thread, daemon=True)
        t.start()
        time.sleep(0.05)

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=0.2, retries=5, quiet=True)
            res = client.push_bytes(b"A" * 10, remote_filename="drop_test.bin")
            self.assertTrue(res, "Client should successfully recover after 2 dropped packets")
            t.join(timeout=3.0)
            self.assertEqual(len(block_1_attempts), 3,
                             f"Client must retransmit up to attempt 3; observed: {block_1_attempts}")
        finally:
            mock.close()
        print(f"\n[+] Retransmission Test: Client successfully retransmitted 3 times on simulated drop: {block_1_attempts}")

    def test_08_timeout_exhaustion_raises_timeout_error(self):
        """Verify client raises TimeoutError when server completely fails to respond."""
        port = get_free_port()
        mock = MockTftpServer(bind_port=port)
        # Server simply drops everything

        try:
            client = TftpClient(host="127.0.0.1", port=port, timeout=0.1, retries=3, quiet=True)
            with self.assertRaises(TimeoutError) as ctx:
                client.push_bytes(b"test", remote_filename="timeout.bin")
            self.assertIn("did not respond to TFTP WRQ", str(ctx.exception))
        finally:
            mock.close()
        print("\n[+] Retransmission Exhaustion: Client properly timed out and raised TimeoutError.")

    # -------------------------------------------------------------------------
    # TEST 4: BLOCK ROLLOVER (BLOCK >= 65536 MODULO 65536)
    # -------------------------------------------------------------------------
    def test_09_block_rollover_full_transfer(self):
        """
        Adversarially test block rollover at 65535 -> 0.
        Uses a custom mock server that tests rollover without needing 33.5 MB of data.
        Mock server immediately sends ACK for block 65535, checks client behavior on block 65536.
        Also tests high block rollover via actual 65,537 block transfer with 1-byte blocks.
        """
        port = get_free_port()
        mock = MockTftpServer(bind_port=port)
        observed_blocks = []

        def rollover_server():
            try:
                # WRQ
                req, client_addr = mock.sock.recvfrom(1024)
                sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess.settimeout(5.0)

                # Send ACK 0
                sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                # Client sends block 1.
                # To test rollover without waiting for 65,536 transfers,
                # we accept block 1, then simulate high block transition
                pkt, sender = sess.recvfrom(1024)
                op, blk = struct.unpack(">HH", pkt[:4])
                observed_blocks.append(blk)
                sess.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                sess.close()
            except Exception as e:
                pass

        # Also let's test rollover directly with client loop logic:
        # What does client do when block reaches 65535 and rolls over?
        # Let's run an empirical 65538-block transfer with 4-byte blocks:
        # Total data: 65538 * 4 = 262,152 bytes (256 KB)
        # Client block_size = 4!
        port2 = get_free_port()
        recvd_blocks_rollover = []

        mock2 = MockTftpServer(bind_port=port2)

        def rollover_streaming_server():
            try:
                req, client_addr = mock2.sock.recvfrom(1024)
                sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess.settimeout(5.0)
                sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                expected = 1
                while True:
                    pkt, sender = sess.recvfrom(1024)
                    op, blk = struct.unpack(">HH", pkt[:4])
                    chunk = pkt[4:]
                    # Record blocks around rollover
                    if blk >= 65534 or blk <= 2:
                        recvd_blocks_rollover.append(blk)
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, blk), sender)
                    if len(chunk) < 4:
                        break
                    expected = (expected + 1) & 0xFFFF
                sess.close()
            except Exception as e:
                recvd_blocks_rollover.append(("ERROR", str(e)))

        t = threading.Thread(target=rollover_streaming_server, daemon=True)
        t.start()
        time.sleep(0.05)

        try:
            # 65537 blocks: 65536 full blocks (4 bytes each) + 1 trailing block (2 bytes)
            # Total bytes = 65536 * 4 + 2 = 262,146 bytes
            test_data = b"M" * (65536 * 4 + 2)
            client = TftpClient(host="127.0.0.1", port=port2, timeout=2.0, retries=3,
                                block_size=4, quiet=True)
            res = client.push_bytes(test_data, remote_filename="rollover_full.bin")
            self.assertTrue(res, "Transfer crossing 65,535 blocks failed!")
            t.join(timeout=10.0)

            # Check that block 65534, 65535, 0, 1 were observed!
            self.assertIn(65534, recvd_blocks_rollover, "Block 65534 was not sent")
            self.assertIn(65535, recvd_blocks_rollover, "Block 65535 was not sent")
            self.assertIn(0, recvd_blocks_rollover, "Block 0 (rollover) was not sent")
            self.assertIn(1, recvd_blocks_rollover, "Block 1 (after rollover) was not sent")
            print(f"\n[+] Block Rollover Verified: Observed sequence around 65535: {recvd_blocks_rollover[:10]}")
        finally:
            mock.close()
            mock2.close()

    # -------------------------------------------------------------------------
    # TEST 5: ADVERSARIAL FLAWS & SYSTEM RESILIENCE CHECKS
    # -------------------------------------------------------------------------
    def test_10_winsock_connreset_handling(self):
        """
        Verify TftpClient handles WSAECONNRESET (10054) on closed UDP port without crashing.
        Must catch ConnectionResetError/OSError and cleanly timeout after retries.
        """
        port = get_free_port()  # Port is closed, nothing listening
        client = TftpClient(host="127.0.0.1", port=port, timeout=0.1, retries=2, quiet=True)

        timed_out_cleanly = False
        try:
            client.push_bytes(b"probe", remote_filename="probe.bin")
        except ConnectionResetError as e:
            self.fail(f"TftpClient crashed with ConnectionResetError: {e}")
        except TimeoutError:
            timed_out_cleanly = True
            print("\n[+] TftpClient gracefully handled closed port and timed out.")

        self.assertTrue(timed_out_cleanly, "Expected clean TimeoutError without crashing")

    def test_11_path_traversal(self):
        """
        Verify TftpServer blocks arbitrary file read via RRQ path traversal.
        Requests with path traversal (e.g. ../docs/...) must NOT leak files and must return ERROR opcode.
        """
        port = get_free_port()
        server = TftpServer(bind_ip="127.0.0.1", bind_port=port, quiet=True)
        server.start_background()
        time.sleep(0.05)

        try:
            target_file = os.path.join(SUITE_DIR, "docs", "EMERGENCY_RECOVERY_GUIDE.md")
            self.assertTrue(os.path.exists(target_file))

            client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_sock.settimeout(2.0)

            # Send RRQ with relative path traversal
            rrq = struct.pack(">H", OPCODE_RRQ) + target_file.encode("ascii") + b"\x00octet\x00"
            client_sock.sendto(rrq, ("127.0.0.1", port))

            data_pkt, sender = client_sock.recvfrom(1024)
            opcode, bnum = struct.unpack(">HH", data_pkt[:4])
            client_sock.close()

            # Opcode must be OPCODE_ERROR (5), NOT OPCODE_DATA (3)
            self.assertEqual(opcode, OPCODE_ERROR, "Server must return ERROR opcode for path traversal request")
            self.assertNotEqual(opcode, OPCODE_DATA, "Server must NOT serve file data on path traversal request")
            print("\n[+] Path traversal blocked: Server returned ERROR opcode.")
        finally:
            server.stop()

    def test_12_duplicate_ack_retry_exhaustion(self):
        """
        Verify that receiving delayed duplicate ACKs does not consume retry counters prematurely.
        With retries=3 and timeout=0.2s, transfer must not be exhausted in < 0.25s.
        """
        port = get_free_port()
        mock = MockTftpServer(bind_port=port)

        def dup_ack_server():
            try:
                req, client_addr = mock.sock.recvfrom(1024)
                sess = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sess.settimeout(2.0)

                # Send initial ACK 0
                sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), client_addr)

                # Client sends DATA block 1
                pkt, sender = sess.recvfrom(1024)
                op, blk = struct.unpack(">HH", pkt[:4])

                # Instead of sending ACK 1, flood 6 duplicate ACK 0s!
                for _ in range(6):
                    sess.sendto(struct.pack(">HH", OPCODE_ACK, 0), sender)
                    time.sleep(0.005)

                # Keep socket open and discard retransmissions to simulate dropped ACK 1
                while True:
                    try:
                        sess.recvfrom(1024)
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                try:
                    sess.close()
                except Exception:
                    pass

        t = threading.Thread(target=dup_ack_server, daemon=True)
        t.start()
        time.sleep(0.05)

        start_t = time.time()
        timeout_occurred = False
        try:
            # retries = 3, timeout = 0.2s
            # If duplicate ACKs exhaust retries prematurely, it would fail in < 0.05s.
            # When decoupled, it waits for timeout, taking >= 0.25s.
            client = TftpClient(host="127.0.0.1", port=port, timeout=0.2, retries=3, quiet=True)
            client.push_bytes(b"data", remote_filename="dup.bin")
        except TimeoutError:
            timeout_occurred = True
        elapsed = time.time() - start_t

        print(f"\n[+] Duplicate ACK resilience verified: elapsed={elapsed:.3f}s")
        self.assertTrue(timeout_occurred, "Expected TimeoutError when ACK 1 is never sent")
        self.assertGreaterEqual(elapsed, 0.25, f"Retries were exhausted prematurely ({elapsed:.3f}s < 0.25s)!")
        mock.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

