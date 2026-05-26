# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = Path(os.getenv("PDK_ROOT", Path("../gf180mcu").resolve()))
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", "0") == "1"
slot = os.getenv("SLOT", "0p5x0p5")

hdl_toplevel = "chip_top"

# Pad indexes from chip_core.sv.
DEBUG_PAD = 0
SERIAL_I_START_PAD = 2
REQ_I_PAD = 11
SERIAL_O_START_PAD = 12
REQ_O_PAD = 21
TRAP_PAD = 22
NUM_SERIAL_PADS = 9


def _pad_drive(width, driven_bits=None):
    bits = ["z"] * width
    for index, value in (driven_bits or {}).items():
        bits[width - 1 - index] = str(value)
    return "".join(bits)


async def reset_chip(dut):
    dut.rst_n_PAD.value = 0
    await ClockCycles(dut.clk_PAD, 5)
    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 5)
    await Timer(2, unit="ns")


def assert_scalar(signal, expected, name):
    actual = str(signal.value).lower()
    assert actual == str(expected), f"{name}: expected {expected}, got {actual}"


def assert_vector_bit(signal, index, expected, name):
    actual = str(signal.value[index]).lower()
    assert actual == str(expected), f"{name}: expected {expected}, got {actual}"


def vector_bit_value(signal, index):
    return str(signal.value[index]).lower()


def get_child(parent, *names):
    for name in names:
        try:
            return parent[name]
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            pass
        try:
            return parent._id(name, extended=False)
        except (AttributeError, ValueError):
            pass
        try:
            return parent._id(name, extended=True)
        except (AttributeError, ValueError):
            pass
    raise AssertionError(f"Could not find any of: {', '.join(names)}")


def gl_pad2core(dut, pad):
    escaped = rf"\bidir_PAD2CORE[{pad}] "
    return get_child(dut, escaped, escaped.rstrip(), f"bidir_PAD2CORE[{pad}]")


async def start_and_reset(dut):
    num_bidir_pads = len(dut.bidir_PAD)

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads)
    dut.clk_PAD.value = 0
    dut.rst_n_PAD.value = 0

    cocotb.start_soon(Clock(dut.clk_PAD, 10, unit="ns").start())
    await reset_chip(dut)
    return num_bidir_pads


@cocotb.test()
async def test_chip_top_pad_smoke(dut):
    """Basic chip-top smoke test through the pad-level wrapper."""

    num_bidir_pads = await start_and_reset(dut)

    assert num_bidir_pads == 48, f"Expected 48 bidirectional pads, got {num_bidir_pads}"
    assert_scalar(dut.rst_n_PAD, 1, "reset pad after reset")
    await ClockCycles(dut.clk_PAD, 5)


@cocotb.test()
async def test_fixed_pad_directions(dut):
    """Check fixed chip-core pad direction controls."""

    await start_and_reset(dut)
    if gl:
        input_pads = [DEBUG_PAD, REQ_I_PAD] + list(
            range(SERIAL_I_START_PAD, SERIAL_I_START_PAD + NUM_SERIAL_PADS)
        )
        output_pads = [REQ_O_PAD, TRAP_PAD] + list(
            range(SERIAL_O_START_PAD, SERIAL_O_START_PAD + NUM_SERIAL_PADS)
        )

        for pad in input_pads:
            actual = vector_bit_value(dut.bidir_PAD, pad)
            assert actual == "z", f"bidir[{pad}] should float when released, got {actual}"

        for pad in output_pads:
            actual = vector_bit_value(dut.bidir_PAD, pad)
            assert actual != "z", f"bidir[{pad}] should be driven when released"
        return

    core = dut.i_chip_core

    # Fixed input-only pads.
    assert_vector_bit(core.bidir_oe, DEBUG_PAD, 0, "debug OE")
    assert_vector_bit(core.bidir_ie, DEBUG_PAD, 1, "debug IE")
    assert_vector_bit(core.bidir_oe, REQ_I_PAD, 0, "req_i OE")
    assert_vector_bit(core.bidir_ie, REQ_I_PAD, 1, "req_i IE")

    for pad in range(SERIAL_I_START_PAD, SERIAL_I_START_PAD + NUM_SERIAL_PADS):
        assert_vector_bit(core.bidir_oe, pad, 0, f"serial_i[{pad - SERIAL_I_START_PAD}] OE")
        assert_vector_bit(core.bidir_ie, pad, 1, f"serial_i[{pad - SERIAL_I_START_PAD}] IE")

    # Fixed output-only pads.
    assert_vector_bit(core.bidir_oe, REQ_O_PAD, 1, "req_o OE")
    assert_vector_bit(core.bidir_ie, REQ_O_PAD, 0, "req_o IE")
    assert_vector_bit(core.bidir_oe, TRAP_PAD, 1, "trap OE")
    assert_vector_bit(core.bidir_ie, TRAP_PAD, 0, "trap IE")

    for pad in range(SERIAL_O_START_PAD, SERIAL_O_START_PAD + NUM_SERIAL_PADS):
        assert_vector_bit(core.bidir_oe, pad, 1, f"serial_o[{pad - SERIAL_O_START_PAD}] OE")
        assert_vector_bit(core.bidir_ie, pad, 0, f"serial_o[{pad - SERIAL_O_START_PAD}] IE")


@cocotb.test()
async def test_req_i_pad_input_path(dut):
    """Drive req_i through its external pad."""

    num_bidir_pads = await start_and_reset(dut)

    req_i_signal = gl_pad2core(dut, REQ_I_PAD) if gl else dut.i_chip_core.req_i

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, {REQ_I_PAD: 1})
    await Timer(2, unit="ns")
    assert_scalar(req_i_signal, 1, "req_i pad input high")

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, {REQ_I_PAD: 0})
    await Timer(2, unit="ns")
    assert_scalar(req_i_signal, 0, "req_i pad input low")


@cocotb.test()
async def test_serial_input_pad_path(dut):
    """Drive the 9-bit serial input bus through external pads."""

    num_bidir_pads = await start_and_reset(dut)

    pattern = 0b101_011_001
    driven_bits = {
        SERIAL_I_START_PAD + bit: (pattern >> bit) & 1
        for bit in range(NUM_SERIAL_PADS)
    }

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, driven_bits)
    await Timer(2, unit="ns")

    if gl:
        actual = 0
        for bit in range(NUM_SERIAL_PADS):
            actual |= int(gl_pad2core(dut, SERIAL_I_START_PAD + bit).value) << bit
    else:
        actual = int(dut.i_chip_core.serial_i.value)

    assert actual == pattern, f"serial_i expected 0x{pattern:x}, got 0x{actual:x}"


def chip_top_runner():
    proj_path = Path(__file__).resolve().parent

    defines = {f"SLOT_{slot.upper().replace('P', 'P')}": True}
    includes = [proj_path / "../src"]
    sources = []

    if gl:
        sources += [
            pdk_root / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v",
            pdk_root / pdk / "libs.ref" / scl / "verilog" / "primitives.v",
            proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v",
        ]
        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources += [
            proj_path / "../src/chip_top.sv",
            proj_path / "../src/chip_core.sv",
            proj_path / "../src/housekeeping/housekeeping_top.sv",
            proj_path / "../src/housekeeping/boot_fsm.sv",
            proj_path / "../src/housekeeping/spi_engine.sv",
            proj_path / "../ip/picorv32/picorv32.v",
            proj_path / "../src/sp_addr_handling/sp_addr_handler.sv",
            proj_path / "../src/sp_addr_handling/mmio.sv",
            proj_path / "../src/cache_controller/cache_controller.sv",
            proj_path / "../src/cache_controller/outbound_arbiter.sv",
            proj_path / "../src/cache_controller/on_snoop_event_state_machine.sv",
            proj_path / "../src/cache_controller/on_processor_event_state_machine.sv",
            proj_path / "../src/cache_controller/apply_wstrb.sv",
            proj_path / "../src/interposer_interface/cache_interface.sv",
            proj_path / "../src/interposer_interface/lossy_pipe_stage.sv",
            proj_path / "../src/interposer_interface/rserializer.sv",
            proj_path / "../src/interposer_interface/tserializer.sv",
            proj_path / "../src/mem_ctrl/cache_mem.sv",
            proj_path / "../src/mem_ctrl/two_port_cache_mem.sv",
            proj_path / "../src/mem_ctrl/mem128x32.sv",
            proj_path / "../src/mem_ctrl/mem128x4.sv",
        ]

    sources += [
        pdk_root / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_fd_io.v",
        pdk_root / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_ws_io.v",
        pdk_root
        / pdk
        / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root
        / pdk
        / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]
    elif sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        includes=includes,
        build_args=build_args,
        always=True,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb",
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
