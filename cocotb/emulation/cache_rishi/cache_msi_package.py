"""cache_model.py

Core golden-model components for an MSI cache subsystem.

This module intentionally contains only the pieces that model the cache and
coherence logic itself:

1. MSI constants and enums
2. A pure combinational MSI protocol model
3. Cache-line and set-associative cache storage
4. A behavioural SRAM model used by the controller-side model

The cache controller is kept in a separate module so that:
- the cache data structure can be unit tested in isolation
- the controller can import and reuse these classes cleanly
- cocotb and non-cocotb testbenches can build on the same core model
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


class MSIState(IntEnum):
    """MSI line state."""

    I = 0b00
    S = 0b01
    M = 0b10


class ProcEvent(IntEnum):
    """Processor-issued coherence event."""

    PR_RD = 0
    PR_WR = 1


class SnoopEvent(IntEnum):
    """Incoming coherence event observed on the bus/interposer."""

    BUS_RD = 0b00
    BUS_RDX = 0b01
    BUS_UPGR = 0b10


class CoherenceCmd(IntEnum):
    """Coherence command values that mirror the RTL header."""

    CMD_BUS_RD = 0
    CMD_BUS_RDX = 1
    CMD_BUS_UPGR = 2
    CMD_EVICT_CLEAN = 3
    CMD_EVICT_DIRTY = 4
    CMD_SNOOP_BUS_RD = 5
    CMD_SNOOP_BUS_RDX = 6
    CMD_SNOOP_BUS_UPGR = 7


@dataclass
class MSIOutput:
    """Outputs of one combinational MSI evaluation."""

    next_state: MSIState = MSIState.I
    cmd_valid: bool = False
    issue_cmd: Optional[CoherenceCmd] = None
    flush: bool = False


class MSIProtocol:
    """Pure combinational MSI state machine.

    Processor side:
      I + PR_RD  -> S, BUS_RD
      I + PR_WR  -> M, BUS_RDX
      S + PR_RD  -> S, no cmd
      S + PR_WR  -> M, BUS_UPGR
      M + PR_RD  -> M, no cmd
      M + PR_WR  -> M, no cmd

    Snoop side:
      I + BUS_*    -> I, no cmd
      S + BUS_RD   -> S, no cmd
      S + BUS_RDX  -> I, SNOOP_BUS_RDX
      S + BUS_UPGR -> I, SNOOP_BUS_UPGR
      M + BUS_RD   -> S, SNOOP_BUS_RD, flush
      M + BUS_RDX  -> I, SNOOP_BUS_RDX, flush
      M + BUS_UPGR -> illegal in MSI. If one cache truly owns M, another cache
                      should not be issuing BUS_UPGR for that line.
    """

    _PROC_TABLE = {
        (MSIState.I, ProcEvent.PR_RD): (MSIState.S, CoherenceCmd.CMD_BUS_RD, False),
        (MSIState.I, ProcEvent.PR_WR): (MSIState.M, CoherenceCmd.CMD_BUS_RDX, False),
        (MSIState.S, ProcEvent.PR_RD): (MSIState.S, None, False),
        (MSIState.S, ProcEvent.PR_WR): (MSIState.M, CoherenceCmd.CMD_BUS_UPGR, False),
        (MSIState.M, ProcEvent.PR_RD): (MSIState.M, None, False),
        (MSIState.M, ProcEvent.PR_WR): (MSIState.M, None, False),
    }

    _SNOOP_TABLE = {
        (MSIState.I, SnoopEvent.BUS_RD): (MSIState.I, None, False),
        (MSIState.I, SnoopEvent.BUS_RDX): (MSIState.I, None, False),
        (MSIState.I, SnoopEvent.BUS_UPGR): (MSIState.I, None, False),
        (MSIState.S, SnoopEvent.BUS_RD): (MSIState.S, None, False),
        (MSIState.S, SnoopEvent.BUS_RDX): (
            MSIState.I,
            CoherenceCmd.CMD_SNOOP_BUS_RDX,
            False,
        ),
        (MSIState.S, SnoopEvent.BUS_UPGR): (
            MSIState.I,
            CoherenceCmd.CMD_SNOOP_BUS_UPGR,
            False,
        ),
        (MSIState.M, SnoopEvent.BUS_RD): (
            MSIState.S,
            CoherenceCmd.CMD_SNOOP_BUS_RD,
            True,
        ),
        (MSIState.M, SnoopEvent.BUS_RDX): (
            MSIState.I,
            CoherenceCmd.CMD_SNOOP_BUS_RDX,
            True,
        ),
    }

    def evaluate(
        self,
        current_state: MSIState,
        proc_valid: bool,
        proc_event: Optional[ProcEvent],
        snoop_valid: bool,
        snoop_event: Optional[SnoopEvent],
    ) -> MSIOutput:
        """Evaluate one MSI transition.

        Exactly one of the processor or snoop paths should normally be used per
        call. If both valids are deasserted, the state machine holds state.
        """
        out = MSIOutput(next_state=current_state)

        if proc_valid and proc_event is not None:
            key = (current_state, proc_event)
            if key in self._PROC_TABLE:
                ns, cmd, flush = self._PROC_TABLE[key]
                out.next_state = ns
                out.cmd_valid = cmd is not None
                out.issue_cmd = cmd
                out.flush = flush
            return out

        if snoop_valid and snoop_event is not None:
            if current_state == MSIState.M and snoop_event == SnoopEvent.BUS_UPGR:
                raise RuntimeError(
                    "Illegal MSI event: snooped BUS_UPGR while line is in M"
                )

            key = (current_state, snoop_event)
            if key in self._SNOOP_TABLE:
                ns, cmd, flush = self._SNOOP_TABLE[key]
                out.next_state = ns
                out.cmd_valid = cmd is not None
                out.issue_cmd = cmd
                out.flush = flush

        return out


@dataclass
class CacheLine:
    """One cache line with MSI state and replacement metadata."""

    valid: bool = False
    state: MSIState = MSIState.I
    tag: int = 0
    data: List[int] = field(default_factory=lambda: [0] * 4)
    lru_counter: int = 0

    def invalidate(self) -> None:
        """Invalidate the line and clear its payload."""
        self.valid = False
        self.state = MSIState.I
        self.tag = 0
        self.data = [0] * len(self.data)

    def is_dirty(self) -> bool:
        """Return True when the line is resident and modified."""
        return self.valid and self.state == MSIState.M

    def is_resident(self) -> bool:
        """Return True when the line currently participates in coherence."""
        return self.valid and self.state != MSIState.I


class Cache:
    """Parameterised N-way set associative cache.

    Defaults model a 2 KiB cache:
      64 sets x 2 ways x 4 words/line x 4 bytes/word
    """

    def __init__(
        self,
        num_sets: int = 64,
        num_ways: int = 2,
        words_per_line: int = 4,
        addr_bits: int = 32,
    ):
        if not (num_sets and (num_sets & (num_sets - 1)) == 0):
            raise ValueError("num_sets must be a power of 2")
        if not (words_per_line and (words_per_line & (words_per_line - 1)) == 0):
            raise ValueError("words_per_line must be a power of 2")

        self.num_sets = num_sets
        self.num_ways = num_ways
        self.words_per_line = words_per_line
        self.addr_bits = addr_bits

        self.byte_offset_bits = 2
        self.word_offset_bits = int(math.log2(words_per_line))
        self.index_bits = int(math.log2(num_sets))
        self.tag_bits = (
            addr_bits
            - self.index_bits
            - self.word_offset_bits
            - self.byte_offset_bits
        )

        self.lines: List[List[CacheLine]] = [
            [CacheLine(data=[0] * words_per_line) for _ in range(num_ways)]
            for _ in range(num_sets)
        ]

        self._lru_tick = 0

    def decode_addr(self, addr: int) -> Tuple[int, int, int, int]:
        """Return (tag, set_index, word_offset, byte_offset)."""
        byte_offset = addr & 0x3
        word_offset = (addr >> self.byte_offset_bits) & (self.words_per_line - 1)
        set_index = (
            addr >> (self.byte_offset_bits + self.word_offset_bits)
        ) & (self.num_sets - 1)
        tag = addr >> (
            self.byte_offset_bits + self.word_offset_bits + self.index_bits
        )
        return tag, set_index, word_offset, byte_offset

    def make_line_addr(self, tag: int, set_index: int) -> int:
        """Reconstruct a line-aligned base byte address."""
        return (
            tag << (self.byte_offset_bits + self.word_offset_bits + self.index_bits)
        ) | (set_index << (self.byte_offset_bits + self.word_offset_bits))

    def lookup(self, addr: int) -> Tuple[bool, int, Optional[CacheLine]]:
        """Return (hit, way_index, line_or_none)."""
        tag, set_idx, _, _ = self.decode_addr(addr)
        for way, line in enumerate(self.lines[set_idx]):
            if line.valid and line.tag == tag and line.state != MSIState.I:
                return True, way, line
        return False, -1, None

    def _lru_victim(self, set_idx: int) -> Tuple[int, CacheLine]:
        """Return the least recently used victim way and line."""
        victim_way = min(
            range(self.num_ways),
            key=lambda w: self.lines[set_idx][w].lru_counter,
        )
        return victim_way, self.lines[set_idx][victim_way]

    def _touch(self, set_idx: int, way: int) -> None:
        """Mark a line as most recently used."""
        self._lru_tick += 1
        self.lines[set_idx][way].lru_counter = self._lru_tick

    def fill(self, addr: int, data_words: List[int], state: MSIState) -> None:
        """Install a line into the cache.

        The controller is expected to handle any eviction side effects before
        calling this method.
        """
        tag, set_idx, _, _ = self.decode_addr(addr)
        victim_way, victim = self._lru_victim(set_idx)

        victim.valid = True
        victim.state = state
        victim.tag = tag
        victim.data = list(data_words)
        self._touch(set_idx, victim_way)

    def update_word(self, addr: int, word: int, strobe: int) -> None:
        """Byte-strobed write into an already resident cache line."""
        _, set_idx, word_off, _ = self.decode_addr(addr)
        hit, way, line = self.lookup(addr)
        if not hit or line is None:
            raise RuntimeError(
                f"update_word called on non resident address 0x{addr:08X}"
            )

        current = line.data[word_off]
        result = 0
        for b in range(4):
            mask = 0xFF << (b * 8)
            if strobe & (1 << b):
                result |= word & mask
            else:
                result |= current & mask

        line.data[word_off] = result
        line.state = MSIState.M
        self._touch(set_idx, way)

    def read_word(self, addr: int) -> int:
        """Read a 32-bit word from a resident cache line."""
        _, _, word_off, _ = self.decode_addr(addr)
        hit, _, line = self.lookup(addr)
        if not hit or line is None:
            raise RuntimeError(
                f"read_word called on non resident address 0x{addr:08X}"
            )
        return line.data[word_off]

    def set_state(self, addr: int, state: MSIState) -> None:
        """Update the MSI state of a resident line."""
        hit, _, line = self.lookup(addr)
        if not hit or line is None:
            return

        line.state = state
        if state == MSIState.I:
            line.valid = False

    def flush_line(self, addr: int) -> Optional[CacheLine]:
        """Invalidate a resident line and return a copy of its prior contents."""
        tag, set_idx, _, _ = self.decode_addr(addr)
        for line in self.lines[set_idx]:
            if line.valid and line.tag == tag:
                evicted = CacheLine(
                    valid=True,
                    state=line.state,
                    tag=tag,
                    data=list(line.data),
                    lru_counter=line.lru_counter,
                )
                line.invalidate()
                return evicted
        return None


class SRAMModel:
    """Behavioural model of the GF180 mem_ctrl_512x32 memory array.

    The external interface is byte-addressed, but storage is word-based.
    Address bits [8:0] after shifting off the byte offset select the 32-bit
    word. Byte strobes are applied to each write.
    """

    MEM_DEPTH = 512

    def __init__(self):
        self._mem: List[int] = [0] * self.MEM_DEPTH

    def _word_addr(self, byte_addr: int) -> int:
        """Map an aligned byte address into the SRAM word index."""
        return (byte_addr >> 2) & 0x1FF

    def read(self, mem_addr: int) -> int:
        """Read one 32-bit word from the SRAM model."""
        return self._mem[self._word_addr(mem_addr)]

    def write(self, mem_addr: int, data: int, strobe: int) -> None:
        """Write one 32-bit word using the provided byte enable mask."""
        wa = self._word_addr(mem_addr)
        current = self._mem[wa]
        result = 0
        for b in range(4):
            mask = 0xFF << (b * 8)
            if strobe & (1 << b):
                result |= data & mask
            else:
                result |= current & mask
        self._mem[wa] = result

    def read_line(self, base_byte_addr: int, words: int) -> List[int]:
        """Read a full cache line from memory starting at a line base address."""
        return [self.read(base_byte_addr + i * 4) for i in range(words)]

    def write_line(self, base_byte_addr: int, data_words: List[int]) -> None:
        """Write back an entire cache line using full byte enables."""
        for i, word in enumerate(data_words):
            self.write(base_byte_addr + i * 4, word, 0xF)

    def load_program(self, data: List[int], start_word: int = 0) -> None:
        """Bulk-load a sequence of words into the SRAM model."""
        for i, val in enumerate(data):
            idx = start_word + i
            if idx >= self.MEM_DEPTH:
                break
            self._mem[idx] = val & 0xFFFF_FFFF


__all__ = [
    "MSIState",
    "ProcEvent",
    "SnoopEvent",
    "CoherenceCmd",
    "MSIOutput",
    "MSIProtocol",
    "CacheLine",
    "Cache",
    "SRAMModel",
]
