import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner

from sram_models import find_sram_model


SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "mem64x8"


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())
    await Timer(1, unit="ns")


def set_idle(dut):
    dut.enable_n_i.value = 1
    dut.gwen_i.value = 0b111
    dut.wen_i.value = 0xFFFFFF
    dut.addr_i.value = 0
    dut.wdata_i.value = 0


async def write_array(dut, addr, data, gwen=0b000, wen=0x000000):
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.gwen_i.value = gwen
    dut.wen_i.value = wen
    dut.addr_i.value = addr & 0x3F
    dut.wdata_i.value = data & 0xFFFFFF
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    set_idle(dut)


async def read_array(dut, addr):
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.gwen_i.value = 0b111
    dut.wen_i.value = 0xFFFFFF
    dut.addr_i.value = addr & 0x3F
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    value = int(dut.rdata_o.value) & 0xFFFFFF
    set_idle(dut)
    return value


@cocotb.test()
async def test_full_width_round_trip(dut):
    await start_clock(dut)
    set_idle(dut)

    rng = random.Random(0x64)
    expected = {}

    for _ in range(64):
        addr = rng.randrange(64)
        data = rng.randrange(1 << 24)
        expected[addr] = data
        await write_array(dut, addr, data)
        got = await read_array(dut, addr)
        assert got == data, (
            f"metadata SRAM read mismatch at {addr:#x}: "
            f"DUT={got:#08x}, expected={data:#08x}"
        )

    for addr, data in expected.items():
        got = await read_array(dut, addr)
        assert got == data, (
            f"metadata SRAM retained mismatch at {addr:#x}: "
            f"DUT={got:#08x}, expected={data:#08x}"
        )


@cocotb.test()
async def test_bank_gwen_selects_only_enabled_sram(dut):
    await start_clock(dut)
    set_idle(dut)

    addr = 0x15
    await write_array(dut, addr, 0x123456)
    await write_array(dut, addr, 0xABCDEF, gwen=0b101, wen=0x000000)

    got = await read_array(dut, addr)
    assert got == 0x12CD56, (
        f"only the middle 8-bit SRAM bank should update: got {got:#08x}"
    )


@cocotb.test()
async def test_bit_wen_masks_within_each_bank(dut):
    await start_clock(dut)
    set_idle(dut)

    addr = 0x22
    await write_array(dut, addr, 0x000000)

    # In each 8-bit bank, active-low WEN writes only the low nibble.
    await write_array(dut, addr, 0xFFFFFF, gwen=0b000, wen=0xF0F0F0)

    got = await read_array(dut, addr)
    assert got == 0x0F0F0F, (
        f"low-nibble bit masks were not honored: got {got:#08x}"
    )


def mem64x8_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [
        find_sram_model(64),
        proj_path / "../src/mem_ctrl/mem64x8.sv",
    ]

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=sources,
        hdl_toplevel=HDL_TOPLEVEL,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=HDL_TOPLEVEL,
        test_module="mem64x8_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem64x8_runner()
