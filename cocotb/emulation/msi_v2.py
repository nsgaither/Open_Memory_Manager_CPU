"""
MSI Cache Coherence Protocol - State Machine Core Module

This module defines the MSI (Modified-Shared-Invalid) protocol state machine and 
core data structures used by both cache controllers and the directory controller.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

# ============================================================================
# MSI Protocol States and Events
# ============================================================================

class MSIState(IntEnum):
    """
    MSI cache coherence states.
    
    State Meanings:
    - INVALID: Cache line not present or invalidated (no copy exists)
    - SHARED: Read-only copy, may be shared with other caches
    - MODIFIED: Exclusive, dirty copy (must write back on eviction)
    
    State Invariants:
    1. At most one cache can be in MODIFIED for any address
    2. If one cache is MODIFIED, all others must be INVALID
    3. Multiple caches can be SHARED simultaneously
    """
    INVALID = 0   # No valid copy in this cache
    SHARED = 1    # Read-only copy (clean)
    MODIFIED = 2  # Read-write copy (dirty)


class ProcessorEvent(IntEnum):
    """
    Processor-initiated events (CPU → Cache).
    
    These represent CPU memory operations that trigger cache state transitions.
    
    PR_RD: Processor Read
        - CPU wants to read from this address
        - May cause cache miss (state transition)
    
    PR_WR: Processor Write
        - CPU wants to write to this address
        - May require exclusive access (upgrade or miss)
    """
    PR_RD = 0  # Processor read request
    PR_WR = 1  # Processor write request


class SnoopEvent(IntEnum):
    """
    Snoop events (Directory → Cache via snoop messages).
    
    These represent coherence operations from other caches that this cache
    must respond to. Snoops are triggered by the directory when another
    cache issues a bus transaction.
    
    BUS_RD: Another cache is reading (BusRd transaction)
        - This cache may need to share if in MODIFIED state
    
    BUS_RDX: Another cache is writing (BusRdX transaction)
        - This cache must invalidate and possibly flush dirty data
    
    BUS_UPGR: Another cache is upgrading from SHARED to MODIFIED
        - This cache must invalidate (no flush needed - data already shared)
    """
    BUS_RD = 1     # Another cache issued BusRd (read miss)
    BUS_RDX = 2    # Another cache issued BusRdX (write miss)
    BUS_UPGR = 4   # Another cache issued BusUpgr (write hit in Shared)


class CoherenceCmd(IntEnum):
    """
    Coherence command types for cache-directory communication.
    
    Commands are divided into two categories:
    
    1. Cache → Directory (bus transactions):
       - BUS_RD: Read miss, need data
       - BUS_RDX: Write miss, need exclusive access
       - BUS_UPGR: Upgrade from SHARED to MODIFIED (already have data)
       - EVICT_CLEAN: Evicting SHARED line (no writeback needed)
       - EVICT_DIRTY: Evicting MODIFIED line (writeback included)
    
    2. Directory → Cache (snoop commands):
       - SNOOP_BUS_RD: Another cache is reading, share if MODIFIED
       - SNOOP_BUS_RDX: Another cache is writing, invalidate and flush if MODIFIED
       - SNOOP_BUS_UPGR: Another cache is upgrading, invalidate
    
    Note: Values are chosen to avoid conflicts (snoops start at 17)
    """
    # Cache-to-Directory commands (values 1-5)
    BUS_RD = 1        # Read request (cache miss on read)
    BUS_RDX = 2       # Read-exclusive request (cache miss on write)
    BUS_UPGR = 4      # Upgrade request (cache hit on write in SHARED state)
    EVICT_CLEAN = 8   # Evict SHARED line (no data)
    EVICT_DIRTY = 16   # Evict MODIFIED line (includes writeback data)
    
    # Directory-to-Cache commands (values 17-19, offset to avoid conflicts)
    SNOOP_BUS_RD = 17    # Snoop: another cache reading
    SNOOP_BUS_RDX = 18   # Snoop: another cache writing
    SNOOP_BUS_UPGR = 19  # Snoop: another cache upgrading


# ============================================================================
# State Transition Result
# ============================================================================

@dataclass
class TransitionResult:
    """
    Result of an MSI state transition.
    
    Used by both on_processor_event() and on_snoop_event() to indicate:
    1. What the new cache state should be
    2. Whether a coherence command should be issued to the directory
    3. Whether data needs to be flushed (for snoops only)
    
    Fields:
        next_state: The new MSI state after this transition
        issue_cmd: Coherence command to send to directory (None if no action needed)
        flush: Whether to flush data back (for snoop events on MODIFIED lines)
    
    Examples:
        # Read miss in INVALID state
        TransitionResult(SHARED, BUS_RD, False)
        
        # Write hit in MODIFIED state (no bus transaction needed)
        TransitionResult(MODIFIED, None, False)
        
        # Snoop BusRd while MODIFIED (flush data, downgrade to SHARED)
        TransitionResult(SHARED, None, True)
    """
    next_state: MSIState           # New state after transition
    issue_cmd: Optional[CoherenceCmd] = None  # Command to issue (or None)
    flush: bool = False            # Whether to flush data (snoop only)

# ============================================================================
# MSI State Machine - Processor Events
# ============================================================================

def on_processor_event(state: MSIState, event: ProcessorEvent) -> TransitionResult:
    """
    MSI state transition for processor-initiated events (CPU operations).
    
    This function implements the core MSI protocol logic for CPU reads and writes.
    It determines:
    1. What the new cache state should be
    2. Whether a bus transaction needs to be issued to the directory
    
    State Transition Table:
    
    Current State | Event  | Next State | Bus Transaction | Notes
    --------------|--------|------------|-----------------|---------------------------
    INVALID       | PR_RD  | SHARED     | BUS_RD          | Read miss, fetch from memory
    INVALID       | PR_WR  | MODIFIED   | BUS_RDX         | Write miss, get exclusive
    SHARED        | PR_RD  | SHARED     | None            | Read hit, no action needed
    SHARED        | PR_WR  | MODIFIED   | BUS_UPGR        | Upgrade to exclusive, invalidate others
    MODIFIED      | PR_RD  | MODIFIED   | None            | Read hit, data already exclusive
    MODIFIED      | PR_WR  | MODIFIED   | None            | Write hit, data already exclusive
    
    Args:
        state: Current MSI state of the cache line
        event: Processor event (PR_RD or PR_WR)
    
    Returns:
        TransitionResult with next_state and optional issue_cmd
    
    Example Usage (in CacheController):
        line = self._line(addr)
        tr = on_processor_event(line.state, ProcessorEvent.PR_RD)
        
        # If command needs to be issued, send to directory
        if tr.issue_cmd is not None:
            line.data = self._send_dir_cmd(tr.issue_cmd, addr)
        
        # Update cache line state
        line.state = tr.next_state
    """
    
    # ---- INVALID State ----
    # Cache line not present - must fetch from memory/directory
    if state == MSIState.INVALID:
        if event == ProcessorEvent.PR_RD:
            # Read miss: Fetch data and transition to SHARED
            # Issue BUS_RD to directory to get data
            return TransitionResult(MSIState.SHARED, CoherenceCmd.BUS_RD, False)
        else:  # PR_WR
            # Write miss: Fetch data and transition to MODIFIED (exclusive)
            # Issue BUS_RDX to directory to get data and invalidate others
            return TransitionResult(MSIState.MODIFIED, CoherenceCmd.BUS_RDX, False)
    
    # ---- SHARED State ----
    # Cache line present in read-only form
    if state == MSIState.SHARED:
        if event == ProcessorEvent.PR_RD:
            # Read hit: Data already present, no action needed
            return TransitionResult(MSIState.SHARED, None, False)
        else:  # PR_WR
            # Write upgrade: Already have data, just need exclusive access
            # Issue BUS_UPGR to invalidate other sharers (no data transfer)
            return TransitionResult(MSIState.MODIFIED, CoherenceCmd.BUS_UPGR, False)
    
    # ---- MODIFIED State ----
    # Cache line present in exclusive/dirty form
    if state == MSIState.MODIFIED:
        # Both reads and writes hit - data is already exclusive
        # No bus transaction needed for either operation
        return TransitionResult(MSIState.MODIFIED, None, False)
    
    # Should never reach here if state is valid
    raise ValueError("invalid MSI state")


# ============================================================================
# MSI State Machine - Snoop Events
# ============================================================================

def on_snoop_event(state: MSIState, event: SnoopEvent) -> TransitionResult:
    """
    MSI state transition for snoop events (coherence messages from directory).
    
    This function implements how a cache responds to coherence operations
    initiated by OTHER caches. The directory sends snoop commands when another
    cache needs to:
    - Read data (BUS_RD) - may need to share
    - Write data (BUS_RDX) - must invalidate
    - Upgrade to exclusive (BUS_UPGR) - must invalidate
    
    State Transition Table:
    
    Current State | Snoop Event | Next State | Flush Data? | Notes
    --------------|-------------|------------|-------------|---------------------------
    INVALID       | Any         | INVALID    | No          | No copy, ignore snoop
    SHARED        | BUS_RD      | SHARED     | No          | Other cache reading, stay shared
    SHARED        | BUS_RDX     | INVALID    | No          | Other cache writing, invalidate
    SHARED        | BUS_UPGR    | INVALID    | No          | Other cache upgrading, invalidate
    MODIFIED      | BUS_RD      | SHARED     | Yes         | Other cache reading, share data
    MODIFIED      | BUS_RDX     | INVALID    | Yes         | Other cache writing, flush & invalidate
    MODIFIED      | BUS_UPGR    | MODIFIED   | No          | Can't happen (would be SHARED)
    
    Args:
        state: Current MSI state of the cache line
        event: Snoop event (BUS_RD, BUS_RDX, or BUS_UPGR)
    
    Returns:
        TransitionResult with next_state and flush flag
        - flush=True means cache must provide data (send back in mem_rdata)
    
    Example Usage (in CacheController):
        line = self._line(addr)
        tr = on_snoop_event(line.state, SnoopEvent.BUS_RD)
        
        # If flush requested, include data in response
        flush_data = line.data if tr.flush else 0
        
        # Update state
        line.state = tr.next_state
        
        # Return flush data to directory
        return flush_data
    """
    
    # ---- INVALID State ----
    # No copy of this line - ignore all snoops
    if state == MSIState.INVALID:
        # Cache doesn't have this line, no action needed
        return TransitionResult(MSIState.INVALID, None, False)
    
    # ---- SHARED State ----
    # Read-only copy - may need to invalidate
    if state == MSIState.SHARED:
        if event == SnoopEvent.BUS_RD:
            # Another cache reading: stay SHARED (data is clean in memory)
            # No flush needed - data will come from memory
            return TransitionResult(MSIState.SHARED, None, False)
        else:  # BUS_RDX or BUS_UPGR
            # Another cache writing/upgrading: must invalidate our copy
            # No flush needed - data is clean (SHARED is read-only)
            return TransitionResult(MSIState.INVALID, None, False)
    
    # ---- MODIFIED State ----
    # Exclusive/dirty copy - may need to flush and downgrade/invalidate
    if state == MSIState.MODIFIED:
        if event == SnoopEvent.BUS_RD:
            # Another cache reading: must share
            # Flush dirty data, downgrade to SHARED
            # Directory will update memory and send data to requester
            return TransitionResult(MSIState.SHARED, None, True)
        
        if event == SnoopEvent.BUS_RDX:
            # Another cache writing: must invalidate
            # Flush dirty data and transition to INVALID
            # Directory will send data to new owner
            return TransitionResult(MSIState.INVALID, None, True)
        
        # BUS_UPGR while MODIFIED shouldn't happen in MSI protocol
        # BusUpgr is only issued from SHARED state, and only one cache
        # can be MODIFIED at a time. If we're MODIFIED, others must be INVALID.
        # This is a protocol violation, but we handle it gracefully by staying MODIFIED
        return TransitionResult(MSIState.MODIFIED, None, False)
    
    # Should never reach here if state is valid
    raise ValueError("invalid MSI state")


