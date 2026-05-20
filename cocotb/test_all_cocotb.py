#!/usr/bin/env python3
"""Standalone test runner — runs each cocotb testbench as a subprocess."""

import subprocess
import sys
import os
from pathlib import Path

ENV = {
    "PDK_ROOT": os.getenv("PDK_ROOT", str(Path("../gf180mcu").resolve())),
    "PDK":      os.getenv("PDK",      "gf180mcuD"),
    "SLOT":     os.getenv("SLOT",     "0p5x0p5"),
    "SIM":      os.getenv("SIM",      "icarus"),
    **os.environ,
}

COCOTB_DIR = Path(__file__).resolve().parent

TESTBENCHES = [
    "cache_mem_tb",
    "cache_sram_test",
    "two_port_cache_mem_tb",
    "test_mem_ctrl_128x4",
    "cache_interface_tb",
]


def run_one(name: str) -> bool:
    script = f"{name}.py"
    print(f"\n{'='*60}")
    print(f"  Running: {script}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, script],
        cwd=COCOTB_DIR,
        env=ENV,
    )
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {script}  (exit code {result.returncode})")
    return ok


def main() -> int:
    passed = 0
    failed = 0
    for tb in TESTBENCHES:
        if run_one(tb):
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
