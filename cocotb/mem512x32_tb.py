# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("../gf180mcu").resolve())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)

hdl_toplevel = "mem512x32"

# 4x: reset walks all 2048 byte rows (512 words x 4 bytes) across two 1024x8 macros
INIT_BYTE_CYCLES = 2048
NUM_WORDS = 512


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, "ns")
    cocotb.start_soon(clock.start())
    await Timer(1, unit="ns")


def set_idle(dut):
    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.mem_ready_i.value = 0


async def reset(dut):
    set_idle(dut)
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 4)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")


async def wait_init_done(dut, timeout_cycles=INIT_BYTE_CYCLES + 20):
    for cycle in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        if int(dut.mem_ready_o.value) == 1:
            return cycle + 1
    raise AssertionError(
        f"mem_ready_o never asserted within {timeout_cycles} cycles after reset"
    )


async def wait_accept_ready(dut, context, timeout_cycles=8):
    for cycle in range(timeout_cycles):
        await Timer(1, unit="ns")
        if int(dut.mem_ready_o.value) == 1:
            return cycle
        await RisingEdge(dut.clk_i)
    raise AssertionError(f"mem_ready_o was not high before {context}")


async def mem_transaction(dut, addr, data=0, strb=0, timeout_cycles=16):
    await wait_accept_ready(dut, f"request addr {addr:#x}")

    await FallingEdge(dut.clk_i)
    dut.mem_addr_i.value = addr & 0x1FF
    dut.mem_wdata_i.value = data & 0xFFFFFFFF
    dut.mem_wstrb_i.value = strb & 0xF
    dut.mem_valid_i.value = 1

    await RisingEdge(dut.clk_i)
    dut.mem_valid_i.value = 0
    dut.mem_wstrb_i.value = 0

    for cycle in range(1, timeout_cycles + 1):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        if int(dut.mem_valid_o.value) == 1:
            rdata = int(dut.mem_rdata_o.value)
            dut.mem_ready_i.value = 1
            await RisingEdge(dut.clk_i)
            await Timer(1, unit="ns")
            dut.mem_ready_i.value = 0
            return rdata, cycle

    raise AssertionError(
        f"mem_valid_o never asserted for addr {addr:#x} within {timeout_cycles} cycles"
    )


async def mem_write(dut, addr, data, strb=0xF):
    _, cycles = await mem_transaction(dut, addr, data, strb)
    return cycles


async def mem_read(dut, addr):
    return await mem_transaction(dut, addr, 0, 0)


@cocotb.test()
async def test_mem_write_read_single(dut):
    logger = logging.getLogger("test_mem_write_read_single")

    await start_clock(dut)
    await reset(dut)
    await wait_init_done(dut)

    await mem_write(dut, 0x00, 0xDEADBEEF)
    read_val, _ = await mem_read(dut, 0x00)

    assert read_val == 0xDEADBEEF, f"Expected 0xDEADBEEF, got {read_val:#x}"
    logger.info("Single write/read test passed")


@cocotb.test()
async def test_mem_write_read_multiple(dut):
    logger = logging.getLogger("test_mem_write_read_multiple")

    await start_clock(dut)
    await reset(dut)
    await wait_init_done(dut)

    # Span both 1024x8 macros: words 0..255 live in macro0 (addr[8]==0),
    # words 256..511 in macro1 (addr[8]==1). Include the boundary + top word.
    test_data = [
        (0x000, 0x12345678),  # macro0 bottom
        (0x001, 0xABCDEF01),
        (0x0FF, 0x0BADF00D),  # macro0 top (word 255)
        (0x100, 0x11223344),  # macro1 bottom (word 256)
        (0x1FF, 0x55667788),  # macro1 top (word 511)
    ]

    for addr, data in test_data:
        await mem_write(dut, addr, data)

    for addr, expected in test_data:
        read_val, _ = await mem_read(dut, addr)
        assert read_val == expected, (
            f"Addr {addr:#x}: expected {expected:#x}, got {read_val:#x}"
        )

    logger.info("Multiple write/read test passed")


@cocotb.test()
async def test_mem_byte_write(dut):
    logger = logging.getLogger("test_mem_byte_write")

    await start_clock(dut)
    await reset(dut)
    await wait_init_done(dut)

    addr = 0x10
    await mem_write(dut, addr, 0x00000000)

    byte_patterns = [
        (0b0001, 0x000000AA, 0x000000AA),
        (0b0010, 0x0000BB00, 0x0000BBAA),
        (0b0100, 0x00CC0000, 0x00CCBBAA),
        (0b1000, 0xDD000000, 0xDDCCBBAA),
    ]

    for strb, wdata, expected in byte_patterns:
        await mem_write(dut, addr, wdata, strb=strb)
        read_val, _ = await mem_read(dut, addr)
        assert read_val == expected, (
            f"strb=0b{strb:04b}: expected {expected:#x}, got {read_val:#x}"
        )

    logger.info("Byte write test passed")


@cocotb.test()
async def test_mem_timing(dut):
    logger = logging.getLogger("test_mem_timing")

    await start_clock(dut)
    await reset(dut)
    await wait_init_done(dut)

    _, cycles = await mem_read(dut, 0x20)
    assert cycles >= 5, f"Memory response should take at least 5 cycles, took {cycles}"
    assert cycles <= 8, f"Memory response took unexpectedly long: {cycles} cycles"

    logger.info("Memory response took %d cycles", cycles)


def mem512x32_runner():
    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {}
    build_args = []

    if gl:
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")
        sources.append(proj_path / "../final/pnl/mem512x32.pnl.v")
        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources.append(proj_path / "../src/mem_ctrl/mem512x32.sv")

    # 4x data store rides two ocd 1024x8 macros. Use the portable beh model
    # (works on both Icarus and Verilator; PDK .v carries specify blocks).
    sources.append(proj_path / "models/gf180_ocd_sram1024x8_model.sv")

    if sim == "icarus":
        build_args = ["-g2012"]
    elif sim == "verilator":
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
        test_module="mem512x32_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem512x32_runner()
