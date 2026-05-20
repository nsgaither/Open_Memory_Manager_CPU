from dataclasses import dataclass
from .msi_v2 import CoherenceCmd

@dataclass
class axi_request:

    """
    Axi Packet with Coherence commands
    ------------------------------------------------------------------------
    | mem_valid | mem_instr | mem_ready | mem_addr | mem_wdata | mem_wstrb |
    |   1 bit   |   1 bit   |   1 bit   |  32 bit  |   32 bit  |   4 bit   |
    ------------------------------------------------------------------------

    Used for the following communications:
        - cpu -> cache controller
        - cache controller -> cache sram
        - directory controller -> main sram memory
    """

    mem_valid: bool
    mem_instr: bool
    mem_ready: bool

    mem_addr: int
    mem_wdata: int
    mem_wstrb: int
    mem_rdata: int


@dataclass
class axi_and_coherence_request:
    """
    Axi Packet with Coherence commands
    --------------------------------------------------------------------------------------
    | mem_valid | mem_instr | mem_ready | mem_addr | mem_wdata | mem_wstrb | CoherenceCmd |
    |   1 bit   |   1 bit   |   1 bit   |  32 bit  |   32 bit  |   4 bit   |    3 bits    |
    --------------------------------------------------------------------------------------

    Used for the following communications:
        - cache controolers -> directory system
    """

    # basic axi stuff
    mem_valid: bool
    mem_instr: bool
    mem_ready: bool

    mem_addr: int
    mem_wdata_or_msi_payload: int
    mem_wstrb: int
    mem_rdata: int

    # extra data need for cache conhernce
    coherence_cmd: CoherenceCmd
    core_id: int






