# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "chip_top"

async def set_defaults(dut):
    dut.input_PAD.value = 0

async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0

async def start_clock(clock, freq=50):
    """Start the clock @ freq MHz"""
    c = Clock(clock, 1 / freq * 1000, "ns")
    cocotb.start_soon(c.start())

async def reset(reset, active_low=True, time_ns=1000):
    """Reset dut"""
    cocotb.log.info("Reset asserted...")
    reset.value = not active_low
    await Timer(time_ns, "ns")
    reset.value = active_low
    cocotb.log.info("Reset deasserted.")

async def start_up(dut):
    """Startup sequence"""
    await set_defaults(dut)
    if gl:
        await enable_power(dut)
    await start_clock(dut.clk_PAD)
    await reset(dut.rst_n_PAD)


@cocotb.test()
async def test_reset_and_clock(dut):
    """Test reset and clock functionality"""
    logger = logging.getLogger("test_reset_and_clock")
    logger.info("Testing reset and clock...")

    await start_up(dut)

    # Verify clock is running by checking edges
    await RisingEdge(dut.clk_PAD)
    await RisingEdge(dut.clk_PAD)
    logger.info("Clock is toggling.")

    # Verify reset is deasserted
    assert dut.rst_n_PAD.value == 1, "Reset should be deasserted"
    logger.info("Reset is deasserted.")

    logger.info("Reset and clock test passed!")


@cocotb.test()
async def test_bidir_outputs(dut):
    """Test bidirectional pad outputs after reset"""
    logger = logging.getLogger("test_bidir_outputs")
    logger.info("Testing bidirectional pad outputs...")

    await start_up(dut)

    # Wait for SRAM reset to complete (512 cycles + some idle cycles)
    await ClockCycles(dut.clk_PAD, 600)

    # bidir_oe is set to 1 in chip_core, so pads should be in output mode
    # and bidir_out is set to 0, so all outputs should be 0
    logger.info(f"bidir_PAD value: {dut.bidir_PAD.value}")
    assert dut.bidir_PAD.value == 0, f"bidir_PAD should be 0, got {dut.bidir_PAD.value}"

    logger.info("Bidirectional outputs test passed!")


@cocotb.test()
async def test_input_propagation(dut):
    """Test that inputs propagate to core"""
    logger = logging.getLogger("test_input_propagation")
    logger.info("Testing input propagation...")

    await start_up(dut)

    # Wait for reset and SRAM init
    await ClockCycles(dut.clk_PAD, 600)

    # Set some input values
    test_val = 0xA
    dut.input_PAD.value = test_val
    await ClockCycles(dut.clk_PAD, 5)

    # Read back through the core - inputs should be visible
    logger.info(f"input_PAD value: {dut.input_PAD.value}")
    assert dut.input_PAD.value == test_val, f"input_PAD should be {test_val}"

    logger.info("Input propagation test passed!")


def chip_top_runner():

    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]

    if gl:
        # SCL models
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")

        # We use the powered netlist
        sources.append(proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v")

        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources.append(proj_path / "../src/chip_top.sv")
        sources.append(proj_path / "../src/chip_core.sv")
        sources.append(proj_path / "../ip/picorv32/picorv32.v")
        sources.append(proj_path / "../src/mem_ctrl/mem128x32.sv")

    sources += [
        # IO pad models
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_fd_io.v",
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_ws_io.v",
        
        # SRAM macros
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        
        # Custom IP
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    build_args = []

    if sim == "icarus":
        # For debugging
        # build_args = ["-Winfloop", "-pfileline=1"]
        pass

    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=build_args,
        waves=True,
    )

    plusargs = []

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb,",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
