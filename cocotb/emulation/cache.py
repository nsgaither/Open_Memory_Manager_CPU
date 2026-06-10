# External
from dataclasses import dataclass

# Data Types & Consts
from typing import (Callable, Awaitable, Dict, List)
from .axi_request_types import (axi_and_coherence_request, axi_request)
from .msi import (MSIState, ProcessorEvent, SnoopEvent, CoherenceCmd, TransitionResult)
from .config import ( OFFSET_WIDTH, INDEX_WIDTH, TAG_WIDTH, NUM_CACHE_LINES)

# Functions
from .msi import (on_processor_event, on_snoop_event)
from .util import (apply_wstrb)


@dataclass
class CacheLine:
    """
    Represents a single cache line with tag, state, and data:
        - 32 bits long
        - tag, index, and offset size are determined by memory sizes in config
        - Structure: [ Tag | Index | Offset ]
        - For simplicity Offset will be 0 bits as wide cache line dont provide value
          due 2 pin constraits
    """

    tag: int = 0
    index: int = 0
    state: MSIState = MSIState.INVALID
    data: int = 0

    def __post_init__(self):
        # Calculate maximum values based on bit widths
        # A width of 10 bits means a max value of (2^10) - 1
        max_tag = (1 << TAG_WIDTH) - 1

        if not (0 <= self.tag <= max_tag):
            raise ValueError(f"Tag {self.tag} exceeds {TAG_WIDTH}-bit limit ({max_tag})")


class CacheController:
    """
    Cache controller implementing MSI coherence protocol.
    Handles processor requests and directory snoops.
    Fully associative for simulation simplicity.
    """

    def __init__(self, core_id: int, directory_axi_handler: Callable[[axi_and_coherence_request], Awaitable[axi_request]]) -> None:
        """
        Create a cache controller for a single core.

        Args:
            core_id (int): Cache identifier.
            directory_axi_handler (Callable): Directory request interface.
        """

        self.core_id: int = core_id
        self.arbiter_port: Callable[[axi_and_coherence_request], Awaitable[axi_request]] = directory_axi_handler
        self.lines: List[CacheLine] = []
        for i in range(NUM_CACHE_LINES):
            tag = (i >> INDEX_WIDTH) & ((1 << TAG_WIDTH) - 1)
            index = i & ((1 << INDEX_WIDTH) - 1)
            self.lines.append(CacheLine(tag=tag, index=index))


    def _line(self, addr: int) -> CacheLine:
        """
        Get or create the cache line for an address.

        Args:
            addr (int): address.
        """

        bit_mask_to_isolate_index: int = (1 << INDEX_WIDTH) - 1
        cache_line_addr: int = (addr >> OFFSET_WIDTH) & bit_mask_to_isolate_index
        return self.lines[cache_line_addr]

    async def _send_dir_cmd(self, cmd: CoherenceCmd, addr: int, payload: int = 0) -> axi_request:
        """
        Send a coherence command to the directory and returns its response.

        Args:
            cmd (CohereneceCmd: 3 bits): address.
            addr (32 bits): address of memory
            payload (32 bits): Optional payload containing data to write to main memory

        Returns:
            Response data from directory

        """

        # build axi + conherence request
        req: axi_and_coherence_request = axi_and_coherence_request(
            mem_valid = True,
            mem_ready = False,
            mem_instr = False,
            mem_addr = addr,
            mem_wdata_or_msi_payload = payload,
            mem_wstrb = 0xF,  # All bytes valid
            mem_rdata = 0,
            coherence_cmd = cmd,
            core_id = self.core_id
        )

        # print(req)
        # Send request to directory and get response

        # print("data sent to dir")
        # print(req)
        resp: axi_request = await self.arbiter_port(req)


        # Return data from directory (relevant for BUS_RD, BUS_RDX)
        # print("yo is this hit")
        return resp

    async def _send_dir_cmd_invalid(self) -> axi_request:

        req = axi_and_coherence_request(
            mem_valid=False,  # invalid = just a dummy to satisfy arbiter
            mem_ready=False,
            mem_instr=False,
            mem_addr=0,
            mem_wdata_or_msi_payload=0,
            mem_wstrb=0,
            mem_rdata=0,
            coherence_cmd=CoherenceCmd.NULL,
            core_id=self.core_id
        )

        return await self.arbiter_port(req)

    async def _handle_tag_mismatch(self, cache_line: CacheLine, request_addr: int) -> None:

        # skip if cacheline invalid
        if cache_line.state == MSIState.INVALID:
            return

        # isolate tag
        bit_mask_to_isolate_tag: int = (1 << TAG_WIDTH) - 1
        request_addr_tag: int = (request_addr) >> (OFFSET_WIDTH + INDEX_WIDTH) & bit_mask_to_isolate_tag

        # combine tag and index to make mem_addr
        shifted_tag: int = (cache_line.tag << TAG_WIDTH)
        tag_addr: int = shifted_tag | cache_line.index

        if cache_line.tag != request_addr_tag:
            # print("tag misatch")
            if cache_line.state == MSIState.SHARED:
                await self._send_dir_cmd(CoherenceCmd.EVICT_CLEAN, tag_addr, cache_line.data)
            elif cache_line.state == MSIState.MODIFIED:
                await self._send_dir_cmd(CoherenceCmd.EVICT_DIRTY, tag_addr, cache_line.data)

            cache_line.state = MSIState.INVALID

    async def _handle_cpu_read(self, request: axi_request) -> axi_request:
        """
        Handles CPU read request, takes cachlines current state and figure out next one using state machine provisioned in on_processor event

        Args:
            request: axi_request to read

        Returns:
            a axi_request repsone with handshake complete (connected to core.py)
        """

        if request.mem_valid == False:
            # print("invalid request")
            await self._send_dir_cmd_invalid() # need something to send to arbiter
            return request

        line: CacheLine = self._line(request.mem_addr)
        # print("this cache line for read")
        # print(line)

        # check if tags match
        await self._handle_tag_mismatch(line, request.mem_addr)

        # Ask state machine: what do we do for a read in current state?
        tr: TransitionResult = on_processor_event(line.state, ProcessorEvent.PR_RD)

        # If cache miss (or other condition requiring coherence transaction)
        if tr.issue_cmd is not None:
            # Fetch data from directory/memory and update cache line
            print("cache read miss")
            dir_resp: axi_request = await self._send_dir_cmd(tr.issue_cmd, request.mem_addr)
            if dir_resp.mem_ready:
                line.state = tr.next_state
                line.data = dir_resp.mem_rdata

        # we have data in cache so just pipe it straight through
        else:
            await self._send_dir_cmd_invalid() # need something to send to arbiter
            request.mem_rdata = line.data
            request.mem_ready = True
            return request

        # TODO: infinite loop when this commented
        # request.mem_ready = True

        # Update cache line state based on state machine result
        # line.state = tr.next_state
        # Return data to CPU
        return dir_resp


    async def _handle_cpu_write(self, request: axi_request) -> axi_request:

        """
        Handles CPU write request, takes cachlines current state and figure out next one using state machine provisioned in on_processor event

        Args:
            request: axi_request to write

        Returns:
            a axi_and_coherence_request repsone with handshake complete
            ie mem_ready and valid are both high

        """

        if request.mem_valid == False:
            # print("invalid request")
            await self._send_dir_cmd_invalid() # need something to send to arbiter
            return request

        line: CacheLine = self._line(request.mem_addr)

        # check if tags match
        await self._handle_tag_mismatch(line, request.mem_addr)

        # Ask state machine: what do we do for a write in current state?
        tr: TransitionResult = on_processor_event(line.state, ProcessorEvent.PR_WR)

        # print("right before dir_resp")
        # print(request)

        cache_rsp: axi_request = request
        # If we need exclusive access or need to fetch data
        if tr.issue_cmd is not None:
            dir_resp: axi_request = await self._send_dir_cmd(tr.issue_cmd, request.mem_addr)
            if dir_resp.mem_ready:
                line.state = tr.next_state
                # 1. Fill the line with data from memory
                if dir_resp.mem_rdata is not None:
                    line.data = dir_resp.mem_rdata
                # 2. Apply the CPU's specific byte updates
                line.data = apply_wstrb(line.data, request.mem_wdata, request.mem_wstrb)
                cache_rsp.mem_ready = dir_resp.mem_ready
        else:
            # cahce hit
            await self._send_dir_cmd_invalid() # need something to send to arbiter
            line.data = apply_wstrb(line.data, request.mem_wdata, request.mem_wstrb)
            cache_rsp.mem_ready = True

        # Return updated data
        # request.mem_ready = True
        return cache_rsp


    def _handle_snoop(self, request: axi_and_coherence_request) -> axi_and_coherence_request:

        """
        Handle snoop message from directory.

        Snoops occur when ANOTHER cache issues a coherence transaction that
        affects this cache's copy of the data. The directory sends snoop
        messages to coordinate between caches.

        Args:
            (pass in a axi_and_cohrence_request from it the following are used)
                addr: Memory address being snooped
                packed_cmd: Packed coherence command from directory

        Returns:
            Flushed data (if MODIFIED and flush required), else 0

        """

        line: CacheLine = self._line(request.mem_addr)
        cmd: CoherenceCmd = request.coherence_cmd

        # Note: requester and payload are currently unused but may be useful later
        requester: int = request.core_id
        payload: int = request.mem_rdata

        # Map coherence command to snoop event
        if cmd == int(CoherenceCmd.SNOOP_BUS_RD):
            event = SnoopEvent.BUS_RD
        elif cmd == int(CoherenceCmd.SNOOP_BUS_RDX):
            event = SnoopEvent.BUS_RDX
        elif cmd == int(CoherenceCmd.SNOOP_BUS_UPGR):
            event = SnoopEvent.BUS_UPGR
        else:
            raise ValueError(f"unknown snoop cmd {cmd}")

        # Ask state machine: how do we respond to this snoop?
        tr: TransitionResult = on_snoop_event(line.state, event)

        # If flush requested, provide our dirty data
        # Otherwise return 0 (no data needed)
        request.mem_wdata_or_msi_payload = line.data if tr.flush else 0

        # Update state (may invalidate or downgrade to SHARED)
        # print(f" line state before snoop is {line.state}")
        line.state = tr.next_state
        # print(f" line state after snoop is {line.state}")

        # Return flush data to directory
        request.mem_ready = True
        return request

    async def handle_request(self, request):
        """
        Unified handler for:
          - axi_request (CPU traffic)
          - axi_and_coherence_request (Directory / snoop traffic)
        """

        # ---------------------------
        # AXI CPU REQUEST
        # ---------------------------
        if isinstance(request, axi_request):

            # Ignore invalid requests
            if not request.mem_valid:
                request.mem_ready = False
                return request

            # CPU read or write
            if request.mem_wstrb == 0:
                request = await self._handle_cpu_read(request)
            else:
                request = await self._handle_cpu_write(request)

            request.mem_ready = True
            return request

        # ---------------------------
        # AXI + COHERENCE REQUEST
        # ---------------------------
        elif isinstance(request, axi_and_coherence_request):

            if not request.mem_valid:
                request.mem_ready = False
                return request

            request = self._handle_snoop(request)
            return request

        # ---------------------------
        # Unknown request type
        # ---------------------------
        else:
            raise TypeError(f"Unsupported request type: {type(request)}")



    async def axi_handler_for_core(self, request: axi_request) -> axi_request:

        """
        Core's AXI request handler - routes requests to appropriate handlers.
        This is the primary entry point for all communication with the cache and core.

        1. CPU Memory Traffic (axi_request):
           - Read: mem_wstrb == 0
           - Write: mem_wstrb != 0
           Routes to: _cpu_read() or _cpu_write()

        Args:
            request:
            AXI request from CPU

        Returns:
            AXI response with mem_ready=True and appropriate data to the core

        """

        # print("=== core to cache ===")
        # print(request)

        # CPU memory traffic: read or write
        if request.mem_wstrb == 0:
            # CPU read (write strobe = 0)
            request = await self._handle_cpu_read(request)
        else:
            # CPU write (write strobe != 0)
            request = await self._handle_cpu_write(request)


        # print("=== cache to core ===")
        # print(request)

        # Mark response as ready
        # request.mem_ready = True
        return request



    async def axi_and_coherence_handler(self, request: axi_and_coherence_request ) -> axi_and_coherence_request:

        """
        Core's axi+coherence request handler - routes requests to appropriate handlers.

        This is the primary entry point for all communication with the directory mainly just used for snoop requests.

        Args:
            AXI + Cohrence Cmd from directory

        Returns:
            AXI + Cohrence Cmd with mem_ready=True and appropriate data to the core
        """

        # Coherence traffic: snoop from directory

        # Error Handling
        if not request.mem_valid:
            request.mem_ready = False
            return request

        request = self._handle_snoop(request)
        # request.mem_ready = True  We shouldnt need this
        return request


    def dump_cache(self) -> None:

        for index, line in enumerate(self.lines):
            print(
              f"  Cache{self.core_id} addr:{index}"
              f" state={line.state.name:<8}|"
              f" data=0x{line.data}"
            )

    def flush_all(self) -> None:
        for line in self.lines:
            line.state = MSIState.INVALID





# CPU Address
#      ↓
# [ Tag | Index | Offset ]

#      ↓
# Select Set (Index)
#      ↓
# Compare Tags (parallel)
#      ↓
#  ┌───────────────┐
#  │ Hit?          │
#  └──────┬────────┘
#         │Yes
#         ↓
#    Use Offset → DONE

#         │No
#         ↓
#   Randomly pick a way
#         ↓
#   If M → write back
#         ↓
#   Load from memory
#         ↓
#   Update [Tag | State | Data]
#         ↓
#   Use Offset → DONE
