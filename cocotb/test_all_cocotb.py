#!/usr/bin/env python3
"""Standalone test runner — runs each cocotb testbench as a subprocess."""

import subprocess
import sys
import os
from pathlib import Path
from xml.etree import ElementTree

ENV = {
    "PDK_ROOT": os.getenv("PDK_ROOT", str(Path("../gf180mcu").resolve())),
    "PDK":      os.getenv("PDK",      "gf180mcuD"),
    "SLOT":     os.getenv("SLOT",     "0p5x0p5"),
    "SIM":      os.getenv("SIM",      "icarus"),
    **os.environ,
}

COCOTB_DIR = Path(__file__).resolve().parent

TESTBENCHES = [
    "cache_mem_tb.py",
    "cache_sram_test.py",
    "mem128x32_tb.py",
    "test_mem_ctrl_128x4.py",
    "two_port_cache_mem_tb.py",
    "on_processor_event_state_machine_tb.py",
    "on_snoop_event_state_machine_tb.py",
    "cache_controller_tb.py",
    "cache_interface_tb.py",
    "sp_handler_tb.py",
    "chip_top_tb.py",
]


def clear_previous_results() -> None:
    for result_file in COCOTB_DIR.glob("sim_build*/results.xml"):
        result_file.unlink()


def collect_result_failures() -> list[str]:
    result_files = sorted(COCOTB_DIR.glob("sim_build*/results.xml"))
    if not result_files:
        return ["no cocotb results.xml was produced"]

    failures = []
    for result_file in result_files:
        root = ElementTree.parse(result_file).getroot()
        for testcase in root.iter("testcase"):
            failure = testcase.find("failure")
            error = testcase.find("error")
            problem = failure if failure is not None else error
            if problem is None:
                continue
            name = testcase.get("name", "<unknown>")
            classname = testcase.get("classname", "")
            message = problem.get("error_msg") or problem.get("message") or problem.tag
            failures.append(f"{result_file}: {classname}.{name}: {message}")

    return failures


def run_one(script: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  Running: {script}")
    print(f"{'='*60}")

    clear_previous_results()
    result = subprocess.run(
        [sys.executable, script],
        cwd=COCOTB_DIR,
        env=ENV,
    )

    result_failures = collect_result_failures()
    ok = result.returncode == 0 and not result_failures
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {script}  (exit code {result.returncode})")
    for failure in result_failures:
        print(f"    {failure}")
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
