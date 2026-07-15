# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = Path(os.getenv("PDK_ROOT", Path("../gf180mcu").resolve()))
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", "0") == "1"
sdf = os.getenv("SDF", "0") == "1"
sdf_file = os.getenv("SDF_FILE", "")
sdf_corner = os.getenv("SDF_CORNER", "max_tt_025C_5v00")
sdf_interconnect = os.getenv("SDF_INTERCONNECT", "0") == "1"
slot = os.getenv("SLOT", "0p5x0p5")

hdl_toplevel = "chip_top"

# Pad indexes from chip_core.sv.
DEBUG_PAD = 0
BOOT_DONE_PAD = 1
SERIAL_I_START_PAD = 2
REQ_I_PAD = 11
SERIAL_O_START_PAD = 12
REQ_O_PAD = 21
TRAP_PAD = 22
DEBUG_START_PAD = 23
DFT_PINS = 8
DFT_CHAINS = DFT_PINS // 2
SCAN_IN_PADS = tuple(range(DEBUG_START_PAD, DEBUG_START_PAD + DFT_CHAINS))
SCAN_OUT_PADS = tuple(
    range(DEBUG_START_PAD + DFT_CHAINS, DEBUG_START_PAD + DFT_PINS)
)
NUM_SERIAL_PADS = 9
# Measured scan-chain lengths after the 4x widen. Deltas vs the 1x baseline
# (139,198,217,119): the cache mem wrappers gained +8 scan FFs total (mem512x6
# 39->43, mem512x32 98->102) split across the cache chains, and chain 0 also
# grew with the mem_init_count counter (MEM_INIT_CYCLES 513->2049 => 10->12b).
SCAN_CHAIN_LENGTHS = (143, 199, 220, 119)


def _pad_drive(width, driven_bits=None):
    bits = ["z"] * width
    for index, value in (driven_bits or {}).items():
        bits[width - 1 - index] = str(value)
    return "".join(bits)


def _scan_pad_drive(width, scan_inputs):
    driven_bits = {DEBUG_PAD: 1}
    driven_bits.update(
        {SCAN_IN_PADS[lane]: (scan_inputs >> lane) & 1 for lane in range(DFT_CHAINS)}
    )
    return _pad_drive(width, driven_bits)


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


def filtered_sdf_without_interconnect(source_sdf, build_dir):
    """Create an Icarus-friendly SDF with INTERCONNECT records removed."""

    build_dir.mkdir(parents=True, exist_ok=True)
    filtered_sdf = build_dir / f"{source_sdf.stem}.no_interconnect.sdf"

    with source_sdf.open() as src, filtered_sdf.open("w") as dst:
        for line in src:
            if line.lstrip().startswith("(INTERCONNECT "):
                continue
            dst.write(line)

    return filtered_sdf


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
async def test_reset_deassertion_is_synchronized(dut):
    """Raw reset asserts immediately and releases after two clock edges."""
    num_bidir_pads = len(dut.bidir_PAD)
    dut.bidir_PAD.value = _pad_drive(num_bidir_pads)
    dut.clk_PAD.value = 0
    dut.rst_n_PAD.value = 0
    cocotb.start_soon(Clock(dut.clk_PAD, 10, unit="ns").start())

    await ClockCycles(dut.clk_PAD, 2)
    assert_scalar(dut.rst_n_sync, 0, "synchronized reset while asserted")

    # Move deassertion away from the active edge. The first edge fills the
    # synchronizer; the second releases every downstream reset consumer.
    await Timer(2, unit="ns")
    dut.rst_n_PAD.value = 1

    for _ in range(4):
        await RisingEdge(dut.clk_PAD)
        await Timer(1, unit="ps")
        if int(dut.reset_sync_ff.value) & 1:
            break
    else:
        raise AssertionError("reset synchronizer first stage never released")

    assert_scalar(dut.rst_n_sync, 0, "synchronized reset after first edge")

    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ps")
    assert_scalar(dut.rst_n_sync, 1, "synchronized reset after second edge")


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

    req_i_signal = gl_pad2core(dut, REQ_I_PAD) if gl else dut.i_chip_core.req_i_branches

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, {REQ_I_PAD: 1})
    await Timer(2, unit="ns")
    if gl:
        assert_scalar(req_i_signal, 1, "req_i pad input high")
    else:
        for branch in range(5):
            assert_vector_bit(req_i_signal, branch, 1, f"req_i branch {branch} high")

    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, {REQ_I_PAD: 0})
    await Timer(2, unit="ns")
    if gl:
        assert_scalar(req_i_signal, 0, "req_i pad input low")
    else:
        for branch in range(5):
            assert_vector_bit(req_i_signal, branch, 0, f"req_i branch {branch} low")


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


@cocotb.test()
async def test_scan_chain_shift_path(dut):
    """Check all four GPIO-muxed scan paths and their documented lengths."""

    if gl:
        return

    num_bidir_pads = await start_and_reset(dut)
    core = dut.i_chip_core

    dut.bidir_PAD.value = _pad_drive(
        num_bidir_pads, {DEBUG_PAD: 1, **{pad: 0 for pad in SCAN_IN_PADS}}
    )
    await Timer(2, unit="ns")

    for lane, pad in enumerate(SCAN_IN_PADS):
        assert_vector_bit(core.bidir_oe, pad, 0, f"scan input {lane} OE")
        assert_vector_bit(core.bidir_ie, pad, 1, f"scan input {lane} IE")
    for lane, pad in enumerate(SCAN_OUT_PADS):
        assert_vector_bit(core.bidir_oe, pad, 1, f"scan output {lane} OE")
        assert_vector_bit(core.bidir_ie, pad, 0, f"scan output {lane} IE")

    # Flush every chain to zero, inject one pulse into all four inputs, and
    # check that it emerges after the documented number of registers.
    for _ in range(max(SCAN_CHAIN_LENGTHS)):
        dut.bidir_PAD.value = _scan_pad_drive(num_bidir_pads, 0)
        await ClockCycles(dut.clk_PAD, 1)
        # The foundry input pad delays the core clock by 1 ns.
        await Timer(2, unit="ns")

    for step in range(1, max(SCAN_CHAIN_LENGTHS) + 2):
        dut.bidir_PAD.value = _scan_pad_drive(
            num_bidir_pads, (1 << DFT_CHAINS) - 1 if step == 1 else 0
        )
        await ClockCycles(dut.clk_PAD, 1)
        await Timer(2, unit="ns")

        actual = int(core.dft_scan_out.value)
        expected = sum(
            (1 << lane) if step == length else 0
            for lane, length in enumerate(SCAN_CHAIN_LENGTHS)
        )
        assert actual == expected, (
            f"scan outputs at shift {step}: expected 0b{expected:04b}, "
            f"got 0b{actual:04b}"
        )


@cocotb.test()
async def test_scan_chain_insertion_path(dut):
    """Insert scan data into the first real register on every chain."""

    if gl:
        return

    num_bidir_pads = await start_and_reset(dut)
    core = dut.i_chip_core

    dut.bidir_PAD.value = _scan_pad_drive(num_bidir_pads, 0b1111)
    await Timer(2, unit="ns")
    assert int(core.dft_scan_in.value) == 0b1111
    await ClockCycles(dut.clk_PAD, 1)
    await Timer(2, unit="ns")

    assert_vector_bit(core.mem_init_count, 0, 1, "chain 0 startup insertion")
    assert_vector_bit(
        core.u_cache_controller.cpu_state_q, 0, 1, "chain 1 controller insertion"
    )
    assert_scalar(
        core.u_cache_controller.cache_mem.busy, 1, "chain 2 memory insertion"
    )
    assert_scalar(
        core.u_cache_interface.u_tserializer.current_state,
        1,
        "chain 3 serializer insertion",
    )

    # Dropping debug mode restores the original GPIO mux immediately, without
    # requiring another clock edge.
    dut.bidir_PAD.value = _pad_drive(num_bidir_pads, {DEBUG_PAD: 0})
    await Timer(2, unit="ns")
    dft_mask = (1 << DFT_PINS) - 1
    gpio_oe = (int(core.bidir_oe.value) >> DEBUG_START_PAD) & dft_mask
    gpio_out = (int(core.bidir_out.value) >> DEBUG_START_PAD) & dft_mask
    assert gpio_oe == int(core.gpio_dir.value)
    assert gpio_out == int(core.gpio_pins_o.value)


@cocotb.test()
async def test_cpu_reset_held_until_memory_ready(dut):
    """CPU reset stays low until the cache SRAM clear window has elapsed."""

    if gl:
        return

    num_bidir_pads = await start_and_reset(dut)
    core = dut.i_chip_core

    dut.bidir_PAD.value = _pad_drive(
        num_bidir_pads, {DEBUG_PAD: 0, BOOT_DONE_PAD: 1}
    )
    await Timer(2, unit="ns")

    assert_scalar(core.memory_ready, 0, "memory_ready immediately after reset")
    assert_scalar(core.cpu_resetn, 0, "cpu_resetn immediately after reset")

    # 4x data mem clears 2048 rows: memory_ready asserts after MEM_INIT_CYCLES=2049.
    for _ in range(2100):
        await ClockCycles(dut.clk_PAD, 1)
        await Timer(1, unit="ps")
        if int(core.memory_ready.value) == 1:
            break

    assert_scalar(core.memory_ready, 1, "memory_ready after SRAM clear")
    assert_scalar(core.cpu_resetn, 1, "cpu_resetn after SRAM clear")


def chip_top_runner():
    proj_path = Path(__file__).resolve().parent

    defines = {f"SLOT_{slot.upper().replace('P', 'P')}": True}
    includes = [proj_path / "../src"]
    sources = []

    if gl:
        sources += [
            pdk_root / pdk / "libs.ref" / scl / "verilog" / "primitives.v",
            pdk_root / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v",
            proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v",
        ]
        defines = {"USE_POWER_PINS": True}
        if not sdf:
            defines["FUNCTIONAL"] = True

        if sdf:
            if not sdf_file:
                raise RuntimeError(
                    "SDF=1 requires SDF_FILE to be set. "
                    "Run: make sim-sdf SDF_CORNER=<corner>"
                )
            annotation_sdf = Path(sdf_file)
            if sim == "icarus" and not sdf_interconnect:
                annotation_sdf = filtered_sdf_without_interconnect(
                    annotation_sdf,
                    proj_path / "sim_build",
                )
            sources += [proj_path / "sdf_annotate.v"]
            defines["SDF_FILE"] = str(annotation_sdf)
    else:
        sources += [
            pdk_root / pdk / "libs.ref" / scl / "verilog" / "primitives.v",
            pdk_root / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v",
            proj_path / "../src/chip_top.sv",
            proj_path / "../src/chip_core.sv",
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
            proj_path / "../src/mem_ctrl/mem512x32.sv",
            proj_path / "../src/mem_ctrl/mem512x6.sv",
        ]

    sources += [
        pdk_root / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_fd_io.v",
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__qrcode_id/vh/gf180mcu_ws_ip__qrcode_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__shuttle_id/vh/gf180mcu_ws_ip__shuttle_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__project_id/vh/gf180mcu_ws_ip__project_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__marker/vh/gf180mcu_ws_ip__marker.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    # 4x cache: data on two ocd 1024x8, tag on ocd 512x8. Portable beh models
    # (Icarus rejects the PDK SRAM specify paths, incl. under SDF).
    sources += [
        proj_path / "models/gf180_ocd_sram1024x8_model.sv",
        proj_path / "models/gf180_ocd_sram512x8_model.sv",
    ]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]
        if sdf:
            corner_name = sdf_corner.lower()
            if corner_name.startswith("max_"):
                sdf_delay_mode = "max"
            elif corner_name.startswith("min_"):
                sdf_delay_mode = "min"
            else:
                sdf_delay_mode = "typ"
            build_args += [
                "-gspecify",
                "-T",
                sdf_delay_mode,
                "-s",
                "sdf_annotate_shim",
            ]
            if sdf_interconnect:
                build_args += ["-ginterconnect"]
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

    plusargs = []
    if sdf:
        plusargs += ["+sdf_verbose", "+maxdelays"]

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
