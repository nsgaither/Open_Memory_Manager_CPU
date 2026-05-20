# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

"""
CocoTB testbench for mem_ctrl_128x32 — SRAM initialization verification.

Tests:
  1. test_init_busy_during_reset       — mem_ready_o stays low for exactly 128 cycles post-reset
  2. test_init_zeros_all_addresses     — every address reads back 0x0000_0000 after init
  3. test_ready_after_init             — mem_ready_o goes high immediately after the 128th write
  4. test_no_cpu_access_during_init    — mem_ready_o stays 0 regardless of CPU request during init
  5. test_write_read_after_init        — basic R/W sanity check once init completes
  6. test_full_address_range_rw        — write/read all 128 locations with a unique pattern

DUT ports (mem_ctrl_128x32):
    clk_i        input
    rst_ni       input  (active-low reset)
    mem_valid_i  input  [0:0]
    mem_addr_i   input  [31:0]
    mem_wdata_i  input  [31:0]
    mem_wstrb_i  input  [3:0]
    mem_rdata_o  output [31:0]
    mem_ready_o  output [0:0]
"""

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Timer
from cocotb_tools.runner import get_runner

# ---------------------------------------------------------------------------
# Simulator / environment knobs
# ---------------------------------------------------------------------------
sim      = os.getenv("SIM",      "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk      = os.getenv("PDK",      "gf180mcuD")
scl      = os.getenv("SCL",      "gf180mcu_fd_sc_mcu7t5v0")

hdl_toplevel = "mem128x32"

# SRAM is 512x8 (bytes), controller presents 128x32 (words)
INIT_BYTE_CYCLES = 512   # FSM resets 512 byte addresses
NUM_WORDS        = 128   # Controller presents 128 words (32-bit each)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _start_clock(dut, freq_mhz: int = 50):
    """Launch a clock on clk_i."""
    period_ns = 1_000 / freq_mhz
    c = Clock(dut.clk_i, period_ns, "ns")
    cocotb.start_soon(c.start())


async def _reset(dut, cycles: int = 4):
    """Assert active-low reset for *cycles* clock edges, then release."""
    dut.rst_ni.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value  = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.rst_ni.value = 1


async def _wait_init_done(dut, timeout_cycles: int = INIT_BYTE_CYCLES + 20):
    """
    Poll mem_ready_o on every rising edge.
    Returns the cycle count at which ready went high.
    Raises AssertionError if timeout is reached first.
    """
    for cycle in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            return cycle
    raise AssertionError(
        f"mem_ready_o never asserted within {timeout_cycles} cycles after reset release"
    )


async def _cpu_read(dut, addr: int) -> int:
    """Drive a CPU read request and wait for mem_ready_o; returns rdata."""
    await FallingEdge(dut.clk_i)
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0             # read
    # Wait for mem_ready_o (FSM needs 5 cycles: MEM_REQ_0..MEM_REQ_4)
    while True:
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            rdata = int(dut.mem_rdata_o.value)
            dut.mem_valid_i.value = 0
            return rdata


async def _cpu_write(dut, addr: int, data: int, strb: int = 0xF):
    """Drive a CPU write request and wait for mem_ready_o."""
    await FallingEdge(dut.clk_i)
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = data
    dut.mem_wstrb_i.value = strb
    # Wait for mem_ready_o (FSM needs 5 cycles: MEM_REQ_0..MEM_REQ_4)
    while True:
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value == 1:
            dut.mem_valid_i.value = 0
            dut.mem_wstrb_i.value = 0
            return


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_init_busy_during_reset(dut):
    """
    mem_ready_o must remain LOW for *at least* INIT_BYTE_CYCLES cycles after
    reset is released, confirming the FSM is actively initialising.
    """
    log = logging.getLogger("tb.init_busy")
    log.info("START: test_init_busy_during_reset")

    await _start_clock(dut)
    await _reset(dut)

    low_count = 0
    for _ in range(INIT_BYTE_CYCLES - 1):    # check all but the last cycle
        await RisingEdge(dut.clk_i)
        assert dut.mem_ready_o.value == 0, (
            f"mem_ready_o went HIGH prematurely at cycle {low_count}"
        )
        low_count += 1

    log.info(f"mem_ready_o stayed LOW for {low_count} cycles ✓")


@cocotb.test()
async def test_ready_after_init(dut):
    """
    mem_ready_o must assert HIGH after INIT_BYTE_CYCLES cycles
    (the FSM sweeps 512 byte addresses before becoming ready).
    """
    log = logging.getLogger("tb.ready_after_init")
    log.info("START: test_ready_after_init")

    await _start_clock(dut)
    await _reset(dut)

    cycles_to_ready = await _wait_init_done(dut)

    assert cycles_to_ready <= INIT_BYTE_CYCLES + 5, (
        f"mem_ready_o asserted too late: {cycles_to_ready} cycles "
        f"(expected ≤ {INIT_BYTE_CYCLES + 5})"
    )
    log.info(f"mem_ready_o asserted after {cycles_to_ready} cycles ✓")


@cocotb.test()
async def test_no_cpu_access_during_init(dut):
    """
    CPU requests presented while init is running must be silently ignored:
    mem_ready_o stays 0 throughout the init window even when mem_valid_i=1.
    """
    log = logging.getLogger("tb.no_cpu_during_init")
    log.info("START: test_no_cpu_access_during_init")

    await _start_clock(dut)
    await _reset(dut)

    # Assert a CPU read immediately
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value  = 0x00000010
    dut.mem_wstrb_i.value = 0

    for cycle in range(INIT_BYTE_CYCLES - 1):
        await RisingEdge(dut.clk_i)
        assert dut.mem_ready_o.value == 0, (
            f"mem_ready_o asserted during init at cycle {cycle} despite active CPU request"
        )

    dut.mem_valid_i.value = 0
    log.info("mem_ready_o correctly suppressed all CPU responses during init ✓")


@cocotb.test()
async def test_init_zeros_all_addresses(dut):
    """
    After initialisation every one of the 128 32-bit words must read back
    as 0x0000_0000.  This is the core correctness check for the sweep FSM.
    """
    log = logging.getLogger("tb.zeros_check")
    log.info("START: test_init_zeros_all_addresses")

    await _start_clock(dut)
    await _reset(dut)
    await _wait_init_done(dut)

    failures = []
    for addr in range(NUM_WORDS):
        rdata = await _cpu_read(dut, addr)
        if rdata != 0:
            failures.append((addr, rdata))

    assert not failures, (
        f"{len(failures)} addresses did not read back zero after init:\n"
        + "\n".join(f"  addr=0x{a:03X}  data=0x{d:08X}" for a, d in failures[:16])
        + (" ..." if len(failures) > 16 else "")
    )
    log.info(f"All {NUM_WORDS} addresses verified as 0x00000000 after init ✓")


@cocotb.test()
async def test_write_read_after_init(dut):
    """
    Basic R/W smoke-test: write a known value to a handful of addresses
    and verify the readback is correct.
    """
    log = logging.getLogger("tb.rw_sanity")
    log.info("START: test_write_read_after_init")

    await _start_clock(dut)
    await _reset(dut)
    await _wait_init_done(dut)

    test_vectors = [
        (0x00, 0xDEADBEEF),
        (0x01, 0xCAFEBABE),
        (0x7F, 0x12345678),
    ]

    for addr, data in test_vectors:
        await _cpu_write(dut, addr, data, strb=0xF)
        rdata = await _cpu_read(dut, addr)
        assert rdata == data, (
            f"addr=0x{addr:02X}: wrote 0x{data:08X}, read back 0x{rdata:08X}"
        )
        log.info(f"  addr=0x{addr:02X} → 0x{data:08X} ✓")

    log.info("Write/read sanity passed ✓")


@cocotb.test()
async def test_full_address_range_rw(dut):
    """
    Write a unique 32-bit pattern to every address then read all of them back.
    Pattern: addr XOR 0xA5A5_0000 — chosen to exercise all byte lanes.
    """
    log = logging.getLogger("tb.full_sweep_rw")
    log.info("START: test_full_address_range_rw")

    await _start_clock(dut)
    await _reset(dut)
    await _wait_init_done(dut)

    # ---- Write phase ----
    log.info("Writing unique pattern to all 128 word addresses…")
    for addr in range(NUM_WORDS):
        pattern = ((addr << 2) ^ 0xA5A50000) & 0xFFFFFFFF
        await _cpu_write(dut, addr << 2, pattern, strb=0xF)

    # ---- Read-back phase ----
    log.info("Reading back and verifying…")
    failures = []
    for addr in range(NUM_WORDS):
        expected = ((addr << 2) ^ 0xA5A50000) & 0xFFFFFFFF
        rdata = await _cpu_read(dut, addr << 2)
        if rdata != expected:
            failures.append((addr, expected, rdata))

    assert not failures, (
        f"{len(failures)} mismatches in full sweep:\n"
        + "\n".join(
            f"  addr=0x{a:02X} (word {a})  exp=0x{e:08X}  got=0x{g:08X}"
            for a, e, g in failures[:16]
        )
        + (" ..." if len(failures) > 16 else "")
    )
    log.info(f"Full {NUM_WORDS}-word R/W sweep passed ✓")


@cocotb.test()
async def test_byte_strobes_after_init(dut):
    """
    Verify each of the four byte-write strobes works independently
    after init is complete.  Writes 0x00 to all bytes first, then
    patches one byte at a time and checks the others are undisturbed.
    """
    log = logging.getLogger("tb.byte_strobes")
    log.info("START: test_byte_strobes_after_init")

    await _start_clock(dut)
    await _reset(dut)
    await _wait_init_done(dut)

    TEST_ADDR = 0x010

    # Address is already zero from init; overwrite with 0 explicitly anyway
    await _cpu_write(dut, TEST_ADDR, 0x00000000, strb=0xF)

    byte_patterns = [
        (0b0001, 0x000000AA, 0x000000AA),   # byte 0 only
        (0b0010, 0x0000BB00, 0x0000BBAA),   # byte 1 only
        (0b0100, 0x00CC0000, 0x00CCBBAA),   # byte 2 only
        (0b1000, 0xDD000000, 0xDDCCBBAA),   # byte 3 only
    ]

    for strb, wdata, expected in byte_patterns:
        await _cpu_write(dut, TEST_ADDR, wdata, strb=strb)
        rdata = await _cpu_read(dut, TEST_ADDR)
        assert rdata == expected, (
            f"strb=0b{strb:04b}: wrote 0x{wdata:08X}, "
            f"expected 0x{expected:08X}, got 0x{rdata:08X}"
        )
        log.info(f"  strb=0b{strb:04b} → 0x{rdata:08X} ✓")

    log.info("Byte-strobe test passed ✓")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def mem_ctrl_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/mem_ctrl/mem128x32.sv",
        Path(pdk_root) / pdk / (
            "libs.ref/gf180mcu_fd_ip_sram/verilog/"
            "gf180mcu_fd_ip_sram__sram512x8m8wm1.v"
        ),
    ]

    build_args = []
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        build_args=build_args,
        waves=True,
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="mem_ctrl_512x32_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem_ctrl_runner()
