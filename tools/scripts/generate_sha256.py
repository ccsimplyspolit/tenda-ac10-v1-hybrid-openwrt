#!/usr/bin/env python3
"""
Cryptographic SHA-256 Manifest Generator for Tenda AC10 V1.0 Artifacts
======================================================================

Generates standard SHA256SUMS.txt manifests for staged directories and release packages.

Usage:
    python generate_sha256.py [--dir <path>] [--output <file>] [--recursive]
"""

import os
import sys
import hashlib
import argparse

def compute_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def generate_manifest(target_dir, output_file=None, recursive=False):
    if not os.path.isdir(target_dir):
        print(f"[-] Error: Target directory does not exist: {target_dir}")
        return False

    records = []
    print(f"[*] Scanning {target_dir} (recursive={recursive})...")

    if recursive:
        for root, _, files in os.walk(target_dir):
            for fname in sorted(files):
                if fname in ("SHA256SUMS.txt", "SHA256SUMS"):
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, target_dir)
                digest = compute_sha256(full_path)
                records.append((digest, rel_path.replace("\\", "/")))
    else:
        for fname in sorted(os.listdir(target_dir)):
            full_path = os.path.join(target_dir, fname)
            if os.path.isfile(full_path):
                if fname in ("SHA256SUMS.txt", "SHA256SUMS"):
                    continue
                digest = compute_sha256(full_path)
                records.append((digest, fname))

    lines = [f"{digest}  {name}" for digest, name in records]
    output_text = "\n".join(lines) + "\n"

    if output_file:
        with open(output_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(output_text)
        print(f"[+] Wrote {len(records)} entries to {output_file}")
    else:
        print(output_text)

    return True

def main():
    parser = argparse.ArgumentParser(description="Generate SHA-256 manifest")
    parser.add_argument("-d", "--dir", default=".", help="Target directory")
    parser.add_argument("-o", "--output", default=None, help="Output manifest file (e.g. SHA256SUMS.txt)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories")

    args = parser.parse_args()
    success = generate_manifest(args.dir, args.output, args.recursive)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
