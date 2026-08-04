#!/usr/bin/env python3
"""AinosOS Test Runner — Discover, run, and report on all test suites.

This script is the central entry point for running all AinosOS test suites.
It provides:

- Auto-discovery of all test suites (kernel C, runtime, SDK, integration,
  stress, performance).
- Sequential execution in dependency order.
- JUnit XML output for CI integration.
- Coverage report generation (HTML, XML, terminal).
- Summary report with pass/fail/skip statistics.
- Suite-level filtering and parallel execution.
- Exit code based on overall results.

Usage:

    # Run all tests
    python tests/run_all_tests.py

    # Run a specific suite
    python tests/run_all_tests.py --suite runtime

    # Run with coverage
    python tests/run_all_tests.py --coverage

    # Run with JUnit XML output
    python tests/run_all_tests.py --junit-xml results.xml

    # Run parallel (4 workers)
    python tests/run_all_tests.py --parallel 4

    # Quick smoke test (skip stress and benchmarks)
    python tests/run_all_tests.py --quick

    # Verbose output
    python tests/run_all_tests.py --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
VERSION = "1.0.0"

SUITE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "kernel": {
        "name": "Kernel Unit Tests",
        "path": "tests/kernel/",
        "type": "c",
        "description": "AI syscall unit tests (embedding, search, model lifecycle, context, status)",
        "dependencies": [],
        "timeout": 120,
    },
    "runtime": {
        "name": "Runtime Tests",
        "path": "tests/runtime/",
        "type": "python",
        "description": "Runtime component tests (GGML, ONNX, model manager, context, power policy, FFI)",
        "dependencies": [],
        "timeout": 300,
    },
    "sdk": {
        "name": "SDK Consistency Tests",
        "path": "tests/sdk/",
        "type": "python",
        "description": "Cross-language SDK API parity tests",
        "dependencies": [],
        "timeout": 300,
    },
    "integration": {
        "name": "Integration Tests",
        "path": "tests/integration/",
        "type": "python",
        "description": "End-to-end pipelines spanning kernel, runtime, and daemon",
        "dependencies": ["runtime", "sdk"],
        "timeout": 600,
    },
    "stress": {
        "name": "Stress Tests",
        "path": "tests/stress/",
        "type": "python",
        "description": "High-load, long-duration resilience validation",
        "dependencies": ["integration"],
        "timeout": 3600,
    },
    "performance": {
        "name": "Performance Benchmarks",
        "path": "tests/performance/",
        "type": "python",
        "description": "Throughput, latency, and memory profiling",
        "dependencies": [],
        "timeout": 1800,
    },
}

SUITE_ORDER = ["kernel", "runtime", "sdk", "integration", "stress", "performance"]

EXIT_CODES = {
    "success": 0,
    "failure": 1,
    "error": 2,
    "internal_error": 3,
    "no_tests": 5,
}

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """Results of a single test suite run."""
    suite_name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    output: str = ""
    suite_type: str = "python"

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.errors == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "total": self.total,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "suite_type": self.suite_type,
        }


@dataclass
class SummaryReport:
    """Overall test run summary."""
    start_time: datetime
    end_time: datetime
    results: dict[str, TestResult] = field(default_factory=dict)
    platform: str = ""
    python_version: str = ""

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def total_passed(self) -> int:
        return sum(r.passed for r in self.results.values())

    @property
    def total_failed(self) -> int:
        return sum(r.failed for r in self.results.values())

    @property
    def total_skipped(self) -> int:
        return sum(r.skipped for r in self.results.values())

    @property
    def total_errors(self) -> int:
        return sum(r.errors for r in self.results.values())

    @property
    def total_tests(self) -> int:
        return sum(r.total for r in self.results.values())

    @property
    def overall_success(self) -> bool:
        return self.total_failed == 0 and self.total_errors == 0

    @property
    def suites_passed(self) -> int:
        return sum(1 for r in self.results.values() if r.success)

    @property
    def suites_total(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "platform": self.platform,
            "python_version": self.python_version,
            "overall_success": self.overall_success,
            "total_passed": self.total_passed,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "total_errors": self.total_errors,
            "total_tests": self.total_tests,
            "suites_passed": self.suites_passed,
            "suites_total": self.suites_total,
            "results": {k: v.to_dict() for k, v in self.results.items()},
        }


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------


class TestRunner:
    """Orchestrates test suite discovery and execution."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.verbose = args.verbose
        self.junit_xml = args.junit_xml
        self.coverage = args.coverage
        self.parallel = args.parallel
        self.quick = args.quick
        self.suite_filter = args.suite
        self.report_path = args.report

    def run(self) -> SummaryReport:
        """Execute all configured test suites and return a summary report."""
        report = SummaryReport(
            start_time=datetime.now(),
            platform=self._get_platform(),
            python_version=sys.version,
        )

        suites = self._get_suites_to_run()
        self._log(f"AinosOS Test Runner v{VERSION}")
        self._log(f"Started at: {report.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"Platform: {report.platform}")
        self._log(f"Python: {sys.version.split()[0]}")
        if self.quick:
            self._log("Mode: QUICK (stress and benchmarks skipped)")
        self._log("")

        for suite_name in suites:
            if suite_name not in SUITE_DEFINITIONS:
                self._log(f"  WARNING: Unknown suite '{suite_name}', skipping")
                continue

            definition = SUITE_DEFINITIONS[suite_name]
            self._log(f"Running {definition['name']}...")

            if self.quick and suite_name in ("stress", "performance"):
                self._log(f"  SKIP (quick mode)")
                result = TestResult(
                    suite_name=suite_name,
                    suite_type=definition["type"],
                    skipped=1,
                )
                report.results[suite_name] = result
                continue

            start = time.monotonic()
            try:
                if definition["type"] == "c":
                    result = self._run_c_suite(suite_name, definition)
                else:
                    result = self._run_python_suite(suite_name, definition)
            except Exception as e:
                self._log(f"  ERROR: {e}")
                result = TestResult(
                    suite_name=suite_name,
                    suite_type=definition["type"],
                    errors=1,
                    output=str(e),
                )

            result.duration_seconds = time.monotonic() - start
            report.results[suite_name] = result

            status = "PASS" if result.success else "FAIL"
            self._log(
                f"  {status}: {result.passed}/{result.total} passed, "
                f"{result.failed} failed, {result.skipped} skipped, "
                f"{result.errors} errors ({result.duration_seconds:.1f}s)"
            )
            self._log("")

        report.end_time = datetime.now()
        self._print_summary(report)
        self._generate_reports(report)

        return report

    def _get_suites_to_run(self) -> list[str]:
        """Determine which suites to run based on filters and dependencies."""
        if self.suite_filter:
            suites = [self.suite_filter]
        else:
            suites = list(SUITE_ORDER)

        # Resolve dependencies: ensure dependent suites are included
        resolved = []
        for suite in suites:
            deps = SUITE_DEFINITIONS.get(suite, {}).get("dependencies", [])
            for dep in deps:
                if dep not in resolved and dep not in suites:
                    resolved.append(dep)
            if suite not in resolved:
                resolved.append(suite)

        return resolved

    def _run_python_suite(self, suite_name: str, definition: dict) -> TestResult:
        """Run a Python test suite using pytest."""
        suite_path = TESTS_DIR / definition["path"].replace("tests/", "")
        if not suite_path.exists():
            return TestResult(suite_name=suite_name, suite_type="python", errors=1, output="Path not found")

        cmd = [
            sys.executable, "-m", "pytest",
            str(suite_path),
            "-v",
            "--tb=short",
            "--no-header",
        ]

        if self.parallel > 1:
            cmd.extend(["-n", str(self.parallel)])

        if self.coverage:
            module_name = f"ainos.{suite_name}" if suite_name != "integration" else "ainos"
            cmd.extend([f"--cov={module_name}", "--cov-report=term"])

        timeout = definition.get("timeout", 300)
        if self.quick:
            # Reduce timeout for quick mode
            timeout = min(timeout, 60)
            if suite_name in ("stress", "performance"):
                cmd.extend(["-m", "not slow"])

        if self.verbose:
            self._log(f"  Command: {' '.join(cmd)}")
            self._log(f"  Timeout: {timeout}s")

        try:
            start = time.monotonic()
            proc = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.monotonic() - start
        except subprocess.TimeoutExpired as e:
            return TestResult(
                suite_name=suite_name,
                suite_type="python",
                errors=1,
                duration_seconds=timeout,
                output=f"Timed out after {timeout}s\n{e.stdout or ''}",
            )

        output = proc.stdout
        if proc.returncode != 0:
            output += proc.stderr

        # Parse pytest output for pass/fail counts
        passed = failed = skipped = errors = 0
        for line in proc.stdout.split("\n"):
            line = line.strip()
            if " passed" in line and " failed" in line:
                # Parse the summary line like "100 passed, 2 failed, 1 skipped in 5.2s"
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "passed":
                        passed = int(parts[i - 1])
                    elif part == "failed":
                        failed = int(parts[i - 1])
                    elif part == "skipped":
                        skipped = int(parts[i - 1])
                    elif part == "error" or part == "errors":
                        errors = int(parts[i - 1])
                break

        # If summary parsing failed, count from the test lines
        if passed == 0 and failed == 0:
            for line in proc.stdout.split("\n"):
                if "PASSED" in line:
                    passed += 1
                elif "FAILED" in line:
                    failed += 1
                elif "SKIPPED" in line:
                    skipped += 1
                elif "ERROR" in line:
                    errors += 1

        return TestResult(
            suite_name=suite_name,
            suite_type="python",
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_seconds=duration,
            output=output,
        )

    def _run_c_suite(self, suite_name: str, definition: dict) -> TestResult:
        """Compile and run a C test suite."""
        suite_path = TESTS_DIR / definition["path"].replace("tests/", "")
        if not suite_path.exists():
            return TestResult(suite_name=suite_name, suite_type="c", errors=1, output="Path not found")

        # Find all .c files
        c_files = list(suite_path.glob("test_*.c"))
        if not c_files:
            return TestResult(suite_name=suite_name, suite_type="c", errors=1, output="No C test files found")

        passed = 0
        failed = 0
        output_lines = []

        for c_file in c_files:
            binary = suite_path / c_file.stem.replace("test_", "") + ".test"
            compile_cmd = ["gcc", "-o", str(binary), str(c_file), "-lm", "-Wall", "-Wextra"]

            if self.verbose:
                self._log(f"  Compiling: {c_file.name}")

            # Compile
            try:
                compile_proc = subprocess.run(
                    compile_cmd, cwd=suite_path, capture_output=True, text=True, timeout=30
                )
                if compile_proc.returncode != 0:
                    output_lines.append(f"Compile error for {c_file.name}:\n{compile_proc.stderr}")
                    failed += 1
                    continue
            except subprocess.TimeoutExpired:
                output_lines.append(f"Compile timeout for {c_file.name}")
                failed += 1
                continue

            # Run
            run_cmd = [str(binary)]
            try:
                run_proc = subprocess.run(
                    run_cmd, cwd=suite_path, capture_output=True, text=True, timeout=60
                )
                output_lines.append(run_proc.stdout)
                if run_proc.stderr:
                    output_lines.append(run_proc.stderr)

                # Parse C test output for pass/fail
                for line in run_proc.stdout.split("\n"):
                    if "PASS:" in line:
                        passed += 1
                    elif "FAIL:" in line:
                        failed += 1

                if run_proc.returncode != 0:
                    failed += 1

            except subprocess.TimeoutExpired:
                output_lines.append(f"Run timeout for {c_file.name}")
                failed += 1

            # Clean up binary
            try:
                binary.unlink()
            except OSError:
                pass

        return TestResult(
            suite_name=suite_name,
            suite_type="c",
            passed=passed,
            failed=failed,
            output="\n".join(output_lines),
        )

    def _print_summary(self, report: SummaryReport) -> None:
        """Print the final summary to stdout."""
        width = 80
        self._log("=" * width)
        self._log(f"{'AinosOS Test Runner v' + VERSION:^{width}}")
        self._log("=" * width)
        self._log("")

        # Per-suite results
        self._log(f"{'Suite':<20} {'Passed':>8} {'Failed':>8} {'Skipped':>8} {'Duration':>10} {'Status':>10}")
        self._log("-" * width)
        for suite_name in SUITE_ORDER:
            if suite_name not in report.results:
                continue
            r = report.results[suite_name]
            status = "PASS" if r.success else "FAIL"
            dur = f"{r.duration_seconds:.1f}s"
            self._log(
                f"{SUITE_DEFINITIONS[suite_name]['name']:<20} "
                f"{r.passed:>8} {r.failed:>8} {r.skipped:>8} "
                f"{dur:>10} {status:>10}"
            )

        self._log("-" * width)
        self._log("")

        # Overall summary
        self._log(f"Results: {report.suites_passed}/{report.suites_total} suites passed")
        self._log(f"Tests: {report.total_passed}/{report.total_tests} passed, "
                  f"{report.total_failed} failed, {report.total_skipped} skipped, "
                  f"{report.total_errors} errors")
        self._log(f"Duration: {report.duration_seconds:.1f}s")
        self._log("")

        if report.overall_success:
            self._log("SUCCESS: All tests passed")
        else:
            self._log("FAILURE: Some tests failed")
        self._log("=" * width)

    def _generate_reports(self, report: SummaryReport) -> None:
        """Generate JUnit XML and JSON reports."""
        # JSON report
        if self.report_path:
            report_path = Path(self.report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, "w") as f:
                json.dump(report.to_dict(), f, indent=2, default=str)
            self._log(f"JSON report written to {report_path}")

        # JUnit XML
        if self.junit_xml:
            self._write_junit_xml(report)

    def _write_junit_xml(self, report: SummaryReport) -> None:
        """Write a JUnit XML file for CI integration."""
        testsuites = ET.Element("testsuites")
        testsuites.set("name", "AinosOS Test Suite")
        testsuites.set("tests", str(report.total_tests))
        testsuites.set("failures", str(report.total_failed))
        testsuites.set("errors", str(report.total_errors))
        testsuites.set("time", f"{report.duration_seconds:.3f}")

        for suite_name, result in report.results.items():
            suite_def = SUITE_DEFINITIONS.get(suite_name, {})
            testsuite = ET.SubElement(testsuites, "testsuite")
            testsuite.set("name", suite_def.get("name", suite_name))
            testsuite.set("tests", str(result.total))
            testsuite.set("failures", str(result.failed))
            testsuite.set("errors", str(result.errors))
            testsuite.set("skipped", str(result.skipped))
            testsuite.set("time", f"{result.duration_seconds:.3f}")

            # Add a single testcase per suite for simplicity
            if result.success:
                tc = ET.SubElement(testsuite, "testcase")
                tc.set("name", f"{suite_name}.all")
                tc.set("status", "passed")
            else:
                tc = ET.SubElement(testsuite, "testcase")
                tc.set("name", f"{suite_name}.all")
                tc.set("status", "failed")
                failure = ET.SubElement(tc, "failure")
                failure.set("message", f"{result.failed} tests failed")
                failure.text = result.output[:500] if result.output else ""

        tree = ET.ElementTree(testsuites)
        junit_path = Path(self.junit_xml)
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(junit_path, encoding="utf-8", xml_declaration=True)
        self._log(f"JUnit XML written to {junit_path}")

    def _get_platform(self) -> str:
        """Get a human-readable platform string."""
        import platform
        return platform.platform()

    def _log(self, message: str) -> None:
        """Print a message to stdout."""
        print(message)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AinosOS Test Runner — Discover, run, and report on all test suites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Run all test suites
  %(prog)s --suite runtime          Run only runtime tests
  %(prog)s --quick                  Skip stress and benchmarks
  %(prog)s --coverage               Run with coverage reporting
  %(prog)s --parallel 4             Run with 4 parallel workers
  %(prog)s --junit-xml results.xml  Output JUnit XML
  %(prog)s --verbose                Verbose output
        """,
    )

    parser.add_argument(
        "--suite", "-s",
        choices=list(SUITE_DEFINITIONS.keys()),
        help="Run only a specific test suite",
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Skip stress tests and performance benchmarks",
    )
    parser.add_argument(
        "--coverage", "-c",
        action="store_true",
        help="Generate coverage reports",
    )
    parser.add_argument(
        "--parallel", "-p",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--junit-xml",
        type=str,
        default="",
        help="Path to write JUnit XML output",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Path to write JSON report",
    )

    return parser


def main() -> int:
    """Main entry point. Returns an exit code."""
    parser = create_parser()
    args = parser.parse_args()

    runner = TestRunner(args)
    try:
        report = runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return EXIT_CODES["error"]
    except Exception as e:
        print(f"Internal error: {e}")
        return EXIT_CODES["internal_error"]

    if report.total_tests == 0:
        return EXIT_CODES["no_tests"]

    return EXIT_CODES["success"] if report.overall_success else EXIT_CODES["failure"]


if __name__ == "__main__":
    sys.exit(main())