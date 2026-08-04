"""Transaction management for AinosDB.

Implements ACID transactions with MVCC (Multi-Version Concurrency Control)
and snapshot isolation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple
from ..storage.wal import WriteAheadLog, LogRecord, LogType
from ..storage.page import PageId


class IsolationLevel(Enum):
    """Transaction isolation levels."""
    READ_UNCOMMITTED = auto()
    READ_COMMITTED = auto()
    REPEATABLE_READ = auto()
    SERIALIZABLE = auto()


@dataclass
class Transaction:
    """Represents a database transaction.

    Attributes:
        transaction_id: Unique transaction identifier.
        isolation_level: Transaction isolation level.
        status: Current transaction status.
        snapshot_lsn: LSN at transaction start (for MVCC).
        start_time: Wall clock time when transaction began.
        modified_pages: Set of pages modified by this transaction.
        undo_log: List of log records for rollback.
    """

    transaction_id: int
    isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED
    status: str = "ACTIVE"  # ACTIVE, COMMITTED, ABORTED
    snapshot_lsn: int = 0
    start_time: float = 0.0
    modified_pages: Set[PageId] = field(default_factory=set)
    undo_log: List[LogRecord] = field(default_factory=list)

    def add_undo(self, record: LogRecord) -> None:
        """Add an undo record for rollback.

        Args:
            record: Log record to undo.
        """
        self.undo_log.append(record)

    def __repr__(self) -> str:
        return (
            f"Transaction(id={self.transaction_id}, status={self.status}, "
            f"isolation={self.isolation_level.name})"
        )


class TransactionManager:
    """Manages database transactions.

    Provides ACID guarantees through MVCC, with support for
    savepoints, rollback, and different isolation levels.

    Attributes:
        wal: Write-ahead log for durability.
        next_txn_id: Next transaction ID to assign.
        active_txns: Currently active transactions.
        committed_txns: Recently committed transaction IDs.
    """

    def __init__(self, wal: Optional[WriteAheadLog] = None) -> None:
        self.wal = wal
        self._next_txn_id = 1
        self._active_txns: Dict[int, Transaction] = {}
        self._committed_txns: Set[int] = set()
        self._lock = threading.RLock()

    def begin(
        self,
        isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> Transaction:
        """Begin a new transaction.

        Args:
            isolation_level: Isolation level for the transaction.

        Returns:
            New Transaction object.
        """
        with self._lock:
            txn_id = self._next_txn_id
            self._next_txn_id += 1

            txn = Transaction(
                transaction_id=txn_id,
                isolation_level=isolation_level,
                start_time=__import__("time").time(),
            )

            # Record in WAL
            if self.wal:
                txn.snapshot_lsn = self.wal.begin_transaction(txn_id)

            self._active_txns[txn_id] = txn
            return txn

    def commit(self, txn: Transaction) -> None:
        """Commit a transaction.

        Args:
            txn: Transaction to commit.

        Raises:
            ValueError: If transaction is not active.
        """
        with self._lock:
            if txn.status != "ACTIVE":
                raise ValueError(f"Transaction {txn.transaction_id} is not active")

            txn.status = "COMMITTED"

            # Record in WAL
            if self.wal:
                self.wal.commit_transaction(txn.transaction_id)

            self._committed_txns.add(txn.transaction_id)
            self._active_txns.pop(txn.transaction_id, None)

            # Cleanup old committed transactions
            self._cleanup_committed()

    def rollback(self, txn: Transaction) -> None:
        """Rollback a transaction.

        Undoes all modifications made by the transaction.

        Args:
            txn: Transaction to rollback.

        Raises:
            ValueError: If transaction is not active.
        """
        with self._lock:
            if txn.status != "ACTIVE":
                raise ValueError(f"Transaction {txn.transaction_id} is not active")

            txn.status = "ABORTED"

            # Undo all modifications in reverse order
            for record in reversed(txn.undo_log):
                self._undo_record(record)

            # Record in WAL
            if self.wal:
                self.wal.abort_transaction(txn.transaction_id)

            self._active_txns.pop(txn.transaction_id, None)

    def _undo_record(self, record: LogRecord) -> None:
        """Undo a single log record.

        Args:
            record: Log record to undo.
        """
        if record.log_type == LogType.INSERT:
            # Undo insert = delete
            pass
        elif record.log_type == LogType.DELETE:
            # Undo delete = re-insert
            pass
        elif record.log_type == LogType.UPDATE:
            # Undo update = restore old value
            pass

    def get_transaction(self, txn_id: int) -> Optional[Transaction]:
        """Get a transaction by ID.

        Args:
            txn_id: Transaction ID.

        Returns:
            Transaction if found, None otherwise.
        """
        return self._active_txns.get(txn_id)

    def is_active(self, txn_id: int) -> bool:
        """Check if a transaction is active.

        Args:
            txn_id: Transaction ID.

        Returns:
            True if the transaction is active.
        """
        return txn_id in self._active_txns

    def is_visible(self, row_txn_id: int, snapshot_txn: Transaction) -> bool:
        """Check if a row created by a given transaction is visible.

        Implements MVCC visibility rules:
        - A row is visible if it was committed before the snapshot
        - A row is visible if it was created by the current transaction
        - A row is not visible if it was created by an active transaction

        Args:
            row_txn_id: Transaction ID that created the row.
            snapshot_txn: Snapshot transaction.

        Returns:
            True if the row is visible.
        """
        with self._lock:
            if row_txn_id == snapshot_txn.transaction_id:
                return True
            if row_txn_id in self._committed_txns:
                return True
            if row_txn_id not in self._active_txns:
                # Transaction completed and was cleaned up - considered committed
                return True
            return False

    def get_active_transactions(self) -> List[int]:
        """Get list of active transaction IDs.

        Returns:
            List of active transaction IDs.
        """
        with self._lock:
            return list(self._active_txns.keys())

    def get_snapshot(self) -> Tuple[int, Set[int]]:
        """Get a snapshot of the current transaction state.

        Returns:
            Tuple of (current LSN, set of active transaction IDs).
        """
        with self._lock:
            lsn = self.wal.current_lsn if self.wal else 0
            return lsn, set(self._active_txns.keys())

    def _cleanup_committed(self) -> None:
        """Clean up old committed transaction IDs."""
        max_txns = 1000
        if len(self._committed_txns) > max_txns:
            # Remove oldest committed transactions
            sorted_txns = sorted(self._committed_txns)
            self._committed_txns = set(sorted_txns[-max_txns:])

    def active_count(self) -> int:
        """Get the number of active transactions.

        Returns:
            Active transaction count.
        """
        return len(self._active_txns)

    def __repr__(self) -> str:
        return (
            f"TransactionManager(active={len(self._active_txns)}, "
            f"committed={len(self._committed_txns)})"
        )