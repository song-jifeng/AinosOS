"""
Command executor for Ainos Shell.

Handles execution of parsed commands including:
- Subprocess execution with proper piping
- Built-in command execution
- Pipeline orchestration
- I/O redirection (file, heredoc, FD duplication)
- Environment variable scoping
- Exit code tracking
- Timeout handling
- Background process management
- Signal propagation
- Resource limits
"""

from __future__ import annotations

import io
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import typing as t
from dataclasses import dataclass, field

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    ParsedCommand,
    Pipeline,
    RedirectInfo,
    ShellError,
    CommandNotFoundError,
    find_executable,
    Timer,
    ensure_dir,
)

# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of a command or pipeline execution."""
    command: str = ""
    args: list = field(default_factory=list)
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    pid: int = 0
    timed_out: bool = False
    cancelled: bool = False
    background: bool = False
    bg_pid: int = 0
    signals_received: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        out = self.stdout
        if self.stderr:
            if out:
                out += "\n"
            out += self.stderr
        return out

    @property
    def truncated_stdout(self, max_len: int = 1000) -> str:
        """Truncated stdout for display."""
        if len(self.stdout) > max_len:
            return self.stdout[:max_len] + "..."
        return self.stdout

    def __repr__(self) -> str:
        return f"Result({self.command} -> {self.exit_code}, {self.duration:.2f}s)"


# ---------------------------------------------------------------------------
# Background process tracker
# ---------------------------------------------------------------------------

class BackgroundProcess:
    """Represents a background process."""

    def __init__(self, pid: int, command: str, proc: t.Optional[subprocess.Popen] = None) -> None:
        self.pid = pid
        self.command = command
        self.proc = proc
        self.start_time = time.time()
        self.end_time: t.Optional[float] = None
        self.exit_code: t.Optional[int] = None
        self.done = False
        self._thread: t.Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None

    @property
    def elapsed(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    def wait(self, timeout: t.Optional[float] = None) -> t.Optional[int]:
        """Wait for the process to finish."""
        if self.proc is None:
            return None
        try:
            self.exit_code = self.proc.wait(timeout=timeout)
            self.done = True
            self.end_time = time.time()
            return self.exit_code
        except subprocess.TimeoutExpired:
            return None

    def poll(self) -> t.Optional[int]:
        """Check if process has exited."""
        if self.proc is None:
            return None
        code = self.proc.poll()
        if code is not None:
            self.exit_code = code
            self.done = True
            self.end_time = time.time()
        return code

    def kill(self) -> None:
        """Kill the process."""
        if self.proc and self.running:
            if IS_POSIX:
                self.proc.send_signal(signal.SIGTERM)
            else:
                self.proc.terminate()

    def __repr__(self) -> str:
        status = "done" if self.done else "running"
        return f"BgProc({self.pid}, {self.command!r}, {status})"


# ---------------------------------------------------------------------------
# Background process manager
# ---------------------------------------------------------------------------

class BackgroundManager:
    """Manages background processes."""

    def __init__(self) -> None:
        self._processes: t.Dict[int, BackgroundProcess] = {}
        self._lock = threading.Lock()

    def add(self, proc: BackgroundProcess) -> None:
        """Register a background process."""
        with self._lock:
            self._processes[proc.pid] = proc

    def remove(self, pid: int) -> t.Optional[BackgroundProcess]:
        """Remove a process from tracking."""
        with self._lock:
            return self._processes.pop(pid, None)

    def get(self, pid: int) -> t.Optional[BackgroundProcess]:
        """Get a process by PID."""
        with self._lock:
            return self._processes.get(pid)

    def list(self) -> t.List[BackgroundProcess]:
        """List all tracked processes."""
        with self._lock:
            return list(self._processes.values())

    def list_running(self) -> t.List[BackgroundProcess]:
        """List running processes."""
        return [p for p in self.list() if p.running]

    def list_done(self) -> t.List[BackgroundProcess]:
        """List finished processes."""
        return [p for p in self.list() if p.done]

    def poll_all(self) -> None:
        """Poll all processes to update status."""
        for proc in self.list():
            proc.poll()

    def reap_done(self) -> t.List[BackgroundProcess]:
        """Remove and return finished processes."""
        done = self.list_done()
        for p in done:
            self.remove(p.pid)
        return done

    def kill_all(self) -> None:
        """Kill all running processes."""
        for proc in self.list_running():
            proc.kill()

    def notify_completion(self) -> t.List[BackgroundProcess]:
        """Check for newly completed processes and return them."""
        completed = []
        for proc in self.list_running():
            if proc.poll() is not None:
                completed.append(proc)
        return completed

    def __len__(self) -> int:
        return len(self._processes)

    def __repr__(self) -> str:
        return f"BgManager(running={len(self.list_running())}, total={len(self)})"


# ---------------------------------------------------------------------------
# I/O redirection
# ---------------------------------------------------------------------------

class RedirectHandler:
    """Handles I/O redirection for commands."""

    @staticmethod
    def apply_redirects(
        redirects: t.List[RedirectInfo],
        stdin: t.Optional[t.IO] = None,
        stdout: t.Optional[t.IO] = None,
        stderr: t.Optional[t.IO] = None,
    ) -> dict:
        """Apply redirections, returning a dict of {fd: (mode, target)}."""
        result = {
            0: stdin if stdin else None,
            1: stdout if stdout else None,
            2: stderr if stderr else None,
        }
        close_fds: t.List[int] = []

        for redirect in redirects:
            if redirect.type == RedirectInfo.Type.INPUT:
                try:
                    f = open(redirect.target, 'r')
                    result[0] = f
                except FileNotFoundError:
                    raise ShellError(f"No such file: {redirect.target}")
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.OUTPUT:
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'w')
                    result[1] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.APPEND:
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'a')
                    result[1] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.STDERR_OUTPUT:
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'w')
                    result[2] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.STDERR_APPEND:
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'a')
                    result[2] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.STDERR_MERGE:
                # 2>&1 - stderr goes to same place as stdout
                if result[1] is not None and isinstance(result[1], io.IOBase):
                    result[2] = result[1]
                # If stdout is a pipe or inherited, stderr will inherit same fd

            elif redirect.type == RedirectInfo.Type.OUTPUT_MERGE:
                # &> - both stdout and stderr to file
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'w')
                    result[1] = f
                    result[2] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.ALL_APPEND:
                # &>> - both stdout and stderr to file (append)
                try:
                    ensure_dir(os.path.dirname(os.path.abspath(redirect.target)))
                    f = open(redirect.target, 'a')
                    result[1] = f
                    result[2] = f
                except PermissionError:
                    raise ShellError(f"Permission denied: {redirect.target}")

            elif redirect.type == RedirectInfo.Type.HEREDOC:
                # Heredoc: read from stdin until delimiter found
                # This is handled at parse/execution level
                result[0] = RedirectHandler._create_heredoc(redirect.target)

            elif redirect.type == RedirectInfo.Type.HERESTR:
                # Here-string: <<< "string"
                result[0] = io.StringIO(redirect.target)

        return result

    @staticmethod
    def _create_heredoc(delimiter: str) -> io.StringIO:
        """Create a heredoc input stream waiting for user input."""
        # In interactive mode, this would read from terminal
        # For now, collect from stdin until delimiter
        lines = []
        print(f">> (reading heredoc until '{delimiter}')")
        try:
            for line in sys.stdin:
                if line.rstrip('\n') == delimiter:
                    break
                lines.append(line)
        except EOFError:
            pass
        return io.StringIO(''.join(lines))

    @staticmethod
    def clean_up(fds: dict) -> None:
        """Close any opened file descriptors."""
        for fd_key, fd_val in fds.items():
            if fd_val is not None and isinstance(fd_val, io.IOBase) and fd_val not in (sys.stdin, sys.stdout, sys.stderr):
                try:
                    fd_val.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Command executor
# ---------------------------------------------------------------------------

class CommandExecutor:
    """Executes parsed commands and pipelines."""

    def __init__(self) -> None:
        self.bg_manager = BackgroundManager()
        self._last_exit_code = 0

    def execute_command(
        self,
        cmd: ParsedCommand,
        stdin: t.Optional[t.IO] = None,
        stdout: t.Optional[t.IO] = None,
        stderr: t.Optional[t.IO] = None,
        timeout: t.Optional[float] = None,
        background: bool = False,
    ) -> ExecutionResult:
        """Execute a single parsed command."""
        timer = Timer()
        timer.start()

        result = ExecutionResult(
            command=cmd.command,
            args=cmd.args,
        )

        try:
            # Check if it's a built-in
            from .builtins import BUILTINS
            if cmd.command in BUILTINS:
                # Execute built-in
                builtin_func = BUILTINS[cmd.command]
                rc = builtin_func(cmd.args, stdin=stdin, stdout=stdout, stderr=stderr)
                result.exit_code = rc
                result.stdout = ""
                result.stderr = ""
            else:
                # Execute external command
                rc = self._execute_external(
                    cmd, stdin, stdout, stderr, timeout, background, result
                )
                result.exit_code = rc

        except ShellError as e:
            result.exit_code = e.exit_code
            result.stderr = e.message
            if stderr:
                stderr.write(e.message + "\n")
        except FileNotFoundError as e:
            result.exit_code = 127
            result.stderr = str(e)
            if stderr:
                stderr.write(str(e) + "\n")
        except PermissionError as e:
            result.exit_code = 126
            result.stderr = str(e)
            if stderr:
                stderr.write(str(e) + "\n")
        except Exception as e:
            result.exit_code = 1
            result.stderr = str(e)
            if stderr:
                stderr.write(str(e) + "\n")

        timer.stop()
        result.duration = timer.elapsed
        self._last_exit_code = result.exit_code

        return result

    def _execute_external(
        self,
        cmd: ParsedCommand,
        stdin: t.Optional[t.IO],
        stdout: t.Optional[t.IO],
        stderr: t.Optional[t.IO],
        timeout: t.Optional[float],
        background: bool,
        result: ExecutionResult,
    ) -> int:
        """Execute an external command as a subprocess."""
        executable = find_executable(cmd.command)
        if executable is None:
            raise CommandNotFoundError(cmd.command)

        # Build full command arguments
        full_args = [executable] + cmd.args

        # Prepare I/O
        stdin_pipe = stdin if stdin else subprocess.PIPE
        stdout_pipe = stdout if stdout else subprocess.PIPE
        stderr_pipe = stderr if stderr else subprocess.PIPE

        # Handle redirections
        redirects = RedirectHandler.apply_redirects(
            cmd.redirects, stdin, stdout, stderr
        )

        # Use redirected files where specified
        if redirects[0] is not None:
            stdin_pipe = redirects[0]
        if redirects[1] is not None:
            stdout_pipe = redirects[1]
        if redirects[2] is not None:
            stderr_pipe = redirects[2]

        # Build environment
        env = os.environ.copy()
        for key, value in cmd.env_vars.items():
            env[key] = value

        try:
            # On Windows, use shell=False for direct execution
            # On POSIX, use shell=False and pass the executable directly
            proc = subprocess.Popen(
                full_args,
                stdin=stdin_pipe,
                stdout=stdout_pipe,
                stderr=stderr_pipe,
                env=env,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )

            result.pid = proc.pid

            if background:
                bg_proc = BackgroundProcess(proc.pid, cmd.command, proc)
                self.bg_manager.add(bg_proc)
                result.background = True
                result.bg_pid = proc.pid
                # Don't wait for background processes
                return 0

            if timeout:
                try:
                    stdout_data, stderr_data = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout_data, stderr_data = proc.communicate()
                    result.timed_out = True
                    return 124  # Timeout exit code
            else:
                stdout_data, stderr_data = proc.communicate()

            result.stdout = stdout_data or ""
            result.stderr = stderr_data or ""
            return proc.returncode

        except OSError as e:
            raise ShellError(f"Failed to execute {cmd.command}: {e}")
        finally:
            RedirectHandler.clean_up(redirects)

    def execute_pipeline(
        self,
        pipeline: Pipeline,
        stdin: t.Optional[t.IO] = None,
        stdout: t.Optional[t.IO] = None,
        stderr: t.Optional[t.IO] = None,
        timeout: t.Optional[float] = None,
    ) -> t.List[ExecutionResult]:
        """Execute a pipeline of commands connected by pipes."""
        if not pipeline.commands:
            return []

        results: t.List[ExecutionResult] = []

        # Single command, no piping needed
        if len(pipeline.commands) == 1:
            result = self.execute_command(
                pipeline.commands[0],
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                background=pipeline.background,
            )
            results.append(result)
            return results

        # Multi-command pipeline
        # For simplicity, we execute each command sequentially
        # and pipe the output of one to the input of the next
        prev_stdout: t.Optional[t.IO] = None

        for i, cmd in enumerate(pipeline.commands):
            is_last = i == len(pipeline.commands) - 1

            cmd_stdin = stdin if i == 0 else prev_stdout
            cmd_stdout = stdout if is_last else subprocess.PIPE
            cmd_stderr = stderr or sys.stderr

            # We need to handle piping differently for subprocesses
            # For simplicity, if we're piping, capture output and feed it
            if not is_last and not isinstance(cmd_stdout, io.IOBase):
                # Execute with output capture
                result = self.execute_command(
                    cmd,
                    stdin=cmd_stdin,
                    stdout=subprocess.PIPE,
                    stderr=cmd_stderr,
                    timeout=timeout,
                )

                # Create a StringIO from the output for the next command
                if result.stdout:
                    prev_stdout = io.StringIO(result.stdout)
                else:
                    prev_stdout = io.StringIO("")
            else:
                result = self.execute_command(
                    cmd,
                    stdin=cmd_stdin,
                    stdout=cmd_stdout,
                    stderr=cmd_stderr,
                    timeout=timeout,
                    background=pipeline.background if is_last else False,
                )
                prev_stdout = None

            results.append(result)

        return results

    def execute_commands(
        self,
        pipelines: t.List[Pipeline],
        stdin: t.Optional[t.IO] = None,
        stdout: t.Optional[t.IO] = None,
        stderr: t.Optional[t.IO] = None,
    ) -> t.List[t.List[ExecutionResult]]:
        """Execute multiple pipelines sequentially."""
        all_results = []
        for pipeline in pipelines:
            results = self.execute_pipeline(
                pipeline, stdin=stdin, stdout=stdout, stderr=stderr
            )
            all_results.append(results)
        return all_results

    def get_last_exit_code(self) -> int:
        """Get the exit code of the last command."""
        return self._last_exit_code

    def set_last_exit_code(self, code: int) -> None:
        """Set the last exit code (used internally)."""
        self._last_exit_code = code

    def get_background_processes(self) -> t.List[BackgroundProcess]:
        """Get all background processes."""
        return self.bg_manager.list()

    def get_running_background(self) -> t.List[BackgroundProcess]:
        """Get running background processes."""
        return self.bg_manager.list_running()

    def kill_background(self, pid: int) -> bool:
        """Kill a background process by PID."""
        proc = self.bg_manager.get(pid)
        if proc:
            proc.kill()
            return True
        return False

    def wait_background(self, pid: int) -> t.Optional[int]:
        """Wait for a background process to finish."""
        proc = self.bg_manager.get(pid)
        if proc:
            return proc.wait()
        return None

    def cleanup_background(self) -> None:
        """Clean up finished background processes."""
        self.bg_manager.reap_done()

    def __repr__(self) -> str:
        return f"CommandExecutor(bg={len(self.bg_manager)})"


# ---------------------------------------------------------------------------
# Module-level executor singleton
# ---------------------------------------------------------------------------

_executor: t.Optional[CommandExecutor] = None


def get_executor() -> CommandExecutor:
    """Get the global executor singleton."""
    global _executor
    if _executor is None:
        _executor = CommandExecutor()
    return _executor


__all__ = [
    "ExecutionResult",
    "BackgroundProcess",
    "BackgroundManager",
    "RedirectHandler",
    "CommandExecutor",
    "get_executor",
]