"""Checkpoint management for AinosDB.

Implements fuzzy checkpointing that periodically writes dirty pages
to disk and records the checkpoint position in the WAL.
"""

from __future__ import annotations

import os
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from .page import PageId
from .wal import WriteAheadLog, LogRecord, LogType


class CheckpointManager:
    """Manages database checkpoints for crash recovery.

    Implements fuzzy checkpointing:
    1. Writes CHECKPOINT_BEGIN record to WAL
    2. Flushes all dirty pages to disk
    3. Writes CHECKPOINT_END record with active transaction list

    Attributes:
        wal: Write-ahead log instance.
        flush_func: Function to call for flushing dirty pages.
        checkpoint_interval: Number of WAL records between checkpoints.
        last_checkpoint_lsn: LSN of the last completed checkpoint.
        checkpoint_dir: Directory for checkpoint files.
    """

    __slots__ = (
        "wal", "flush_func", "checkpoint_interval", "last_checkpoint_lsn",
        "checkpoint_dir", "_lock", "_active_txns", "_in_progress",
    )

    CHECKPOINT_FILE = "checkpoint.ckp"

    def __init__(
        self,
        wal: WriteAheadLog,
        flush_func: Any,
        checkpoint_interval: int = 1000,
        checkpoint_dir: str = "./data",
    ) -> None:
        self.wal = wal
        self.flush_func = flush_func
        self.checkpoint_interval = checkpoint_interval
        self.last_checkpoint_lsn = 0
        self.checkpoint_dir = checkpoint_dir
        self._lock = threading.Lock()
        self._active_txns: Set[int] = set()
        self._in_progress = False

        os.makedirs(checkpoint_dir, exist_ok=True)

    def register_transaction(self, txn_id: int) -> None:
        """Register an active transaction.

        Args:
            txn_id: Transaction ID.
        """
        with self._lock:
            self._active_txns.add(txn_id)

    def unregister_transaction(self, txn_id: int) -> None:
        """Unregister a completed transaction.

        Args:
            txn_id: Transaction ID.
        """
        with self._lock:
            self._active_txns.discard(txn_id)

    def should_checkpoint(self, current_lsn: int) -> bool:
        """Check if a checkpoint is needed.

        Args:
            current_lsn: Current LSN.

        Returns:
            True if a checkpoint should be performed.
        """
        return (current_lsn - self.last_checkpoint_lsn) >= self.checkpoint_interval

    def checkpoint(self) -> int:
        """Perform a fuzzy checkpoint.

        Returns:
            LSN of the CHECKPOINT_END record.

        Raises:
            RuntimeError: If a checkpoint is already in progress.
        """
        if self._in_progress:
            raise RuntimeError("Checkpoint already in progress")

        self._in_progress = True

        try:
            # Write CHECKPOINT_BEGIN
            begin_record = LogRecord(log_type=LogType.CHECKPOINT_BEGIN)
            self.wal.append(begin_record)

            # Flush all dirty pages
            if self.flush_func:
                self.flush_func()

            # Get active transaction list
            with self._lock:
                active_txns = list(self._active_txns)

            # Write CHECKPOINT_END with active transaction list
            end_record = LogRecord(
                log_type=LogType.CHECKPOINT_END,
                key=active_txns,
                new_value=self.wal.current_lsn,
            )
            end_lsn = self.wal.append(end_record)

            # Save checkpoint state to disk
            self._save_checkpoint_state(end_lsn, active_txns)

            self.last_checkpoint_lsn = end_lsn
            return end_lsn

        finally:
            self._in_progress = False

    def _save_checkpoint_state(
        self, checkpoint_lsn: int, active_txns: List[int]
    ) -> None:
        """Save checkpoint state to a persistent file.

        Args:
            checkpoint_lsn: LSN of the checkpoint.
            active_txns: List of active transaction IDs.
        """
        file_path = os.path.join(self.checkpoint_dir, self.CHECKPOINT_FILE)
        data = struct.pack("!QI", checkpoint_lsn, len(active_txns))
        for txn_id in active_txns:
            data += struct.pack("!I", txn_id)

        # Write atomically
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, file_path)

    def load_checkpoint_state(self) -> Tuple[int, List[int]]:
        """Load checkpoint state from disk.

        Returns:
            Tuple of (last_checkpoint_lsn, active_transaction_ids).
        """
        file_path = os.path.join(self.checkpoint_dir, self.CHECKPOINT_FILE)
        if not os.path.exists(file_path):
            return 0, []

        with open(file_path, "rb") as f:
            data = f.read()

        checkpoint_lsn = struct.unpack_from("!Q", data, 0)[0]
        num_txns = struct.unpack_from("!I", data, 8)[0]
        offset = 12

        active_txns = []
        for _ in range(num_txns):
            txn_id = struct.unpack_from("!I", data, offset)[0]
            active_txns.append(txn_id)
            offset += 4

        return checkpoint_lsn, active_txns

    def recover(self) -> None:
        """Recover from the last checkpoint.

        Replays WAL records after the last checkpoint to restore
        database state.
        """
        checkpoint_lsn, active_txns = self.load_checkpoint_state()
        self.last_checkpoint_lsn = checkpoint_lsn

        # Replay WAL records after checkpoint
        records = self.wal.get_records_since(checkpoint_lsn)

        # Determine which transactions committed
        committed_txns: Set[int] = set()
        for record in records:
            if record.log_type == LogType.COMMIT:
                committed_txns.add(record.transaction_id)

        # Redo committed transactions, undo uncommitted ones
        for record in records:
            if record.log_type in (LogType.INSERT, LogType.UPDATE, LogType.DELETE):
                if record.transaction_id in committed_txns:
                    # Redo: apply the change
                    if self.flush_func:
                        self.flush_func(record)
                else:
                    # Undo: reverse the change
                    if record.old_value is not None:
                        if self.flush_func:
                            self.flush_func(record, undo=True)

    def get_checkpoint_info(self) -> Dict[str, Any]:
        """Get information about the current checkpoint state.

        Returns:
            Dictionary with checkpoint information.
        """
        return {
            "last_checkpoint_lsn": self.last_checkpoint_lsn,
            "active_transactions": list(self._active_txns),
            "checkpoint_interval": self.checkpoint_interval,
            "in_progress": self._in_progress,
        }

    def close(self) -> None:
        """Perform a final checkpoint and close."""
        try:
            self.checkpoint()
        except RuntimeError:
            pass

    def __repr__(self) -> str:
        return (
            f"CheckpointManager(last_lsn={self.last_checkpoint_lsn}, "
            f"active_txns={len(self._active_txns)})"
        )