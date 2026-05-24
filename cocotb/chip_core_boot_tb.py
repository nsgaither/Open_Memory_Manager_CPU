import os
import shutil
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM",  "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("../gf180mcu"))
pdk = os.getenv("PDK",  "gf180mcuD")

hdl_toplevel = "chip_core_flash_tb"

# pad index constants(match localparam values in chip_core.sv)
PAD_PASS_THRU_EN = 0    # input_in[0]
PAD_MISO = 1    # input_in[1]
PAD_SCK = 8    # bidir[8]
PAD_MOSI = 9    # bidir[9]
PAD_CSB = 10   # bidir[10]

NUM_INPUT_PADS = 12
NUM_BIDIR_PADS = 40
NUM_ANALOG_PADS = 2

#boot image- same 512-byte XOR pattern used in all boot tests
BOOT_IMAGE = [(i & 0xFF) ^ 0xA5 for i in range(512)]

def expected_word(word_index):
    b = BOOT_IMAGE[word_index * 4 : word_index * 4 + 4]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

def write_boot_image_mem():
    sim_build = Path(__file__).resolve().parent / "sim_build"
    sim_build.mkdir(exist_ok=True)
    out = sim_build / "boot_image.mem"
    with open(out, "w") as f:
        f.write("@000000\n")
        for byte in BOOT_IMAGE:
            f.write(f"{byte:02X}\n")
    return out


# clk and reset
def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

async def apply_reset(dut, cycles=40_000):
    dut.rst_n.value    = 0
    dut.input_in.value = 0   # pass_thru_en=0, MISO=0
    dut.bidir_in.value = 0
    await ClockCycles(dut.clk, cycles)
    dut.rst_n.value = 1
    await Timer(1, unit="ns")


#test 1 — pass thru pad conenction check
#check if input_in[0] correctly controls bidir_oe for flash pins
@cocotb.test()
async def test_passthru_pad_oe(dut):
    print("\n=== TEST 1: pass-through pad output-enable control ===")
    start_clock(dut)
    dut.rst_n.value = 1
    dut.input_in.value = 0   # pass_thru_en = 0
    dut.bidir_in.value = 0
    await ClockCycles(dut.clk, 5)
    await Timer(1, unit="ns")

    # boot mode: pass_thru_en=0, chip should drive flash pads
    dut.input_in.value = 0
    await Timer(2, unit="ns")
    oe = int(dut.bidir_oe.value)
    sck_oe = (oe >> PAD_SCK)  & 1
    mosi_oe = (oe >> PAD_MOSI) & 1
    csb_oe = (oe >> PAD_CSB)  & 1
    print(f"  pass_thru_en=0:")
    print(f"    bidir_oe[{PAD_SCK}]  (SCK)  = {sck_oe}   (expected 1)")
    print(f"    bidir_oe[{PAD_MOSI}]  (MOSI) = {mosi_oe}   (expected 1)")
    print(f"    bidir_oe[{PAD_CSB}] (CSB)  = {csb_oe}   (expected 1)")
    assert sck_oe == 1, f"SCK  OE wrong in boot mode: got {sck_oe},  expected 1"
    assert mosi_oe == 1, f"MOSI OE wrong in boot mode: got {mosi_oe}, expected 1"
    assert csb_oe == 1, f"CSB  OE wrong in boot mode: got {csb_oe},  expected 1"

    #pass thru mode: pass_thru_en=1, chip should release pads
    dut.input_in.value = (1 << PAD_PASS_THRU_EN)
    await Timer(2, unit="ns")
    oe = int(dut.bidir_oe.value)
    sck_oe = (oe >> PAD_SCK)  & 1
    mosi_oe = (oe >> PAD_MOSI) & 1
    csb_oe = (oe >> PAD_CSB)  & 1
    print(f"\n  pass_thru_en=1:")
    print(f"    bidir_oe[{PAD_SCK}]  (SCK)  = {sck_oe}   (expected 0)")
    print(f"    bidir_oe[{PAD_MOSI}]  (MOSI) = {mosi_oe}   (expected 0)")
    print(f"    bidir_oe[{PAD_CSB}] (CSB)  = {csb_oe}   (expected 0)")
    assert sck_oe  == 0, f"SCK  OE wrong in pass-thru mode: got {sck_oe},  expected 0"
    assert mosi_oe == 0, f"MOSI OE wrong in pass-thru mode: got {mosi_oe}, expected 0"
    assert csb_oe  == 0, f"CSB  OE wrong in pass-thru mode: got {csb_oe},  expected 0"

    print("\n  *** PASS — pad output-enable correctly controlled by pass_thru_en")


# test 2- boot via pads: check SCK and MOSI appear on bidir_out
@cocotb.test()
async def test_spi_signals_reach_pads(dut):
    print("\n=== TEST 2: SPI signals reach pad outputs during boot ===")
    start_clock(dut)
    await apply_reset(dut)
    sck_transitions  = 0
    mosi_seen_high = False
    csb_went_low = False
    prev_sck = None
    timed_out = False

    for _ in range(100_000):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        bidir_out_val = int(dut.bidir_out.value)
        curr_sck = (bidir_out_val >> PAD_SCK)  & 1
        curr_mosi = (bidir_out_val >> PAD_MOSI) & 1
        curr_csb = (bidir_out_val >> PAD_CSB)  & 1

        if curr_csb == 0:
            csb_went_low = True
        if curr_mosi == 1:
            mosi_seen_high = True
        if prev_sck is not None and curr_sck != prev_sck:
            sck_transitions += 1
        prev_sck = curr_sck
        #stop once we seen enough SCK activity to be sure
        if sck_transitions >= 32:
            break
    else:
        timed_out = True

    print(f"  CSB went low:       {csb_went_low}   (expected True)")
    print(f"  MOSI seen high:     {mosi_seen_high}  (expected True)")
    print(f"  SCK transitions:    {sck_transitions} (expected >= 32)")
    assert csb_went_low, \
        "CSB never went low on bidir_out — flash_csb_o not reaching pad"
    assert sck_transitions >= 32, \
        f"SCK only toggled {sck_transitions} times — spi_sck_o not reaching pad"
    assert mosi_seen_high, \
        "MOSI never went high — spi_mosi_o not reaching pad"

    print("\n  *** PASS — SPI signals correctly routed to pad outputs")


#test 3- MISO pad routing (cypress model drives MISO through wrapper)
@cocotb.test()
async def test_miso_pad_routing(dut):
    print("\n=== TEST 3: MISO pad routing — Cypress model drives input_in[1] ===")
    start_clock(dut)
    await apply_reset(dut)
 
    timed_out = False
    for _ in range(500_000):
        await RisingEdge(dut.clk)
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True
 
    assert not timed_out, \
        ("boot_done never asserted. MISO from the Cypress model may not be "
         "reaching the SPI engine through input_in[PAD_MISO]. "
         "Check PAD_MISO index in chip_core.sv and the wrapper wiring.")
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o  = {int(dut.cores_en_o.value)}   (expected 1)")
    assert dut.cores_en_o.value == 1, "cores_en must be high after boot"
 
    print("\n  *** PASS — MISO correctly routed from Cypress model through "
          "input_in[1] to SPI engine")


#test 4- cores_en gating: stays low until boot completes
@cocotb.test()
async def test_cores_en_held_low_during_boot(dut):
    print("\n=== TEST 4: cores_en held low until boot completes ===")
    start_clock(dut)
    await apply_reset(dut)
    premature_cores_en = False
    boot_done_seen     = False
    timed_out          = False
 
    for _ in range(500_000):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        boot_done = int(dut.boot_done_o.value)
        cores_en  = int(dut.cores_en_o.value)
        if cores_en == 1 and boot_done == 0:
            premature_cores_en = True
            print("  ERROR: cores_en went high before boot_done!")
            break
        if boot_done == 1:
            boot_done_seen = True
            break
    else:
        timed_out = True
 
    assert not timed_out, "boot_done never asserted — Cypress model may not be responding"
    assert not premature_cores_en, \
        ("cores_en_o went high before boot_done_o. "
         "CPU cores would start fetching before SRAM is populated.")
    assert boot_done_seen, "boot_done never asserted"
    assert dut.cores_en_o.value == 1, "cores_en must be high after boot_done"
    print("  cores_en stayed low throughout entire boot")
    print("  cores_en went high exactly when boot_done asserted")
    print("\n  *** PASS — CPU reset gating is correct")


#runner
def chip_core_runner():
    proj_path = Path(__file__).resolve().parent
    sim_build  = proj_path / "sim_build"
    sim_build.mkdir(exist_ok=True)

    mem_path = write_boot_image_mem()
    print(f"[runner] wrote {mem_path}")

    import shutil
    secr_src = proj_path / "../ip/cypress_model/s25fl128lSECR.mem"
    if secr_src.exists():
        shutil.copy(secr_src, sim_build / "s25fl128lSECR.mem")

    sram_macro = (Path(pdk_root) / pdk /
                  "libs.ref/gf180mcu_fd_ip_sram/verilog/"
                  "gf180mcu_fd_ip_sram__sram512x8m8wm1.v")

    sources = [
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        proj_path / "../src/mem_ctrl/mem128x32.sv",
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        proj_path / "../ip/picorv32/picorv32.v",
        proj_path / "../ip/cypress_model/s25fl128l.v",
        proj_path / "../src/chip_core.sv",
        proj_path / "../src/housekeeping/chip_core_flash_tb.sv",
    ]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="chip_core_flash_tb",
        always=True,
        build_args=[],
        waves=True,
    )
    runner.test(
        hdl_toplevel="chip_core_flash_tb",
        test_module="chip_core_boot_tb",
        waves=True,
    )


if __name__ == "__main__":
    chip_core_runner()