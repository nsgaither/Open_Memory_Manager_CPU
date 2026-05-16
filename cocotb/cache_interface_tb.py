import os
import logging
from pathlib import Path
from math import ceil
from enum import IntEnum

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb_tools.runner import get_runner
from cocotb.clock import Clock
import random


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "cache_interface"

class Metadata(IntEnum):
    NULL            = 0b0000
    BusRD           = 0b0001
    BusRDX          = 0b0010
    BusUPGR         = 0b0011

    EvictClean      = 0b0101
    EvictDirty      = 0b0110


    SnoopBusRD      = 0b1001
    SnoopBusRDX     = 0b1010
    SnoopBusUPGR    = 0b1011


    WhoAmI          = 0b1110
    ResetDone       = 0b1111

class CCMD1H(IntEnum):
    BusRD              = 0b000000001
    BusRDX             = 0b000000010
    BusUPGR            = 0b000000100
    EvictClean         = 0b000001000
    EvictDirty         = 0b000010000
    SnoopBusRD_Ack     = 0b000100000
    SnoopBusRDX_Ack    = 0b001000000
    SnoopBusUPGR_Ack   = 0b010000000
    ResetDone          = 0b100000000

class DCMD1H(IntEnum):
    BusRD_Ack        = 0b0000001
    BusRDX_Ack       = 0b0000010
    BusUPGR_Ack      = 0b0000100
    SnoopBusRD       = 0b0001000
    SnoopBusRDX      = 0b0010000
    SnoopBusUPGR     = 0b0100000
    WhoAmI           = 0b1000000

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def reset_dut(dut):
    dut.rst_ni.value = 0

    # zero all inputs
    dut.cache_valid_i.value = 0
    dut.cache_addr_i.value = 0
    dut.cache_data_i.value = 0
    dut.cache_cmd_i.value = 0
    
    dut.bus_ready_i.value = 0

    dut.snoop_ready_i.value = 0

    dut.req_i.value = 0
    dut.serial_i.value = 0

    await Timer(50, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

async def collect_message(dut):

    logger = logging.getLogger("cocotb.test")
    if not gl:
        NUM_PINS = int(dut.NUM_TPINS.value)
    else:
        NUM_PINS = 9

    while dut.req_o.value == 0:
        await RisingEdge(dut.clk_i)

    captured_bits = 0
    bit_count = 0
    while dut.req_o.value == 1:
        bit_count += NUM_PINS
        captured_bits <<= NUM_PINS
        captured_bits += int(dut.serial_o.value)
        await RisingEdge(dut.clk_i)

    logger.info(f"Captured {bit_count} bits: {hex(captured_bits)}")

    return bit_count, captured_bits

async def send_message(dut, data, msg_len):

    logger = logging.getLogger("cocotb.test")
    if not gl:
        NUM_PINS = int(dut.NUM_RPINS.value)
    else:
        NUM_PINS = 9

    dut.req_i.value = 1

    t_len = ceil(msg_len / NUM_PINS)
    mask = (1 << NUM_PINS) - 1

    for i in range (t_len-1, -1, -1):
        curr_data = (data >> (i*NUM_PINS)) & mask
        logger.debug(f"Iteration: {i}, Message: {hex(data)}, Sending: {curr_data}")

        dut.serial_i.value = curr_data
        await FallingEdge(dut.clk_i)
    
    dut.req_i.value = 0
    dut.serial_i.value = 0

def set_packet(dut, ccmd : CCMD1H, mem_addr, mem_wdata):

    assert 0x0 <= mem_addr <= 0xFFFFFFFF, "mem_addr must be 32 bits"
    assert 0x0 <= mem_wdata <= 0xFFFFFFFF, "mem_wdata must be 32 bits"

    dut.cache_valid_i.value = 1
    dut.cache_cmd_i.value = ccmd
    dut.cache_addr_i.value = mem_addr
    dut.cache_data_i.value = mem_wdata

class CycleCounter:
    def __init__(self, clock_signal):
        self.count = 0
        self.clk = clock_signal

    async def start(self):
        while True:
            await cocotb.triggers.RisingEdge(self.clk)
            self.count += 1


# ─── Tests ────────────────────────────────────────────────────────────────────
@cocotb.test
async def test_send_BusRD(dut):
    if not gl:
        NUM_PINS = int(dut.NUM_TPINS.value)
    else:
        NUM_PINS = 9

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.BusRD
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(36 / NUM_PINS) * NUM_PINS
    expected_data = (mem_addr << 4) + Metadata.BusRD

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_EvictDirty(dut):
    if not gl:
        NUM_PINS = int(dut.NUM_TPINS.value)
    else:
        NUM_PINS = 9

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.EvictDirty
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(68 / NUM_PINS) * NUM_PINS
    expected_data = (mem_wdata << 36) + (mem_addr << 4) + Metadata.EvictDirty

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_SnoopBusRD_Ack(dut):
    if not gl:
        NUM_PINS = int(dut.NUM_TPINS.value)
    else:
        NUM_PINS = 9

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.SnoopBusRD_Ack
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(36 / NUM_PINS) * NUM_PINS
    expected_data = (mem_wdata << 4) + Metadata.SnoopBusRD

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_ResetDone(dut):
    if not gl:
        NUM_PINS = int(dut.NUM_TPINS.value)
    else:
        NUM_PINS = 9

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.ResetDone
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(4 / NUM_PINS) * NUM_PINS
    expected_data = Metadata.ResetDone

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"
    
    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_WhoAmI(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.WhoAmI
    expected_cpu_id = 0xA1
    expected_message = (expected_cpu_id << 4) + command
    expected_msg_len = 12

    # send message
    await FallingEdge(dut.clk_i)
    await send_message(dut, data=expected_message, msg_len=expected_msg_len)

    # validate message
    await FallingEdge(dut.clk_i)
    assert dut.bus_valid_o.value == 0, "bus_valid_o should not be high after WhoAmI command"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after WhoAmI command"
    await FallingEdge(dut.clk_i)
    cpu_id = int(dut.cpu_id_o.value)
    assert cpu_id == expected_cpu_id, f"Expected CPU_ID {expected_cpu_id}, got {cpu_id}"
    assert dut.bus_valid_o.value == 0, "bus_valid_o should not be high after WhoAmI command"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after WhoAmI command"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_BusRD_Ack(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.BusRD
    expected_bus_data = 0xDEADBEEF
    expected_message = (expected_bus_data << 4) + command
    expected_msg_len = 36

    # send message
    cocotb.start_soon(send_message(dut, data=expected_message, msg_len=expected_msg_len))

    # validate message
    while dut.bus_valid_o.value == 0:
        await FallingEdge(dut.clk_i)

    bus_data = int(dut.bus_data_o.value)
    bus_dircmd = int(dut.bus_dircmd_o.value)
    
    expected_dcmd = DCMD1H.BusRD_Ack & 0b111

    assert bus_data == expected_bus_data, f"Expected mem_rdata {expected_bus_data}, got {bus_data}"
    assert bus_dircmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {bus_dircmd}"
    assert dut.bus_valid_o.value == 1, "bus_valid_o should be high after BusRD_Ack command"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    for _ in range(5):
        await FallingEdge(dut.clk_i)
    
    dut.bus_ready_i.value = 1
    await FallingEdge(dut.clk_i)
    assert dut.bus_valid_o.value == 0, "bus_valid_o should not be high after bus_ready_i is high"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_BusUPGR_Ack(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.BusUPGR
    expected_message = command
    expected_msg_len = 4

    # send message
    cocotb.start_soon(send_message(dut, data=expected_message, msg_len=expected_msg_len))

    # validate message
    while dut.bus_valid_o.value == 0:
        await FallingEdge(dut.clk_i)

    bus_dircmd = int(dut.bus_dircmd_o.value)
    
    expected_dcmd = DCMD1H.BusUPGR_Ack & 0b111
    assert bus_dircmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {bus_dircmd}"
    assert dut.bus_valid_o.value == 1, "bus_valid_o should be high after BusRD_Ack command"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    for _ in range(5):
        await FallingEdge(dut.clk_i)
    
    dut.bus_ready_i.value = 1
    await FallingEdge(dut.clk_i)
    assert dut.bus_valid_o.value == 0, "bus_valid_o should not be high after bus_ready_i is high"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    await RisingEdge(dut.clk_i)
    
@cocotb.test
async def test_receive_SnoopBusRDX(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.SnoopBusRDX
    expected_bus_data = 0xDEADBEEF
    expected_message = (expected_bus_data << 4) + command
    expected_msg_len = 36

    # send message
    cocotb.start_soon(send_message(dut, data=expected_message, msg_len=expected_msg_len))

    # validate message
    while dut.snoop_valid_o.value == 0:
        await FallingEdge(dut.clk_i)

    bus_data = int(dut.snoop_data_o.value)
    bus_dircmd = int(dut.snoop_dircmd_o.value)
    
    expected_dcmd = (DCMD1H.SnoopBusRDX >> 3) & 0b111

    assert bus_data == expected_bus_data, f"Expected mem_rdata {expected_bus_data}, got {bus_data}"
    assert bus_dircmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {bus_dircmd}"
    assert dut.snoop_valid_o.value == 1, "bus_valid_o should be high after BusRD_Ack command"
    assert dut.bus_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    for _ in range(5):
        await FallingEdge(dut.clk_i)
    
    dut.snoop_ready_i.value = 1
    await FallingEdge(dut.clk_i)
    assert dut.bus_valid_o.value == 0, "bus_valid_o should not be high after bus_ready_i is high"
    assert dut.snoop_valid_o.value == 0, "snoop_valid_o should not be high after BusRD_Ack command"

    await RisingEdge(dut.clk_i)
    
# ─── Running ──────────────────────────────────────────────────────────────────

def directory_interface_runner():
    proj_path = Path(__file__).resolve().parent

    sources = []
    configs = []
    if gl:
        pdk_lib = os.path.join(
            pdk_root, 
            pdk, 
            "libs.ref", 
            scl, 
            "verilog"
        )
        sources += [proj_path / f"../src/netlists/{hdl_toplevel}.nl.v"]
        sources += [os.path.join(pdk_lib, f) for f in [f"{scl}.v", f"primitives.v"]]

        configs += [
            {"NUM_TPINS": 9, "NUM_RPINS": 9},
        ]
    else:
        sources = [
            proj_path / "../src/interposer_interface/cache_interface.sv",
            proj_path / "../src/interposer_interface/rserializer.sv",
            proj_path / "../src/interposer_interface/tserializer.sv",
            proj_path / "../src/interposer_interface/lossy_pipe_stage.sv",
        ]

        configs += [
            {"NUM_TPINS": 1, "NUM_RPINS": 1},
            {"NUM_TPINS": 4, "NUM_RPINS": 4},
            {"NUM_TPINS": 9, "NUM_RPINS": 9},
        ]

    for config in configs:
        run_id = f"tp{config['NUM_TPINS']}_rp{config['NUM_RPINS']}"

        build_args = []
        if sim == "icarus":
            if not gl:
                build_args += ["-g2012", f"-P{hdl_toplevel}.NUM_TPINS={config['NUM_TPINS']}", f"-P{hdl_toplevel}.NUM_RPINS={config['NUM_RPINS']}"]
            else:
                build_args += ["-g2012"]
        if sim == "verilator":
            build_args += ["--timing", "--trace", "--trace-fst", "--trace-structs", f"-GNUM_TPINS={config['NUM_TPINS']}", f"-GNUM_RPINS={config['NUM_RPINS']}"]
        
        runner = get_runner(sim)
        runner.build(
            sources=sources,
            hdl_toplevel=hdl_toplevel,
            always=True,
            build_args=build_args,
            waves=True,
            build_dir=f"sim_build_ci_{run_id}"
        )

        runner.test(
            hdl_toplevel=hdl_toplevel,
            test_module="cache_interface_tb",
            waves=True,
            build_dir=f"sim_build_ci_{run_id}"
        )

if __name__ == "__main__":
    directory_interface_runner()

