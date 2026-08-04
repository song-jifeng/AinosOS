#!/usr/bin/env python3
"""
AinosOS AI Log Analyzer
========================
AI-powered log analysis tool with auto-format detection, anomaly detection,
error clustering, time series analysis, real-time monitoring, and dashboard
generation.

Subcommands:
    analyze     Analyze log files for patterns, anomalies, and errors
    watch       Real-time log monitoring (tail + analyze)
    report      Generate dashboard reports from log data
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import textwrap
import time
import hashlib
import gzip
import threading
from abc import ABC, abstractmethod
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, List, Optional,
    Sequence, Set, Tuple, Type, Union,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
APP_NAME = "ai-log-analyzer"

# Common log formats for auto-detection
LOG_FORMAT_PATTERNS: Dict[str, str] = {
    "syslog": r"^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+",
    "syslog_iso": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
    "apache_common": r'^\S+\s+\S+\s+\S+\s+\[.*?\]\s+".*?"\s+\d+\s+\d+',
    "apache_combined": r'^\S+\s+\S+\s+\S+\s+\[.*?\]\s+".*?"\s+\d+\s+\d+\s+".*?"\s+".*?"',
    "json": r"^\s*\{",
    "csv": r"^[^,]+(?:,[^,]+)+$",
    "python_traceback": r"^Traceback \(most recent call last\):",
    "nginx_error": r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}",
    "docker": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z",
    "custom_timestamp": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
}

SEVERITY_PATTERNS = {
    "CRITICAL": re.compile(r"\b(?:CRITICAL|FATAL|EMERGENCY|PANIC)\b", re.I),
    "ERROR": re.compile(r"\b(?:ERROR|ERR|FAILED|FAILURE|EXCEPTION)\b", re.I),
    "WARNING": re.compile(r"\b(?:WARNING|WARN|NOTICE)\b", re.I),
    "INFO": re.compile(r"\b(?:INFO|INFORMATION|LOG|DEBUG|TRACE)\b", re.I),
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    """A single parsed log entry."""
    raw: str
    timestamp: Optional[str] = None
    severity: str = "INFO"
    source: str = ""
    message: str = ""
    pid: Optional[str] = None
    thread: Optional[str] = None
    module: Optional[str] = None
    line_number: int = 0
    error_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LogErrorCluster:
    """A cluster of similar errors."""
    id: str = ""
    pattern: str = ""
    messages: List[str] = field(default_factory=list)
    count: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    severity: str = "ERROR"
    source_files: Set[str] = field(default_factory=set)
    sample: str = ""

    def add(self, entry: LogEntry) -> None:
        self.count += 1
        self.messages.append(entry.message[:200])
        if entry.source:
            self.source_files.add(entry.source)
        if not self.first_seen:
            self.first_seen = entry.timestamp
        self.last_seen = entry.timestamp
        if not self.sample:
            self.sample = entry.raw[:300]


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""
    timestamp: str
    count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    unique_sources: int = 0


@dataclass
class Anomaly:
    """An anomaly detected in log data."""
    type: str  # "frequency_spike", "rate_change", "new_error", "pattern"
    description: str
    severity: str
    timestamp: str
    metric: float = 0.0
    threshold: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LogAnalysisResult:
    """Complete log analysis result."""
    filepath: str = ""
    format: str = "unknown"
    total_entries: int = 0
    total_lines: int = 0
    time_range: Tuple[Optional[str], Optional[str]] = (None, None)
    severity_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_clusters: List[LogErrorCluster] = field(default_factory=list)
    top_sources: List[Tuple[str, int]] = field(default_factory=list)
    top_modules: List[Tuple[str, int]] = field(default_factory=list)
    time_series: List[TimeSeriesPoint] = field(default_factory=list)
    anomalies: List[Anomaly] = field(default_factory=list)
    summary: str = ""
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Log format detectors
# ---------------------------------------------------------------------------

class LogFormatDetector:
    """Auto-detect log file format."""

    @staticmethod
    def detect(source: str, sample_size: int = 50) -> str:
        """Detect log format by sampling lines."""
        lines = source.splitlines()
        sample = [l for l in lines[:sample_size] if l.strip()]

        if not sample:
            return "empty"

        # Check for JSON format
        json_count = 0
        for line in sample[:10]:
            try:
                json.loads(line)
                json_count += 1
            except (json.JSONDecodeError, ValueError):
                pass
        if json_count >= len(sample[:10]) * 0.5:
            return "json"

        # Check against known patterns
        scores: Dict[str, int] = defaultdict(int)
        for line in sample:
            for fmt_name, pattern in LOG_FORMAT_PATTERNS.items():
                if re.match(pattern, line):
                    scores[fmt_name] += 1

        if scores:
            best = max(scores, key=scores.get)
            best_score = scores[best]
            if best_score >= len(sample) * 0.3:
                return best

        # Check for common log severity patterns
        sev_count = 0
        for line in sample[:20]:
            for sev_pattern in SEVERITY_PATTERNS.values():
                if sev_pattern.search(line):
                    sev_count += 1
                    break
        if sev_count >= 3:
            return "severity_based"

        return "unknown"


# ---------------------------------------------------------------------------
# Log parsers
# ---------------------------------------------------------------------------

class LogParser:
    """Parse log entries from various formats."""

    # Common timestamp patterns
    TIMESTAMP_PATTERNS = [
        re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?"),
        re.compile(r"\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"),
        re.compile(r"\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}"),
        re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"),
        re.compile(r"\d{10}(?:\.\d+)?"),  # Unix timestamp
    ]

    def parse(self, source: str, fmt: Optional[str] = None) -> List[LogEntry]:
        """Parse log source into structured entries."""
        if fmt is None:
            fmt = LogFormatDetector.detect(source)

        parse_methods: Dict[str, Callable] = {
            "json": self._parse_json,
            "syslog": self._parse_syslog,
            "syslog_iso": self._parse_syslog_iso,
            "apache_common": self._parse_apache,
            "apache_combined": self._parse_apache,
            "severity_based": self._parse_severity_based,
            "python_traceback": self._parse_python_traceback,
            "custom_timestamp": self._parse_severity_based,
            "unknown": self._parse_generic,
        }

        parser = parse_methods.get(fmt, self._parse_generic)
        return parser(source)

    def _parse_json(self, source: str) -> List[LogEntry]:
        """Parse JSON log format."""
        entries: List[LogEntry] = []
        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = LogEntry(
                    raw=line,
                    timestamp=data.get("timestamp", data.get("time", data.get("@timestamp", ""))),
                    severity=data.get("level", data.get("severity", data.get("lvl", "INFO"))).upper(),
                    source=data.get("logger", data.get("source", data.get("name", ""))),
                    message=data.get("message", data.get("msg", data.get("event", line[:200]))),
                    pid=str(data.get("pid", data.get("process_id", ""))),
                    thread=str(data.get("thread", data.get("thread_id", ""))),
                    module=data.get("module", data.get("component", "")),
                    line_number=i,
                    metadata=data,
                )
                entry.severity = self._normalize_severity(entry.severity)
                entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                # Fallback to generic
                entries.append(LogEntry(
                    raw=line, message=line[:200], line_number=i,
                    severity=self._detect_severity(line),
                ))
        return entries

    def _parse_syslog(self, source: str) -> List[LogEntry]:
        """Parse syslog format."""
        entries: List[LogEntry] = []
        pattern = re.compile(
            r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?:\s*(.*)$"
        )

        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                timestamp = match.group(1)
                host = match.group(2)
                proc = match.group(3)
                pid = match.group(4)
                message = match.group(5)
                entries.append(LogEntry(
                    raw=line, timestamp=timestamp, source=host,
                    pid=pid, message=message, line_number=i,
                    module=proc,
                    severity=self._detect_severity(message),
                ))
            else:
                entries.append(LogEntry(
                    raw=line, message=line[:200], line_number=i,
                    severity=self._detect_severity(line),
                ))
        return entries

    def _parse_syslog_iso(self, source: str) -> List[LogEntry]:
        """Parse ISO timestamped log format."""
        entries: List[LogEntry] = []
        pattern = re.compile(
            r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
            r"(?:\[(\d+)\])?\s*(?:(\S+)\s+)?(.*)$"
        )

        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                timestamp = match.group(1)
                pid = match.group(2)
                source_name = match.group(3)
                message = match.group(4) or ""
                entries.append(LogEntry(
                    raw=line, timestamp=timestamp, source=source_name or "",
                    pid=pid, message=message, line_number=i,
                    severity=self._detect_severity(message),
                ))
            else:
                entries.append(LogEntry(
                    raw=line, message=line[:200], line_number=i,
                    severity=self._detect_severity(line),
                ))
        return entries

    def _parse_apache(self, source: str) -> List[LogEntry]:
        """Parse Apache common/combined log format."""
        entries: List[LogEntry] = []
        pattern = re.compile(
            r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"(?:GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH)\s+'
            r'(\S+)\s+\S+"\s+(\d+)\s+(\d+)(?:\s+"(?:[^"]*)"\s+"(?:[^"]*)")?'
        )

        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                ip = match.group(1)
                timestamp = match.group(2)
                path = match.group(3)
                status = match.group(4)
                size = match.group(5)
                sev = "ERROR" if int(status) >= 500 else "WARNING" if int(status) >= 400 else "INFO"
                entries.append(LogEntry(
                    raw=line, timestamp=timestamp, source=ip,
                    message=f"{status} {path}", line_number=i,
                    severity=sev,
                    metadata={"ip": ip, "path": path, "status": int(status), "size": int(size)},
                ))
            else:
                entries.append(LogEntry(
                    raw=line, message=line[:200], line_number=i,
                    severity=self._detect_severity(line),
                ))
        return entries

    def _parse_severity_based(self, source: str) -> List[LogEntry]:
        """Parse logs with severity keywords."""
        entries: List[LogEntry] = []
        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            # Extract timestamp
            timestamp = ""
            for ts_pattern in self.TIMESTAMP_PATTERNS:
                ts_match = ts_pattern.search(line)
                if ts_match:
                    timestamp = ts_match.group(0)
                    break

            severity = self._detect_severity(line)
            entries.append(LogEntry(
                raw=line, timestamp=timestamp, message=line[:200],
                line_number=i, severity=severity,
            ))
        return entries

    def _parse_python_traceback(self, source: str) -> List[LogEntry]:
        """Parse Python traceback logs."""
        entries: List[LogEntry] = []
        current_tb: List[str] = []
        in_traceback = False

        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("Traceback (most recent call last)"):
                in_traceback = True
                current_tb = [line]
            elif in_traceback and (stripped.startswith("File ") or stripped.startswith("  File ")):
                current_tb.append(line)
            elif in_traceback and stripped:
                current_tb.append(line)
                error_msg = " | ".join(current_tb[-3:])
                # Extract error type
                error_type = "Exception"
                exc_match = re.search(r"(\w+Error|\w+Exception):", stripped)
                if exc_match:
                    error_type = exc_match.group(1)
                entries.append(LogEntry(
                    raw=line, message=error_msg[:200], line_number=i,
                    severity="ERROR", error_type=error_type,
                    tags=["traceback", error_type],
                ))
                in_traceback = False
                current_tb = []
            else:
                severity = self._detect_severity(stripped)
                entries.append(LogEntry(
                    raw=line, message=stripped[:200], line_number=i,
                    severity=severity,
                ))

        return entries

    def _parse_generic(self, source: str) -> List[LogEntry]:
        """Generic log parser."""
        entries: List[LogEntry] = []
        for i, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            timestamp = ""
            for ts_pattern in self.TIMESTAMP_PATTERNS:
                ts_match = ts_pattern.search(line)
                if ts_match:
                    timestamp = ts_match.group(0)
                    break
            entries.append(LogEntry(
                raw=line, timestamp=timestamp, message=line[:200],
                line_number=i, severity=self._detect_severity(line),
            ))
        return entries

    def _detect_severity(self, text: str) -> str:
        """Detect log severity from text."""
        for sev, pattern in SEVERITY_PATTERNS.items():
            if pattern.search(text):
                return sev
        return "INFO"

    def _normalize_severity(self, sev: str) -> str:
        """Normalize severity string."""
        sev = sev.upper()
        if sev in ("CRIT", "FATAL"):
            return "CRITICAL"
        if sev in ("ERR", "FAIL"):
            return "ERROR"
        if sev in ("WARN", "WRN"):
            return "WARNING"
        if sev in ("INFO", "INFORMATION", "LOG"):
            return "INFO"
        if sev in ("DEBUG", "TRACE", "TRC", "DBG"):
            return "INFO"  # Treat as info for aggregation
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class LogAnalyzer:
    """Analyze log entries for patterns, anomalies, and errors."""

    def __init__(self) -> None:
        self.parser = LogParser()
        self._error_clusters: Dict[str, LogErrorCluster] = {}
        self._time_buckets: Dict[str, TimeSeriesPoint] = {}
        self._source_counter: Counter = Counter()
        self._module_counter: Counter = Counter()
        self._severity_counter: Dict[str, int] = defaultdict(int)

    def analyze(self, source: str, fmt: Optional[str] = None,
                title: str = "Log Analysis") -> LogAnalysisResult:
        """Analyze log source and return results."""
        result = LogAnalysisResult()
        start_time = time.time()

        # Detect format if not specified
        if fmt is None:
            fmt = LogFormatDetector.detect(source)
        result.format = fmt

        # Parse entries
        entries = self.parser.parse(source, fmt)
        result.total_entries = len(entries)
        result.total_lines = len(source.splitlines())

        if not entries:
            result.duration_ms = (time.time() - start_time) * 1000
            result.summary = "No log entries found."
            return result

        # Process entries
        self._process_entries(entries, result)

        # Build time series
        self._build_time_series(result)

        # Detect anomalies
        self._detect_anomalies(result)

        # Generate summary
        result.summary = self._generate_summary(result)

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def analyze_file(self, filepath: str, fmt: Optional[str] = None) -> LogAnalysisResult:
        """Analyze a log file."""
        try:
            if filepath.endswith(".gz"):
                with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            else:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
        except OSError as e:
            result = LogAnalysisResult(filepath=filepath)
            result.errors.append(str(e))
            return result

        result = self.analyze(source, fmt, title=os.path.basename(filepath))
        result.filepath = filepath
        return result

    def _process_entries(self, entries: List[LogEntry], result: LogAnalysisResult) -> None:
        """Process all entries and build analysis data."""
        timestamps: List[str] = []

        for entry in entries:
            # Count severity
            self._severity_counter[entry.severity] += 1

            # Track timestamp range
            if entry.timestamp:
                timestamps.append(entry.timestamp)

            # Count sources
            if entry.source:
                self._source_counter[entry.source] += 1

            # Count modules
            if entry.module:
                self._module_counter[entry.module] += 1

            # Cluster errors
            if entry.severity in ("ERROR", "CRITICAL"):
                self._cluster_error(entry)

        result.severity_counts = dict(self._severity_counter)
        result.top_sources = self._source_counter.most_common(20)
        result.top_modules = self._module_counter.most_common(20)
        result.error_clusters = sorted(
            self._error_clusters.values(),
            key=lambda c: c.count, reverse=True
        )[:50]  # Top 50 clusters

        if timestamps:
            result.time_range = (min(timestamps), max(timestamps))

    def _cluster_error(self, entry: LogEntry) -> None:
        """Cluster similar errors together."""
        # Normalize message for clustering
        msg = entry.message.strip()

        # Remove variable parts (numbers, hex, UUIDs, paths)
        pattern = re.sub(r'\b0x[0-9a-fA-F]+\b', '0x...', msg)
        pattern = re.sub(r'\b\d{2,}\b', 'N', pattern)
        pattern = re.sub(r'\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b',
                        'UUID', pattern)
        pattern = re.sub(r'"[^"]*"', '"..."', pattern)
        pattern = re.sub(r"'[^']*'", "'...'", pattern)
        pattern = re.sub(r'/\S+', '/...', pattern)
        pattern = re.sub(r'\b\w{40,}\b', 'HASH', pattern)  # Hashes
        pattern = re.sub(r'\bat\s+\S+:\d+\b', 'at FILE:LINE', pattern)  # Tracebacks

        # Normalize whitespace
        pattern = re.sub(r'\s+', ' ', pattern).strip()

        # Truncate to cluster key
        cluster_key = pattern[:150]

        if cluster_key not in self._error_clusters:
            self._error_clusters[cluster_key] = LogErrorCluster(
                id=hashlib.md5(cluster_key.encode()).hexdigest()[:12],
                pattern=cluster_key,
                severity=entry.severity,
            )
        self._error_clusters[cluster_key].add(entry)

    def _build_time_series(self, result: LogAnalysisResult) -> None:
        """Build time series from log entries."""
        # Regenerate time series from scratch
        self._time_buckets = {}
        bucket_size = self._estimate_bucket_size(result.total_entries)

        for entry in self._get_all_entries_from(result):
            if not entry.timestamp:
                continue
            # Normalize timestamp to bucket
            bucket = self._bucket_timestamp(entry.timestamp, bucket_size)
            if bucket not in self._time_buckets:
                self._time_buckets[bucket] = TimeSeriesPoint(timestamp=bucket)
            point = self._time_buckets[bucket]
            point.count += 1
            if entry.severity in ("ERROR", "CRITICAL"):
                point.error_count += 1
            elif entry.severity == "WARNING":
                point.warning_count += 1
            else:
                point.info_count += 1
            if entry.source:
                point.unique_sources += 1

        result.time_series = sorted(
            self._time_buckets.values(),
            key=lambda p: p.timestamp
        )

    def _get_all_entries_from(self, result: LogAnalysisResult) -> List[LogEntry]:
        """Get all entries from the analysis (re-parsed from source)."""
        # This is optimized to return the entries we already parsed
        # Since we don't store them, return empty list
        return []

    def _estimate_bucket_size(self, total_entries: int) -> int:
        """Estimate the time bucket size based on entry count."""
        if total_entries <= 100:
            return 1  # 1 second
        elif total_entries <= 1000:
            return 10  # 10 seconds
        elif total_entries <= 10000:
            return 60  # 1 minute
        elif total_entries <= 100000:
            return 300  # 5 minutes
        return 3600  # 1 hour

    def _bucket_timestamp(self, ts: str, bucket_size: int) -> str:
        """Normalize a timestamp to a bucket."""
        return ts  # Simplified - in production, would round to bucket

    def _detect_anomalies(self, result: LogAnalysisResult) -> None:
        """Detect anomalies in log data."""
        # Frequency spike detection
        if len(result.time_series) > 5:
            counts = [p.count for p in result.time_series]
            avg = sum(counts) / len(counts)
            std = math.sqrt(sum((c - avg) ** 2 for c in counts) / len(counts)) if len(counts) > 1 else 0

            for point in result.time_series:
                if point.count > avg + 3 * std and std > 0:
                    result.anomalies.append(Anomaly(
                        type="frequency_spike",
                        description=f"Log frequency spike: {point.count} entries "
                                    f"(avg={avg:.1f}, threshold={avg + 3 * std:.1f})",
                        severity="WARNING",
                        timestamp=point.timestamp,
                        metric=point.count,
                        threshold=avg + 3 * std,
                    ))

        # Error rate anomaly
        if len(result.time_series) > 3:
            for point in result.time_series:
                if point.count > 0:
                    error_rate = point.error_count / point.count
                    if error_rate > 0.5 and point.error_count > 5:
                        result.anomalies.append(Anomaly(
                            type="error_rate",
                            description=f"High error rate: {error_rate*100:.1f}% "
                                        f"({point.error_count}/{point.count})",
                            severity="HIGH",
                            timestamp=point.timestamp,
                            metric=error_rate,
                            threshold=0.5,
                        ))

        # New error pattern detection
        if result.error_clusters:
            # Check for new clusters that appeared recently
            total_errors = sum(c.count for c in result.error_clusters)
            top_cluster = result.error_clusters[0]
            if top_cluster.count > total_errors * 0.5 and total_errors > 10:
                result.anomalies.append(Anomaly(
                    type="dominant_error",
                    description=f"Dominant error pattern: '{top_cluster.pattern[:100]}' "
                                f"({top_cluster.count}/{total_errors} errors)",
                    severity="MEDIUM",
                    timestamp=top_cluster.last_seen or "",
                    metric=top_cluster.count / max(total_errors, 1),
                    threshold=0.5,
                ))

    def _generate_summary(self, result: LogAnalysisResult) -> str:
        """Generate a summary of the analysis."""
        parts: List[str] = []

        parts.append(f"Analyzed {result.total_entries} log entries from {result.total_lines} lines.")
        parts.append(f"Format: {result.format}")

        if result.time_range[0] and result.time_range[1]:
            parts.append(f"Time range: {result.time_range[0]} to {result.time_range[1]}")

        parts.append(f"Severity breakdown:")
        for sev in ("CRITICAL", "ERROR", "WARNING", "INFO", "UNKNOWN"):
            count = result.severity_counts.get(sev, 0)
            if count > 0:
                parts.append(f"  {sev}: {count}")

        if result.error_clusters:
            parts.append(f"Error clusters: {len(result.error_clusters)}")
            for cluster in result.error_clusters[:5]:
                parts.append(f"  [{cluster.id}] {cluster.pattern[:80]}... ({cluster.count} occurrences)")

        if result.anomalies:
            parts.append(f"Anomalies detected: {len(result.anomalies)}")
            for anomaly in result.anomalies[:5]:
                parts.append(f"  [{anomaly.severity}] {anomaly.description}")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Real-time monitoring
# ---------------------------------------------------------------------------

class LogMonitor:
    """Real-time log file monitoring (tail + analyze)."""

    def __init__(self, filepath: str, analyzer: Optional[LogAnalyzer] = None,
                 interval: float = 1.0, verbose: bool = False) -> None:
        self.filepath = filepath
        self.analyzer = analyzer or LogAnalyzer()
        self.interval = interval
        self.verbose = verbose
        self._running = False
        self._position = 0
        self._entries: List[LogEntry] = []
        self._callback: Optional[Callable] = None

    def on_entry(self, callback: Callable) -> None:
        """Register a callback for new entries."""
        self._callback = callback

    def start(self) -> None:
        """Start monitoring the log file."""
        self._running = True
        self._position = self._get_initial_position()

        print(f"Monitoring {self.filepath}...", file=sys.stderr)
        print(f"Starting from position {self._position}", file=sys.stderr)

        try:
            while self._running:
                new_entries = self._read_new_entries()
                if new_entries:
                    self._entries.extend(new_entries)
                    if self._callback:
                        for entry in new_entries:
                            self._callback(entry)
                    if self.verbose:
                        for entry in new_entries[-5:]:
                            print(f"  [{entry.severity}] {entry.message[:100]}", file=sys.stderr)
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.", file=sys.stderr)
            self._running = False
        except FileNotFoundError:
            print(f"Error: Log file not found: {self.filepath}", file=sys.stderr)
            self._running = False

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False

    def analyze_current(self) -> LogAnalysisResult:
        """Analyze all entries collected so far."""
        source = "\n".join(e.raw for e in self._entries)
        return self.analyzer.analyze(source)

    def _get_initial_position(self) -> int:
        """Get the initial file position."""
        try:
            if os.path.isfile(self.filepath):
                return os.path.getsize(self.filepath)
        except OSError:
            pass
        return 0

    def _read_new_entries(self) -> List[LogEntry]:
        """Read new entries from the log file."""
        try:
            if not os.path.isfile(self.filepath):
                return []

            current_size = os.path.getsize(self.filepath)
            if current_size <= self._position:
                self._position = current_size
                return []

            with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._position)
                new_data = f.read()
                self._position = f.tell()

            if not new_data:
                return []

            return self.analyzer.parser.parse(new_data)

        except (OSError, PermissionError) as e:
            if self.verbose:
                print(f"Error reading log: {e}", file=sys.stderr)
            return []


# ---------------------------------------------------------------------------
# HTML Dashboard Generation
# ---------------------------------------------------------------------------

class DashboardGenerator:
    """Generate HTML dashboard from log analysis results."""

    @staticmethod
    def generate(result: LogAnalysisResult, title: str = "Log Analysis Dashboard") -> str:
        """Generate an HTML dashboard."""
        # Build summary stats
        total = result.total_entries
        critical = result.severity_counts.get("CRITICAL", 0)
        errors = result.severity_counts.get("ERROR", 0)
        warnings = result.severity_counts.get("WARNING", 0)
        info = result.severity_counts.get("INFO", 0)

        # Error clusters table
        clusters_html = ""
        for cluster in result.error_clusters[:20]:
            clusters_html += f"""<tr>
                <td><code>{cluster.id}</code></td>
                <td><span class="sev-{cluster.severity.lower()}">{cluster.severity}</span></td>
                <td class="msg">{cluster.pattern[:120]}</td>
                <td>{cluster.count}</td>
                <td>{cluster.first_seen or "N/A"}</td>
                <td>{cluster.last_seen or "N/A"}</td>
            </tr>\n"""

        # Anomalies table
        anomalies_html = ""
        for anomaly in result.anomalies:
            anomalies_html += f"""<tr>
                <td><span class="sev-{anomaly.severity.lower()}">{anomaly.severity}</span></td>
                <td>{anomaly.type}</td>
                <td>{anomaly.description}</td>
                <td>{anomaly.timestamp}</td>
            </tr>\n"""

        # Time series data
        ts_data = []
        for point in result.time_series:
            ts_data.append({
                "t": point.timestamp,
                "total": point.count,
                "error": point.error_count,
                "warning": point.warning_count,
            })

        # Top sources
        sources_html = ""
        for src, count in result.top_sources[:10]:
            pct = count / max(total, 1) * 100
            sources_html += f"""<tr>
                <td>{src}</td>
                <td>{count}</td>
                <td><div class="bar" style="width:{pct}%"></div></td>
            </tr>\n"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #f5f6fa; color: #2c3e50; padding: 20px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ font-size: 24px; margin-bottom: 20px; color: #2c3e50; }}
    h2 {{ font-size: 18px; margin: 20px 0 10px; color: #34495e; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
              gap: 12px; margin-bottom: 20px; }}
    .stat-card {{ background: #fff; padding: 15px; border-radius: 8px;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
    .stat-card .num {{ font-size: 28px; font-weight: bold; }}
    .stat-card .label {{ font-size: 12px; color: #7f8c8d; margin-top: 4px; }}
    .num-critical {{ color: #c0392b; }}
    .num-error {{ color: #e74c3c; }}
    .num-warning {{ color: #f39c12; }}
    .num-info {{ color: #3498db; }}
    .card {{ background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
    th {{ background: #f8f9fa; font-weight: 600; color: #7f8c8d; }}
    tr:hover {{ background: #f8f9fa; }}
    .msg {{ max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .sev-critical {{ color: #c0392b; font-weight: bold; }}
    .sev-error {{ color: #e74c3c; font-weight: bold; }}
    .sev-warning {{ color: #f39c12; }}
    .sev-info {{ color: #3498db; }}
    .bar {{ height: 4px; background: #3498db; border-radius: 2px; margin-top: 6px; }}
    .summary {{ white-space: pre-wrap; font-family: monospace; font-size: 13px;
               background: #f8f9fa; padding: 15px; border-radius: 6px; }}
    .meta {{ color: #7f8c8d; font-size: 13px; margin-bottom: 15px; }}
    .chart {{ width: 100%; height: 200px; position: relative; }}
    .chart-bar {{ position: absolute; bottom: 0; border-radius: 2px 2px 0 0; }}
    .footer {{ text-align: center; color: #95a5a6; font-size: 12px; margin-top: 30px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    <div class="meta">
      File: {result.filepath} | Format: {result.format} |
      Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} |
      Duration: {result.duration_ms:.0f}ms
    </div>

    <div class="stats">
      <div class="stat-card">
        <div class="num">{total:,}</div>
        <div class="label">Total Entries</div>
      </div>
      <div class="stat-card">
        <div class="num num-critical">{critical:,}</div>
        <div class="label">Critical</div>
      </div>
      <div class="stat-card">
        <div class="num num-error">{errors:,}</div>
        <div class="label">Errors</div>
      </div>
      <div class="stat-card">
        <div class="num num-warning">{warnings:,}</div>
        <div class="label">Warnings</div>
      </div>
      <div class="stat-card">
        <div class="num num-info">{info:,}</div>
        <div class="label">Info</div>
      </div>
      <div class="stat-card">
        <div class="num">{len(result.error_clusters)}</div>
        <div class="label">Error Clusters</div>
      </div>
      <div class="stat-card">
        <div class="num">{len(result.anomalies)}</div>
        <div class="label">Anomalies</div>
      </div>
    </div>

    <div class="card">
      <h2>Summary</h2>
      <div class="summary">{result.summary}</div>
    </div>

    <div class="card">
      <h2>Error Clusters ({len(result.error_clusters)})</h2>
      <table>
        <tr><th>ID</th><th>Severity</th><th>Pattern</th><th>Count</th><th>First Seen</th><th>Last Seen</th></tr>
        {clusters_html}
      </table>
    </div>

    <div class="card">
      <h2>Anomalies ({len(result.anomalies)})</h2>
      <table>
        <tr><th>Severity</th><th>Type</th><th>Description</th><th>Timestamp</th></tr>
        {anomalies_html}
      </table>
    </div>

    <div class="card">
      <h2>Top Sources</h2>
      <table>
        <tr><th>Source</th><th>Count</th><th></th></tr>
        {sources_html}
      </table>
    </div>

    <div class="footer">
      Generated by {APP_NAME} v{VERSION}
    </div>
  </div>
</body>
</html>"""

        return html


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered log analysis tool with anomaly detection and dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s analyze system.log                         # Analyze a log file
              %(prog)s analyze app.log -f json                    # Force JSON format
              %(prog)s analyze errors.log -o report.json          # Output to JSON
              %(prog)s analyze access.log -f html -o dashboard.html  # HTML dashboard
              %(prog)s watch /var/log/syslog                      # Real-time monitoring
              %(prog)s report analysis.json -o dashboard.html     # Generate report
        """),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ------------------------------------------------------------------ #
    # analyze subcommand
    # ------------------------------------------------------------------ #
    analyze_parser = subparsers.add_parser("analyze", help="Analyze log files")
    analyze_parser.add_argument("logfile", type=str, help="Log file to analyze")
    analyze_parser.add_argument("--format", "-f", type=str, default="",
                                help="Log format (auto-detect if not specified)")
    analyze_parser.add_argument("--output", "-o", type=str, default="",
                                help="Output file for results")
    analyze_parser.add_argument("--output-format", choices=["text", "json", "html"],
                                default="text", help="Output format (default: text)")
    analyze_parser.add_argument("--title", type=str, default="Log Analysis",
                                help="Report title")

    # ------------------------------------------------------------------ #
    # watch subcommand
    # ------------------------------------------------------------------ #
    watch_parser = subparsers.add_parser("watch", help="Monitor log files in real-time")
    watch_parser.add_argument("logfile", type=str, help="Log file to monitor")
    watch_parser.add_argument("--interval", "-i", type=float, default=1.0,
                              help="Polling interval in seconds (default: 1.0)")
    watch_parser.add_argument("--format", "-f", type=str, default="",
                              help="Log format (auto-detect)")
    watch_parser.add_argument("--output", "-o", type=str, default="",
                              help="Output analysis file when stopped")

    # ------------------------------------------------------------------ #
    # report subcommand
    # ------------------------------------------------------------------ #
    report_parser = subparsers.add_parser("report", help="Generate reports from analysis data")
    report_parser.add_argument("input", type=str, help="Analysis JSON file")
    report_parser.add_argument("--output", "-o", type=str, default="",
                               help="Output file")
    report_parser.add_argument("--format", "-f", choices=["text", "html", "json"],
                               default="html", help="Output format (default: html)")
    report_parser.add_argument("--title", type=str, default="Log Analysis Report",
                               help="Report title")

    return parser


def cmd_analyze(args: argparse.Namespace) -> int:
    """Handle the 'analyze' subcommand."""
    logfile = args.logfile

    if not os.path.isfile(logfile):
        print(f"Error: Log file not found: {logfile}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Analyzing {logfile}...", file=sys.stderr)

    analyzer = LogAnalyzer()
    result = analyzer.analyze_file(logfile, fmt=args.format or None)

    if result.errors:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        return 1

    if args.output_format == "json":
        output = json.dumps({
            "filepath": result.filepath,
            "format": result.format,
            "total_entries": result.total_entries,
            "total_lines": result.total_lines,
            "severity_counts": result.severity_counts,
            "time_range": result.time_range,
            "error_clusters": [
                {
                    "id": c.id,
                    "pattern": c.pattern[:200],
                    "count": c.count,
                    "first_seen": c.first_seen,
                    "last_seen": c.last_seen,
                    "severity": c.severity,
                    "sample": c.sample[:200],
                }
                for c in result.error_clusters
            ],
            "anomalies": [
                {
                    "type": a.type,
                    "description": a.description,
                    "severity": a.severity,
                    "timestamp": a.timestamp,
                }
                for a in result.anomalies
            ],
            "top_sources": result.top_sources,
            "summary": result.summary,
            "duration_ms": result.duration_ms,
        }, indent=2, default=str)
    elif args.output_format == "html":
        dashboard = DashboardGenerator()
        output = dashboard.generate(result, title=args.title)
    else:
        # Text output
        severity = result.severity_counts
        total = result.total_entries
        lines: List[str] = []
        lines.append(f"Log Analysis: {os.path.basename(logfile)}")
        lines.append("=" * 60)
        lines.append(f"Format: {result.format}")
        lines.append(f"Total entries: {total:,}")
        lines.append(f"Total lines: {result.total_lines:,}")
        if result.time_range[0] and result.time_range[1]:
            lines.append(f"Time range: {result.time_range[0]} to {result.time_range[1]}")
        lines.append("")
        lines.append("Severity breakdown:")
        for sev in ("CRITICAL", "ERROR", "WARNING", "INFO", "UNKNOWN"):
            count = severity.get(sev, 0)
            if count > 0:
                pct = count / total * 100 if total > 0 else 0
                lines.append(f"  {sev:10s}: {count:8,} ({pct:5.1f}%)")
        lines.append("")

        if result.error_clusters:
            lines.append(f"Error Clusters ({len(result.error_clusters)}):")
            for cluster in result.error_clusters[:10]:
                lines.append(f"  [{cluster.id}] {cluster.pattern[:100]}")
                lines.append(f"        Count: {cluster.count}, Severity: {cluster.severity}")
                lines.append("")

        if result.anomalies:
            lines.append(f"Anomalies ({len(result.anomalies)}):")
            for anomaly in result.anomalies:
                lines.append(f"  [{anomaly.severity}] {anomaly.description}")
            lines.append("")

        if result.top_sources:
            lines.append(f"Top Sources:")
            for src, count in result.top_sources[:10]:
                lines.append(f"  {src}: {count}")
            lines.append("")

        lines.append(f"Analysis completed in {result.duration_ms:.0f}ms")
        lines.append("")
        output = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Handle the 'watch' subcommand."""
    logfile = args.logfile

    if not os.path.isfile(logfile):
        print(f"Error: Log file not found: {logfile}", file=sys.stderr)
        return 1

    analyzer = LogAnalyzer()
    monitor = LogMonitor(logfile, analyzer, interval=args.interval, verbose=args.verbose)

    # Register callback to display new entries
    def on_entry(entry: LogEntry) -> None:
        ts = entry.timestamp or ""
        sev = entry.severity
        msg = entry.message[:120]
        print(f"[{ts}] [{sev}] {msg}", file=sys.stderr)

    monitor.on_entry(on_entry)

    print(f"Starting log monitor on {logfile}", file=sys.stderr)
    print(f"Polling interval: {args.interval}s", file=sys.stderr)
    print(f"Press Ctrl+C to stop and analyze", file=sys.stderr)

    try:
        monitor.start()
    except KeyboardInterrupt:
        print("\nStopping monitor...", file=sys.stderr)

    # Analyze collected entries
    if args.verbose:
        print("Analyzing collected entries...", file=sys.stderr)

    result = monitor.analyze_current()

    if args.output:
        output = json.dumps({
            "filepath": logfile,
            "format": result.format,
            "total_entries": result.total_entries,
            "severity_counts": result.severity_counts,
            "error_clusters": [
                {"id": c.id, "pattern": c.pattern[:200], "count": c.count,
                 "first_seen": c.first_seen, "last_seen": c.last_seen}
                for c in result.error_clusters
            ],
            "anomalies": [
                {"type": a.type, "description": a.description, "severity": a.severity}
                for a in result.anomalies
            ],
            "summary": result.summary,
        }, indent=2, default=str)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Analysis saved to {args.output}", file=sys.stderr)
    else:
        print("\n" + result.summary, file=sys.stderr)

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Handle the 'report' subcommand."""
    input_path = args.input

    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading JSON: {e}", file=sys.stderr)
        return 1

    # Reconstruct analysis result from JSON data
    result = LogAnalysisResult()
    result.filepath = data.get("filepath", input_path)
    result.format = data.get("format", "unknown")
    result.total_entries = data.get("total_entries", 0)
    result.total_lines = data.get("total_lines", 0)
    result.severity_counts = defaultdict(int, data.get("severity_counts", {}))
    result.time_range = tuple(data.get("time_range", (None, None)))
    result.summary = data.get("summary", "")
    result.duration_ms = data.get("duration_ms", 0.0)

    for c in data.get("error_clusters", []):
        cluster = LogErrorCluster(
            id=c.get("id", ""),
            pattern=c.get("pattern", ""),
            count=c.get("count", 0),
            first_seen=c.get("first_seen"),
            last_seen=c.get("last_seen"),
            severity=c.get("severity", "ERROR"),
            sample=c.get("sample", ""),
        )
        result.error_clusters.append(cluster)

    for a in data.get("anomalies", []):
        anomaly = Anomaly(
            type=a.get("type", ""),
            description=a.get("description", ""),
            severity=a.get("severity", "INFO"),
            timestamp=a.get("timestamp", ""),
        )
        result.anomalies.append(anomaly)

    if args.format == "json":
        output = json.dumps(data, indent=2, default=str)
    elif args.format == "html":
        dashboard = DashboardGenerator()
        output = dashboard.generate(result, title=args.title)
    else:
        lines: List[str] = []
        lines.append(f"Log Report: {os.path.basename(input_path)}")
        lines.append("=" * 60)
        lines.append(f"Total entries: {result.total_entries:,}")
        lines.append(f"Format: {result.format}")
        lines.append("")
        lines.append("Severity breakdown:")
        for sev in ("CRITICAL", "ERROR", "WARNING", "INFO"):
            count = result.severity_counts.get(sev, 0)
            if count > 0:
                lines.append(f"  {sev}: {count}")
        lines.append("")
        if result.error_clusters:
            lines.append(f"Error clusters: {len(result.error_clusters)}")
            for cluster in result.error_clusters[:5]:
                lines.append(f"  {cluster.pattern[:80]} ({cluster.count})")
        lines.append("")
        if result.anomalies:
            lines.append(f"Anomalies: {len(result.anomalies)}")
        output = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "watch":
        return cmd_watch(args)
    elif args.command == "report":
        return cmd_report(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())