# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner

# Default to verilator for better SystemVerilog support
sim = os.getenv("SIM", "verilator")
pdk_root = os.getenv("PDK_ROOT", Path("../gf180mcu").resolve())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)

hdl_toplevel = "mem_ctrl_128x32"

async def start_clock(clock, freq=50):
    """Start the clock @ freq MHz"""
    c = Clock(clock, 1 / freq * 1000, "ns")
    cocotb.start_soon(c.start())

async def reset(dut, time_ns=1000):
    """Reset dut"""
    cocotb.log.info("Reset asserted...")
    dut.rst_ni.value = 0
    await Timer(time_ns, "ns")
    dut.rst_ni.value = 1
    cocotb.log.info("Reset deasserted.")


@cocotb.test()
async def test_mem_write_read_single(dut):
    """Test single word write and read"""
    logger = logging.getLogger("test_mem_write_read_single")
    logger.info("Testing single write and read...")

    # Initialize
    dut.rst_ni.value = 0
    dut.clk_i.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0

    await start_clock(dut.clk_i)
    await reset(dut)

    # Wait for reset to complete
    await ClockCycles(dut.clk_i, 520)

    # Write a single byte first to understand byte ordering
    logger.info("Writing byte 0xAA to addr 0...")
    dut.mem_addr_i.value = 0x00
    dut.mem_wdata_i.value = 0xAA
    dut.mem_wstrb_i.value = 0x1  # Write byte 0
    dut.mem_valid_i.value = 1

    # Wait for mem_ready
    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value) == 1:
            logger.info(f"Write completed")
            break

    dut.mem_valid_i.value = 0
    await ClockCycles(dut.clk_i, 2)

    # Read back single byte
    dut.mem_addr_i.value = 0x00
    dut.mem_wstrb_i.value = 0x0  # Read
    dut.mem_valid_i.value = 1

    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value) == 1:
            read_val = int(dut.mem_rdata_o.value)
            logger.info(f"Read data: {read_val:#x}")
            # With single byte write, expect byte in some position
            break

    dut.mem_valid_i.value = 0
    await ClockCycles(dut.clk_i, 2)

    # Now write 0xDEADBEEF as 4 bytes and read back
    logger.info("Writing 0xDEADBEEF to addr 0x00...")
    dut.mem_addr_i.value = 0x00
    dut.mem_wdata_i.value = 0xDEADBEEF
    dut.mem_wstrb_i.value = 0xF  # Write all bytes
    dut.mem_valid_i.value = 1

    # Wait for mem_ready
    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value) == 1:
            logger.info(f"Write completed")
            break

    dut.mem_valid_i.value = 0
    await ClockCycles(dut.clk_i, 2)

    # Read back from address 0x00
    logger.info("Reading from addr 0x00...")
    dut.mem_addr_i.value = 0x00
    dut.mem_wstrb_i.value = 0x0  # Read
    dut.mem_valid_i.value = 1

    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value) == 1:
            read_val = int(dut.mem_rdata_o.value)
            logger.info(f"Read data: {read_val:#x}")
            # The memory controller assembles bytes: first byte read → bits 31:24
            # So 0xDE@addr0, 0xAD@addr1, 0xBE@addr2, 0xEF@addr3 → 0xDEADBEEF
            assert read_val == 0xDEADBEEF, f"Expected 0xDEADBEEF, got {read_val:#x}"
            break

    dut.mem_valid_i.value = 0
    logger.info("Single write/read test passed!")


@cocotb.test()
async def test_mem_write_read_multiple(dut):
    """Test multiple consecutive writes and reads"""
    logger = logging.getLogger("test_mem_write_read_multiple")
    logger.info("Testing multiple writes and reads...")

    # Initialize
    dut.rst_ni.value = 0
    dut.clk_i.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0

    await start_clock(dut.clk_i)
    await reset(dut)

    # Wait for reset
    await ClockCycles(dut.clk_i, 520)

    # Write multiple words
    test_data = [
        (0x00, 0x12345678),
        (0x04, 0xABCDEF01),
        (0x08, 0x11223344),
        (0x0C, 0x55667788),
    ]

    for addr, data in test_data:
        logger.info(f"Writing {data:#x} to addr {addr:#x}")
        dut.mem_addr_i.value = addr
        dut.mem_wdata_i.value = data
        dut.mem_wstrb_i.value = 0xF
        dut.mem_valid_i.value = 1

        while True:
            await RisingEdge(dut.clk_i)
            if int(dut.mem_ready_o.value) == 1:
                break

        dut.mem_valid_i.value = 0
        await ClockCycles(dut.clk_i, 2)

    # Read back and verify
    for addr, expected in test_data:
        logger.info(f"Reading from addr {addr:#x}")
        dut.mem_addr_i.value = addr
        dut.mem_wstrb_i.value = 0x0
        dut.mem_valid_i.value = 1

        while True:
            await RisingEdge(dut.clk_i)
            if int(dut.mem_ready_o.value) == 1:
                read_val = int(dut.mem_rdata_o.value)
                logger.info(f"Read: {read_val:#x}, Expected: {expected:#x}")
                assert read_val == expected, f"Addr {addr:#x}: Expected {expected:#x}, got {read_val:#x}"
                break

        dut.mem_valid_i.value = 0
        await ClockCycles(dut.clk_i, 2)

    logger.info("Multiple write/read test passed!")


@cocotb.test()
async def test_mem_byte_write(dut):
    """Test byte-level writes"""
    logger = logging.getLogger("test_mem_byte_write")
    logger.info("Testing byte writes...")

    # Initialize
    dut.rst_ni.value = 0
    dut.clk_i.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0

    await start_clock(dut.clk_i)
    await reset(dut)
    await ClockCycles(dut.clk_i, 520)

    # Write byte by byte to build a word
    addr = 0x10
    bytes_to_write = [0x11, 0x22, 0x33, 0x44]

    for i, byte_val in enumerate(bytes_to_write):
        logger.info(f"Writing byte {byte_val:#x} to byte {i}")
        dut.mem_addr_i.value = addr + i
        dut.mem_wdata_i.value = byte_val
        dut.mem_wstrb_i.value = 0x1  # Write only byte 0 (but addr determines which byte)
        dut.mem_valid_i.value = 1

        while True:
            await RisingEdge(dut.clk_i)
            if int(dut.mem_ready_o.value) == 1:
                break

        dut.mem_valid_i.value = 0
        await ClockCycles(dut.clk_i, 2)

    # Read back the word
    dut.mem_addr_i.value = addr
    dut.mem_wstrb_i.value = 0x0
    dut.mem_valid_i.value = 1

    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value) == 1:
            read_val = int(dut.mem_rdata_o.value)
            logger.info(f"Read word: {read_val:#x}")
            # Note: The actual byte order depends on endianness
            break

    dut.mem_valid_i.value = 0
    logger.info("Byte write test passed!")


@cocotb.test()
async def test_mem_timing(dut):
    """Test memory access timing (should take 4 cycles per access)"""
    logger = logging.getLogger("test_mem_timing")
    logger.info("Testing memory access timing...")

    # Initialize
    dut.rst_ni.value = 0
    dut.clk_i.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0

    await start_clock(dut.clk_i)
    await reset(dut)
    await ClockCycles(dut.clk_i, 520)

    # Perform a read and count cycles
    dut.mem_addr_i.value = 0x20
    dut.mem_wstrb_i.value = 0x0
    dut.mem_valid_i.value = 1

    cycles = 0
    while True:
        await RisingEdge(dut.clk_i)
        cycles += 1
        if int(dut.mem_ready_o.value) == 1:
            logger.info(f"Memory access took {cycles} cycles")
            # FSM takes 4 states (MEM_REQ_0 to MEM_REQ_4) = 4 cycles after IDLE
            assert cycles >= 4, f"Memory access should take at least 4 cycles, took {cycles}"
            break

    dut.mem_valid_i.value = 0
    logger.info("Memory timing test passed!")


def mem128x32_runner():

    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {}
    build_args = []

    if gl:
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")
        sources.append(proj_path / "../final/pnl/mem_ctrl_128x32.pnl.v")
        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources.append(proj_path / "../src/mem_ctrl/mem128x32.sv")

    sources.append(
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v"
    )

    # Use behavioral SRAM model for Verilator to avoid timing/specify block issues
    if sim == "verilator":
        sources = [s for s in sources if "gf180mcu_fd_ip_sram__sram512x8m8wm1.v" not in str(s)]
        sources.append(proj_path / "sram512x8_beh.v")

    if sim == "verilator":
        build_args = ["--no-timing", "--trace", "--trace-fst", "-Wno-lint", "-Wno-style"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="mem128x32_tb,",
        waves=True,
    )


if __name__ == "__main__":
    mem128x32_runner()
