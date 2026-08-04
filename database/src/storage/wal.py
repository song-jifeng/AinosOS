"""Write-Ahead Log (WAL) for AinosDB.

Provides crash recovery by logging all modifications before they are
applied to the database pages. Supports REDO logging for recovery
after system crashes.
"""

from __future__ import annotations

import os
import struct
import threading
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple
from .page import PageId
from ..utils.serializer import Serializer


class LogType(IntEnum):
    """Types of log records."""
    BEGIN = 0
    COMMIT = 1
    ABORT = 2
    INSERT = 3
    DELETE = 4
    UPDATE = 5
    CHECKPOINT_BEGIN = 6
    CHECKPOINT_END = 7
    CLR = 8  # Compensation Log Record (for undo)


class LogRecord:
    """A single record in the write-ahead log.

    Attributes:
        lsn: Log Sequence Number (unique, monotonically increasing).
        log_type: Type of log record.
        transaction_id: ID of the transaction that created this record.
        page_id: Page affected by this operation (if applicable).
        key: Key affected (for index operations).
        old_value: Previous value (for undo).
        new_value: New value (for redo).
        prev_lsn: LSN of previous record in the same transaction.
    """

    __slots__ = (
        "lsn", "log_type", "transaction_id", "page_id",
        "key", "old_value", "new_value", "prev_lsn", "table_id",
    )

    HEADER_FORMAT = "!QIBIIIQQ"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(
        self,
        lsn: int = 0,
        log_type: LogType = LogType.BEGIN,
        transaction_id: int = 0,
        page_id: Optional[PageId] = None,
        key: Any = None,
        old_value: Any = None,
        new_value: Any = None,
        prev_lsn: int = 0,
        table_id: int = 0,
    ) -> None:
        self.lsn = lsn
        self.log_type = log_type
        self.transaction_id = transaction_id
        self.page_id = page_id
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.prev_lsn = prev_lsn
        self.table_id = table_id

    def serialize(self) -> bytes:
        """Serialize the log record to bytes.

        Returns:
            Binary representation of the log record.
        """
        page_num = self.page_id.page_num if self.page_id else -1
        page_table_id = self.page_id.table_id if self.page_id else self.table_id

        key_data = Serializer.encode(self.key) if self.key is not None else b""
        old_data = Serializer.encode(self.old_value) if self.old_value is not None else b""
        new_data = Serializer.encode(self.new_value) if self.new_value is not None else b""

        header = struct.pack(
            self.HEADER_FORMAT,
            self.lsn,
            int(self.log_type),
            self.transaction_id,
            page_num,
            page_table_id,
            self.prev_lsn,
            len(key_data),
            len(old_data),
        )

        return header + key_data + old_data + new_data + struct.pack("!I", len(new_data))

    @classmethod
    def deserialize(cls, data: bytes, offset: int = 0) -> Tuple["LogRecord", int]:
        """Deserialize a log record from bytes.

        Args:
            data: Binary data containing the record.
            offset: Starting offset.

        Returns:
            Tuple of (LogRecord, new offset).
        """
        (
            lsn, log_type_int, transaction_id, page_num,
            page_table_id, prev_lsn, key_len, old_len,
        ) = struct.unpack_from(cls.HEADER_FORMAT, data, offset)
        offset += cls.HEADER_SIZE

        new_len = struct.unpack_from("!I", data, offset)[0]
        offset += 4

        key = None
        old_value = None
        new_value = None

        if key_len > 0:
            key, _ = Serializer.decode(data, offset)
            offset += key_len

        if old_len > 0:
            old_value, _ = Serializer.decode(data, offset)
            offset += old_len

        if new_len > 0:
            new_value, _ = Serializer.decode(data, offset)
            offset += new_len

        page_id = PageId(page_num, page_table_id) if page_num >= 0 else None

        return cls(
            lsn=lsn,
            log_type=LogType(log_type_int),
            transaction_id=transaction_id,
            page_id=page_id,
            key=key,
            old_value=old_value,
            new_value=new_value,
            prev_lsn=prev_lsn,
            table_id=page_table_id,
        ), offset

    def __repr__(self) -> str:
        return (
            f"LogRecord(lsn={self.lsn}, type={self.log_type.name}, "
            f"txn={self.transaction_id})"
        )


class WriteAheadLog:
    """Write-ahead log for crash recovery.

    Maintains a sequential log of all database modifications.
    Supports REDO recovery after system crashes.

    Attributes:
        log_dir: Directory for log files.
        current_lsn: Current log sequence number.
        flushed_lsn: LSN up to which the log has been flushed to disk.
    """

    __slots__ = (
        "log_dir", "current_lsn", "flushed_lsn", "_log_file",
        "_log_file_num", "_lock", "_records", "_max_file_size",
    )

    MAX_FILE_SIZE = 64 * 1024 * 1024  # 64MB per log file

    def __init__(self, log_dir: str) -> None:
        self.log_dir = log_dir
        self.current_lsn = 0
        self.flushed_lsn = 0
        self._log_file_num = 0
        self._log_file: Optional[Any] = None
        self._lock = threading.Lock()
        self._records: Dict[int, LogRecord] = {}
        self._max_file_size = self.MAX_FILE_SIZE

        os.makedirs(log_dir, exist_ok=True)
        self._open_log_file()

    def _open_log_file(self) -> None:
        """Open a new log file for writing."""
        if self._log_file:
            self._log_file.close()

        file_path = os.path.join(
            self.log_dir, f"log_{self._log_file_num:08d}.wal"
        )
        self._log_file = open(file_path, "ab")
        self._log_file_num += 1

    def _rotate_log(self) -> None:
        """Rotate to a new log file when current file is too large."""
        if self._log_file and self._log_file.tell() >= self._max_file_size:
            self._open_log_file()

    def append(self, record: LogRecord) -> int:
        """Append a log record to the WAL.

        Args:
            record: LogRecord to append (lsn will be assigned).

        Returns:
            LSN assigned to the record.
        """
        with self._lock:
            self.current_lsn += 1
            record.lsn = self.current_lsn
            self._records[record.lsn] = record

            data = record.serialize()
            if self._log_file:
                self._log_file.write(data)
                self._log_file.flush()
                os.fsync(self._log_file.fileno())

            self.flushed_lsn = self.current_lsn
            self._rotate_log()

            return record.lsn

    def begin_transaction(self, transaction_id: int) -> int:
        """Record the start of a transaction.

        Args:
            transaction_id: Transaction ID.

        Returns:
            LSN of the BEGIN record.
        """
        record = LogRecord(
            log_type=LogType.BEGIN,
            transaction_id=transaction_id,
        )
        return self.append(record)

    def commit_transaction(self, transaction_id: int) -> int:
        """Record the commit of a transaction.

        Args:
            transaction_id: Transaction ID.

        Returns:
            LSN of the COMMIT record.
        """
        record = LogRecord(
            log_type=LogType.COMMIT,
            transaction_id=transaction_id,
        )
        return self.append(record)

    def abort_transaction(self, transaction_id: int) -> int:
        """Record the abort of a transaction.

        Args:
            transaction_id: Transaction ID.

        Returns:
            LSN of the ABORT record.
        """
        record = LogRecord(
            log_type=LogType.ABORT,
            transaction_id=transaction_id,
        )
        return self.append(record)

    def log_insert(
        self,
        transaction_id: int,
        page_id: PageId,
        key: Any,
        value: Any,
    ) -> int:
        """Log an insert operation.

        Args:
            transaction_id: Transaction ID.
            page_id: Page affected.
            key: Inserted key.
            value: Inserted value.

        Returns:
            LSN of the INSERT record.
        """
        record = LogRecord(
            log_type=LogType.INSERT,
            transaction_id=transaction_id,
            page_id=page_id,
            key=key,
            new_value=value,
        )
        return self.append(record)

    def log_delete(
        self,
        transaction_id: int,
        page_id: PageId,
        key: Any,
        old_value: Any,
    ) -> int:
        """Log a delete operation.

        Args:
            transaction_id: Transaction ID.
            page_id: Page affected.
            key: Deleted key.
            old_value: Previous value.

        Returns:
            LSN of the DELETE record.
        """
        record = LogRecord(
            log_type=LogType.DELETE,
            transaction_id=transaction_id,
            page_id=page_id,
            key=key,
            old_value=old_value,
        )
        return self.append(record)

    def log_update(
        self,
        transaction_id: int,
        page_id: PageId,
        key: Any,
        old_value: Any,
        new_value: Any,
    ) -> int:
        """Log an update operation.

        Args:
            transaction_id: Transaction ID.
            page_id: Page affected.
            key: Updated key.
            old_value: Previous value.
            new_value: New value.

        Returns:
            LSN of the UPDATE record.
        """
        record = LogRecord(
            log_type=LogType.UPDATE,
            transaction_id=transaction_id,
            page_id=page_id,
            key=key,
            old_value=old_value,
            new_value=new_value,
        )
        return self.append(record)

    def get_record(self, lsn: int) -> Optional[LogRecord]:
        """Get a log record by LSN.

        Args:
            lsn: Log Sequence Number.

        Returns:
            LogRecord if found, None otherwise.
        """
        return self._records.get(lsn)

    def get_records_since(self, lsn: int) -> List[LogRecord]:
        """Get all log records with LSN > given LSN.

        Args:
            lsn: Starting LSN (exclusive).

        Returns:
            List of log records.
        """
        return [
            record for lsn_val, record in sorted(self._records.items())
            if lsn_val > lsn
        ]

    def truncate(self, up_to_lsn: int) -> None:
        """Remove log records up to a given LSN.

        Args:
            up_to_lsn: Remove records with LSN <= this value.
        """
        with self._lock:
            self._records = {
                lsn: record for lsn, record in self._records.items()
                if lsn > up_to_lsn
            }

    def replay(self, recovery_func: Any) -> None:
        """Replay log records for crash recovery.

        Args:
            recovery_func: Function to call for each log record.
        """
        log_files = sorted(
            f for f in os.listdir(self.log_dir) if f.endswith(".wal")
        )

        for log_file in log_files:
            file_path = os.path.join(self.log_dir, log_file)
            with open(file_path, "rb") as f:
                data = f.read()
                offset = 0
                while offset < len(data):
                    try:
                        record, offset = LogRecord.deserialize(data, offset)
                        self._records[record.lsn] = record
                        self.current_lsn = max(self.current_lsn, record.lsn)
                        if recovery_func:
                            recovery_func(record)
                    except (struct.error, ValueError, IndexError):
                        break

        self.flushed_lsn = self.current_lsn

    def close(self) -> None:
        """Close the WAL and flush all pending records."""
        with self._lock:
            if self._log_file:
                self._log_file.flush()
                os.fsync(self._log_file.fileno())
                self._log_file.close()
                self._log_file = None

    def __repr__(self) -> str:
        return (
            f"WriteAheadLog(dir={self.log_dir}, current_lsn={self.current_lsn}, "
            f"flushed_lsn={self.flushed_lsn})"
        )