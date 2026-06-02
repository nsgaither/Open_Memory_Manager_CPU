import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, Edge, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner

# golden model
from emulation.msi_v2 import MSIState, ProcessorEvent, TransitionResult # types
from emulation.msi_v2 import on_processor_event # function

sim = os.getenv("SIM", "icarus")
pdk_root = Path("../gf180mcu")
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "on_processor_event_state_machine"

@cocotb.test()
async def test_mem_ctrl_against_golden(dut):

    logger = logging.getLogger("my_testbench")

    for state in MSIState:
        for event in ProcessorEvent:

            # feed in inputs
            dut.current_state_i.value = int(state)
            if event == ProcessorEvent.PR_RD:
                dut.wstrb_i.value = 0
            else:
                dut.wstrb_i.value = 15

            # check output with golden
            golden: TransitionResult = on_processor_event(state, event)

            await Timer(1, unit="ns") # time to propagate outputs  

            # check next state
            assert int(dut.next_state_o.value) == int(golden.next_state), \
                f"State mismatch: DUT={dut.next_state_o.value}, GOLDEN={golden.next_state}"

            # check cmd issued to directory
            if golden.issue_cmd == None:
                assert int(dut.issue_cmd_valid_o.value) == 0, \
                    f"there should be no cmd issued"
            else:
                assert int(dut.issue_cmd_valid_o.value) == 1, \
                    f"there should be cmd issued"
                
                assert int(dut.issue_cmd_o.value) == int(golden.issue_cmd), \
                f"State mismatch: DUT={dut.issue_cmd_o.value}, GOLDEN={golden.issue_cmd}"
            
    logger.info("Done!")


def test_on_processor_event_state_machine():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/msi_protocol/on_processor_event_state_machine.sv",
    ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
        
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="on_processor_event_state_machine",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="on_processor_event_state_machine",
        test_module="on_processor_event_state_machine_tb",
        waves=True,
    )

if __name__ == "__main__":
    test_on_processor_event_state_machine()


