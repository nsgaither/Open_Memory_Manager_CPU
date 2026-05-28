# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
hdl_toplevel = "digital_dll"


async def start_clock(dut):
    dut.clk_ref_i.value = 0
    cocotb.start_soon(Clock(dut.clk_ref_i, 10, unit="ns").start())


async def reset_dut(dut, enable=1, bypass=0):
    dut.rst_ni.value = 0
    dut.enable_i.value = enable
    dut.bypass_i.value = bypass
    await ClockCycles(dut.clk_ref_i, 4)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_ref_i, 2)


@cocotb.test()
async def test_bypass_mode_follows_reference_clock(dut):
    await start_clock(dut)
    await reset_dut(dut, enable=1, bypass=1)

    assert int(dut.locked_o.value) == 1
    assert int(dut.tap_o.value) == 8

    for _ in range(8):
        await Timer(1, unit="ns")
        assert dut.clk_o.value == dut.clk_ref_i.value
        await ClockCycles(dut.clk_ref_i, 1)


@cocotb.test()
async def test_controller_reaches_stable_tap_in_rtl(dut):
    await start_clock(dut)
    await reset_dut(dut, enable=1, bypass=0)

    await ClockCycles(dut.clk_ref_i, 40)

    assert int(dut.tap_o.value) == 0
    assert int(dut.locked_o.value) == 1


@cocotb.test()
async def test_disable_returns_to_initial_tap(dut):
    await start_clock(dut)
    await reset_dut(dut, enable=1, bypass=0)
    await ClockCycles(dut.clk_ref_i, 20)

    dut.enable_i.value = 0
    await ClockCycles(dut.clk_ref_i, 2)

    assert int(dut.tap_o.value) == 8
    assert int(dut.locked_o.value) == 0


def digital_dll_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [proj_path / "../src/clocking/digital_dll.sv"]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]
    elif sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        build_args=build_args,
        waves=True,
        build_dir="sim_build_digital_dll",
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="digital_dll_tb",
        waves=True,
        build_dir="sim_build_digital_dll",
    )


if __name__ == "__main__":
    digital_dll_runner()
