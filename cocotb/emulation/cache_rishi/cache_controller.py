"""cache_controller_model.py

Controller-side golden model that composes the cache, MSI protocol, and SRAM
behavioural model into a processor-visible memory subsystem.

This file depends on cache_model.py and intentionally keeps all controller
policy in one place:
- handling read/write accesses from the core
- generating coherence commands on misses or upgrades
- performing replacement and explicit eviction command generation
- responding to snoop traffic from a bus, directory, or interposer layer
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from cache_model import (
    Cache,
    CoherenceCmd,
    MSIProtocol,
    MSIState,
    ProcEvent,
    SRAMModel,
    SnoopEvent,
)


class CacheTransaction:
    """Record of a completed processor-originated cache transaction."""

    __slots__ = (
        "addr",
        "is_write",
        "data",
        "strobe",
        "hit",
        "msi_before",
        "msi_after",
        "cmd_issued",
        "eviction_cmd",
        "stall_cycles",
    )

    def __init__(self):
        self.addr = 0
        self.is_write = False
        self.data = 0
        self.strobe = 0
        self.hit = False
        self.msi_before = MSIState.I
        self.msi_after = MSIState.I
        self.cmd_issued: Optional[CoherenceCmd] = None
        self.eviction_cmd: Optional[CoherenceCmd] = None
        self.stall_cycles = 0


class SnoopTransaction:
    """Record of a completed snoop transaction."""

    __slots__ = (
        "addr",
        "snoop_event",
        "hit",
        "msi_before",
        "msi_after",
        "cmd_issued",
        "flushed",
        "supplied_data",
    )

    def __init__(self):
        self.addr = 0
        self.snoop_event: Optional[SnoopEvent] = None
        self.hit = False
        self.msi_before = MSIState.I
        self.msi_after = MSIState.I
        self.cmd_issued: Optional[CoherenceCmd] = None
        self.flushed = False
        self.supplied_data: Optional[List[int]] = None


class CacheController:
    """MSI cache controller golden model.

    Public interfaces:
      access(mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb)
        -> (mem_rdata, mem_ready)

      snoop(addr, snoop_event)
        -> (supplied_data_or_none, flushed, issued_cmd)
    """

    MISS_PENALTY = 4

    def __init__(
        self,
        cache: Optional[Cache] = None,
        sram: Optional[SRAMModel] = None,
        miss_penalty: int = MISS_PENALTY,
    ):
        self.cache = cache or Cache()
        self.sram = sram or SRAMModel()
        self.msi = MSIProtocol()
        self.miss_penalty = miss_penalty

        self.stats = {
            "reads": 0,
            "writes": 0,
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "writebacks": 0,
        }

        self.log: List[CacheTransaction] = []
        self.snoop_log: List[SnoopTransaction] = []

    def access(
        self,
        mem_valid: bool,
        mem_instr: bool,
        mem_addr: int,
        mem_wdata: int = 0,
        mem_wstrb: int = 0,
    ) -> Tuple[int, bool]:
        """Service one core memory request.

        mem_wstrb == 0 means read.
        mem_wstrb != 0 means write.

        mem_instr is treated only as a hint in this behavioural model.
        """
        _ = mem_instr

        if not mem_valid:
            return 0, False

        is_write = mem_wstrb != 0
        proc_evt = ProcEvent.PR_WR if is_write else ProcEvent.PR_RD

        if is_write:
            self.stats["writes"] += 1
        else:
            self.stats["reads"] += 1

        hit, _, line = self.cache.lookup(mem_addr)
        current_state = line.state if hit and line is not None else MSIState.I

        txn = CacheTransaction()
        txn.addr = mem_addr
        txn.is_write = is_write
        txn.data = mem_wdata
        txn.strobe = mem_wstrb
        txn.hit = hit
        txn.msi_before = current_state

        msi_out = self.msi.evaluate(
            current_state=current_state,
            proc_valid=True,
            proc_event=proc_evt,
            snoop_valid=False,
            snoop_event=None,
        )
        txn.msi_after = msi_out.next_state
        txn.cmd_issued = msi_out.issue_cmd

        stall = 0
        if not hit:
            self.stats["misses"] += 1
            stall = self.miss_penalty
            txn.eviction_cmd = self._fill_line(mem_addr, msi_out.next_state)
        else:
            self.stats["hits"] += 1
            if msi_out.next_state != current_state:
                self.cache.set_state(mem_addr, msi_out.next_state)

        rdata = 0
        if is_write:
            self.cache.update_word(mem_addr, mem_wdata, mem_wstrb)
        else:
            rdata = self.cache.read_word(mem_addr)

        txn.stall_cycles = stall
        self.log.append(txn)
        return rdata, True

    def snoop(
        self,
        addr: int,
        snoop_event: SnoopEvent,
    ) -> Tuple[Optional[List[int]], bool, Optional[CoherenceCmd]]:
        """Handle one incoming snoop event."""
        hit, _, line = self.cache.lookup(addr)

        txn = SnoopTransaction()
        txn.addr = addr
        txn.snoop_event = snoop_event
        txn.hit = hit
        txn.msi_before = line.state if hit and line is not None else MSIState.I

        if not hit or line is None:
            txn.msi_after = MSIState.I
            self.snoop_log.append(txn)
            return None, False, None

        msi_out = self.msi.evaluate(
            current_state=line.state,
            proc_valid=False,
            proc_event=None,
            snoop_valid=True,
            snoop_event=snoop_event,
        )

        supplied_data = None
        flushed = False

        if msi_out.flush:
            base = self.cache.make_line_addr(line.tag, self._get_set(addr))
            self.sram.write_line(base, line.data)
            self.stats["writebacks"] += 1

            if snoop_event == SnoopEvent.BUS_RD:
                supplied_data = list(line.data)

        if msi_out.next_state == MSIState.I:
            self.cache.flush_line(addr)
            flushed = True
        elif msi_out.next_state != line.state:
            self.cache.set_state(addr, msi_out.next_state)

        txn.msi_after = msi_out.next_state
        txn.cmd_issued = msi_out.issue_cmd
        txn.flushed = flushed
        txn.supplied_data = supplied_data
        self.snoop_log.append(txn)

        return supplied_data, flushed, msi_out.issue_cmd

    def _get_set(self, addr: int) -> int:
        """Return the cache set index for a byte address."""
        c = self.cache
        return (addr >> (c.byte_offset_bits + c.word_offset_bits)) & (c.num_sets - 1)

    def _fill_line(
        self,
        addr: int,
        initial_state: MSIState,
    ) -> Optional[CoherenceCmd]:
        """Fetch a line from SRAM and explicitly model victim eviction traffic."""
        c = self.cache
        line_mask = ~((c.words_per_line * 4) - 1) & 0xFFFF_FFFF
        base_addr = addr & line_mask

        _, set_idx, _, _ = c.decode_addr(addr)
        _, victim = c._lru_victim(set_idx)

        eviction_cmd = None
        if victim.valid and victim.state != MSIState.I:
            self.stats["evictions"] += 1

            if victim.state == MSIState.M:
                eviction_cmd = CoherenceCmd.CMD_EVICT_DIRTY
                writeback_base = c.make_line_addr(victim.tag, set_idx)
                self.sram.write_line(writeback_base, victim.data)
                self.stats["writebacks"] += 1
            else:
                eviction_cmd = CoherenceCmd.CMD_EVICT_CLEAN

        data_words = self.sram.read_line(base_addr, c.words_per_line)
        c.fill(addr, data_words, initial_state)
        return eviction_cmd

    def print_stats(self) -> None:
        """Pretty-print controller statistics for debugging."""
        s = self.stats
        total = s["reads"] + s["writes"]
        hr = (s["hits"] / total * 100.0) if total else 0.0

        print(f"  Reads      : {s['reads']}")
        print(f"  Writes     : {s['writes']}")
        print(f"  Hits       : {s['hits']}")
        print(f"  Misses     : {s['misses']}")
        print(f"  Hit rate   : {hr:.1f}%")
        print(f"  Evictions  : {s['evictions']}")
        print(f"  Writebacks : {s['writebacks']}")

    def dump_log(self) -> None:
        """Print processor transaction history."""
        for i, t in enumerate(self.log):
            op = "WR" if t.is_write else "RD"
            proc_cmd = t.cmd_issued.name if t.cmd_issued is not None else "none"
            evict_cmd = t.eviction_cmd.name if t.eviction_cmd is not None else "none"
            print(
                f"  [{i:4d}] {op} addr=0x{t.addr:08X} "
                f"{'HIT ' if t.hit else 'MISS'} "
                f"{t.msi_before.name}->{t.msi_after.name} "
                f"proc_cmd={proc_cmd:<20} "
                f"evict_cmd={evict_cmd:<18} "
                f"stall={t.stall_cycles}"
            )

    def dump_snoop_log(self) -> None:
        """Print snoop transaction history."""
        for i, t in enumerate(self.snoop_log):
            ev = t.snoop_event.name if t.snoop_event is not None else "none"
            cmd = t.cmd_issued.name if t.cmd_issued is not None else "none"
            supplied = "yes" if t.supplied_data is not None else "no"
            print(
                f"  [{i:4d}] SNOOP addr=0x{t.addr:08X} "
                f"event={ev:<8} "
                f"{'HIT ' if t.hit else 'MISS'} "
                f"{t.msi_before.name}->{t.msi_after.name} "
                f"cmd={cmd:<20} "
                f"flushed={int(t.flushed)} "
                f"supplied={supplied}"
            )


__all__ = [
    "CacheTransaction",
    "SnoopTransaction",
    "CacheController",
]
