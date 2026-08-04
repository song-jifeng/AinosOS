"""
容器执行模块 - Command execution within Ainos containers.

支持:
- 在容器内执行命令
- 交互式终端
- 环境变量管理
- 工作目录设置
- 用户/组切换
- 标准流处理
"""

import logging
import os
import pty
import select
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, TextIO, Union

logger = logging.getLogger(__name__)


class ExecError(Exception):
    """Raised when a container execution fails."""

    def __init__(self, message: str, exit_code: Optional[int] = None) -> None:
        self.exit_code = exit_code
        super().__init__(f"Exec error (exit={exit_code}): {message}" if exit_code is not None else f"Exec error: {message}")


@dataclass
class ExecConfig:
    """Configuration for container execution."""

    command: list[str]
    working_dir: str = "/"
    env: dict[str, str] = field(default_factory=dict)
    user: str = "root"
    group: Optional[str] = None
    tty: bool = False
    interactive: bool = False
    privileged: bool = False
    timeout: Optional[int] = None
    stdin: Optional[Union[str, TextIO]] = None
    stdout: Optional[Union[str, TextIO]] = None
    stderr: Optional[Union[str, TextIO]] = None
    no_new_privs: bool = True
    capabilities: list[str] = field(default_factory=list)
    cgroup_pid: Optional[int] = None

    def validate(self) -> None:
        """Validate exec configuration."""
        if not self.command:
            raise ValueError("Command must not be empty")
        if not self.working_dir.startswith("/"):
            raise ValueError(f"Working directory must be absolute: {self.working_dir}")


class ExecResult:
    """Result of a container execution."""

    def __init__(
        self,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        pid: Optional[int] = None,
        timed_out: bool = False,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.pid = pid
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        """Check if the execution was successful."""
        return self.exit_code == 0

    def __repr__(self) -> str:
        return (
            f"ExecResult(exit_code={self.exit_code}, pid={self.pid}, "
            f"stdout_len={len(self.stdout)}, stderr_len={len(self.stderr)}, "
            f"timed_out={self.timed_out})"
        )


class Executor:
    """
    Handles command execution inside containers.

    Manages process lifecycle, TTY allocation, and I/O streams
    for commands run within a container's namespaces.
    """

    # Minimum environment variables for container
    MINIMAL_ENV: ClassVar[dict[str, str]] = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "TERM": "xterm-256color",
        "CONTAINER": "ainos",
    }

    def __init__(self, container_id: str, rootfs: str, container_pid: Optional[int] = None) -> None:
        self.container_id = container_id
        self.rootfs = rootfs
        self.container_pid = container_pid

    def _build_env(self, config: ExecConfig) -> dict[str, str]:
        """
        Build the environment variables for execution.

        Args:
            config: Execution configuration.

        Returns:
            Complete environment dictionary.
        """
        env = dict(self.MINIMAL_ENV)

        # Add user-provided env vars
        env.update(config.env)

        # Set HOME based on user
        if config.user == "root":
            env["HOME"] = "/root"
        else:
            env["HOME"] = f"/home/{config.user}"

        # Set working directory
        env["PWD"] = config.working_dir

        return env

    def _chroot_exec(self, config: ExecConfig) -> subprocess.Popen:
        """
        Execute a command inside the container's rootfs using chroot.

        Args:
            config: Execution configuration.

        Returns:
            Popen process handle.

        Raises:
            ExecError: If execution setup fails.
        """
        config.validate()
        env = self._build_env(config)

        # Build the full command: chroot into rootfs then run
        cmd = ["chroot", self.rootfs]

        # Set working directory
        if config.working_dir != "/":
            cmd.extend(["--working-dir", config.working_dir])

        if config.user and config.user != "root":
            cmd.extend(["--userspec", config.user])

        cmd.extend(config.command)

        # Prepare stdio
        stdin = config.stdin if config.stdin else subprocess.PIPE
        stdout = config.stdout if config.stdout else subprocess.PIPE
        stderr = config.stderr if config.stderr else subprocess.PIPE

        try:
            process = subprocess.Popen(
                cmd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                env=env,
                cwd=config.working_dir,
                preexec_fn=self._preexec(config),
            )
            return process
        except OSError as e:
            raise ExecError(f"Failed to start process: {e}") from e

    def _preexec(self, config: ExecConfig) -> callable:
        """Create pre-exec function for process setup."""
        def setup() -> None:
            try:
                # Set process group
                os.setpgid(0, 0)

                # Set no_new_privs
                if config.no_new_privs:
                    # prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
                    import ctypes
                    libc = ctypes.CDLL(None, use_errno=True)
                    PR_SET_NO_NEW_PRIVS = 38
                    libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)

                # Reset signal handlers
                signal.signal(signal.SIGPIPE, signal.SIG_DFL)
                signal.signal(signal.SIGCHLD, signal.SIG_DFL)

            except Exception as e:
                logger.warning("Pre-exec setup failed: %s", e)

        return setup

    def _exec_enter_ns(self, config: ExecConfig) -> subprocess.Popen:
        """
        Execute a command inside the container's namespaces using nsenter.

        Args:
            config: Execution configuration.

        Returns:
            Popen process handle.
        """
        if not self.container_pid:
            raise ExecError("Container PID not set; cannot enter namespaces")

        env = self._build_env(config)

        cmd = [
            "nsenter",
            "--target", str(self.container_pid),
            "--mount", "--pid", "--net", "--ipc", "--uts",
        ]

        if config.working_dir != "/":
            cmd.extend(["--wd", config.working_dir])

        cmd.extend(["--", "chroot", self.rootfs])
        if config.user and config.user != "root":
            cmd.extend(["--userspec", config.user])
        cmd.extend(config.command)

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if config.stdin else None,
                stdout=subprocess.PIPE if config.stdout else None,
                stderr=subprocess.PIPE if config.stderr else None,
                env=env,
                preexec_fn=self._preexec(config),
            )
            return process
        except OSError as e:
            raise ExecError(f"Failed to start process via nsenter: {e}") from e

    def execute(self, config: ExecConfig) -> ExecResult:
        """
        Execute a command in the container.

        Args:
            config: Execution configuration.

        Returns:
            ExecResult with exit code and output.
        """
        config.validate()

        use_nsenter = self.container_pid is not None
        process = self._exec_enter_ns(config) if use_nsenter else self._chroot_exec(config)

        stdin_data: Optional[bytes] = None
        if isinstance(config.stdin, str):
            stdin_data = config.stdin.encode("utf-8")
            process.stdin = subprocess.PIPE

        stdout_data: Optional[bytes] = None
        stderr_data: Optional[bytes] = None

        try:
            stdout_data, stderr_data = process.communicate(
                input=stdin_data,
                timeout=config.timeout,
            )
            exit_code = process.returncode or 0
            timed_out = False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_data, stderr_data = process.communicate()
            exit_code = -1
            timed_out = True

        result = ExecResult(
            exit_code=exit_code,
            stdout=stdout_data.decode("utf-8", errors="replace") if stdout_data else "",
            stderr=stderr_data.decode("utf-8", errors="replace") if stderr_data else "",
            pid=process.pid,
            timed_out=timed_out,
        )

        logger.info(
            "Executed command in container %s: %s (exit=%d, pid=%s)",
            self.container_id, config.command[0], exit_code, process.pid,
        )
        return result

    def execute_interactive(
        self,
        config: ExecConfig,
        input_stream: Optional[TextIO] = None,
        output_stream: Optional[TextIO] = None,
    ) -> int:
        """
        Execute a command in the container with interactive TTY.

        Args:
            config: Execution configuration.
            input_stream: Input stream (defaults to sys.stdin).
            output_stream: Output stream (defaults to sys.stdout).

        Returns:
            Exit code of the command.
        """
        config.validate()
        config.tty = True
        config.interactive = True

        input_stream = input_stream or sys.stdin
        output_stream = output_stream or sys.stdout

        env = self._build_env(config)

        # Allocate PTY
        master_fd, slave_fd = pty.openpty()

        use_nsenter = self.container_pid is not None
        if use_nsenter:
            cmd = [
                "nsenter",
                "--target", str(self.container_pid),
                "--mount", "--pid", "--net", "--ipc", "--uts",
                "--", "chroot", self.rootfs,
            ]
        else:
            cmd = ["chroot", self.rootfs]

        if config.working_dir != "/":
            cmd.extend(["--working-dir", config.working_dir])
        if config.user and config.user != "root":
            cmd.extend(["--userspec", config.user])
        cmd.extend(config.command)

        try:
            process = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
                preexec_fn=os.setsid,
            )

            os.close(slave_fd)

            # Terminal size
            try:
                import struct
                import fcntl
                import termios

                def set_winsize(fd: int) -> None:
                    try:
                        size = struct.pack("HHHH", 24, 80, 0, 0)
                        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
                    except OSError:
                        pass

                set_winsize(master_fd)
            except ImportError:
                pass

            # I/O loop
            poll = select.poll()
            poll.register(master_fd, select.POLLIN)
            poll.register(input_stream, select.POLLIN)

            exiting = False

            while process.poll() is None or not exiting:
                try:
                    events = poll.poll(100)

                    for fd, event in events:
                        if event & select.POLLIN:
                            if fd == master_fd:
                                data = os.read(master_fd, 4096)
                                if not data:
                                    exiting = True
                                    break
                                output_stream.buffer.write(data)
                                output_stream.flush()
                            elif fd == input_stream.fileno():
                                data = input_stream.buffer.read(4096)
                                if not data:
                                    exiting = True
                                    break
                                os.write(master_fd, data)
                except OSError:
                    break

            # Read remaining output
            try:
                while True:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    output_stream.buffer.write(data)
                    output_stream.flush()
            except OSError:
                pass

            os.close(master_fd)
            process.wait()
            return process.returncode or 0

        except OSError as e:
            raise ExecError(f"Interactive execution failed: {e}") from e

    def execute_detached(self, config: ExecConfig) -> int:
        """
        Execute a command in the container in detached mode (background).

        Args:
            config: Execution configuration.

        Returns:
            PID of the detached process.
        """
        config.validate()

        env = self._build_env(config)

        use_nsenter = self.container_pid is not None
        if use_nsenter:
            cmd = [
                "nsenter",
                "--target", str(self.container_pid),
                "--mount", "--pid", "--net", "--ipc", "--uts",
                "--", "chroot", self.rootfs,
            ]
        else:
            cmd = ["chroot", self.rootfs]

        if config.working_dir != "/":
            cmd.extend(["--working-dir", config.working_dir])
        if config.user and config.user != "root":
            cmd.extend(["--userspec", config.user])
        cmd.extend(config.command)

        try:
            # Fork and detach
            pid = os.fork()
            if pid == 0:
                # Child
                os.setsid()
                # Redirect stdio to /dev/null
                devnull = os.open(os.devnull, os.O_RDWR)
                os.dup2(devnull, 0)
                os.dup2(devnull, 1)
                os.dup2(devnull, 2)
                os.close(devnull)

                os.execve(cmd[0], cmd, env)

            logger.info("Detached execution in container %s: PID %d", self.container_id, pid)
            return pid

        except OSError as e:
            raise ExecError(f"Detached execution failed: {e}") from e

    def signal_process(self, pid: int, sig: int = signal.SIGTERM) -> None:
        """
        Send a signal to a process in the container.

        Args:
            pid: Process ID to signal.
            sig: Signal number (default SIGTERM).

        Raises:
            ExecError: If signaling fails.
        """
        try:
            if self.container_pid:
                # Signal via nsenter
                import subprocess as sp
                sp.run(
                    ["nsenter", "--target", str(self.container_pid), "--pid",
                     "--", "kill", "-" + str(sig), str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                os.kill(pid, sig)
            logger.debug("Sent signal %d to PID %d in container %s", sig, pid, self.container_id)
        except OSError as e:
            raise ExecError(f"Failed to signal process {pid}: {e}") from e

    def cleanup(self) -> None:
        """Clean up executor resources."""
        logger.debug("Cleaned up executor for container %s", self.container_id)