"""
Built-in commands for Ainos Shell.

Provides implementations of essential shell built-in commands:
- File system: cd, ls, pwd, echo, cat, mkdir, rmdir, cp, mv, rm, touch, head, tail, wc
- Text processing: grep, sort, uniq, cut, tr, sed (basic)
- Process: ps, kill, jobs, fg, bg
- Shell: exit, help, source, alias, unalias, set, unset, export, type, which
- OS: clear, env, printenv, which, date, sleep, yes, true, false
- Ainos: ainos, theme, config, history, plugin, ai
- Network: ping (basic), hostname
- Info: uname, whoami, id, uptime, cal, df, du, free, lsof
"""

from __future__ import annotations

import io
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import typing as t
from datetime import datetime
from pathlib import Path

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    AnsiCode,
    colorize,
    human_readable_size,
    human_readable_time,
    expanduser,
    find_executable,
    list_files,
    file_size,
    file_modified_time,
    list_processes,
    kill_process,
    get_env,
    set_env,
    unset_env,
    ensure_dir,
    file_exists,
    dir_exists,
    terminal_width,
    ShellError,
    CommandNotFoundError,
)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

BuiltinFunc = t.Callable[
    [t.List[str]],
    int,
]


# ---------------------------------------------------------------------------
# Helper for built-in commands
# ---------------------------------------------------------------------------

def _print(text: str = "", end: str = "\n", file: t.Optional[t.IO] = None) -> None:
    """Print helper that writes to the correct output."""
    if file is None:
        file = sys.stdout
    file.write(text + end)
    file.flush()


def _eprint(text: str = "", end: str = "\n") -> None:
    """Print to stderr."""
    _print(text, end=end, file=sys.stderr)


def _parse_args(args: t.List[str], flags: str) -> t.Tuple[dict, t.List[str]]:
    """Simple argument parser for built-in commands."""
    import getopt
    try:
        opts, remaining = getopt.getopt(args, flags)
        opt_dict = dict(opts)
        return opt_dict, remaining
    except getopt.GetoptError as e:
        _eprint(f"Error: {e}")
        return {}, args


# ---------------------------------------------------------------------------
# cd - Change directory
# ---------------------------------------------------------------------------

def builtin_cd(args: t.List[str]) -> int:
    """Change the current working directory.

    Usage: cd [directory]
    If no directory is given, change to HOME.
    """
    if len(args) > 1:
        _eprint("cd: too many arguments")
        return 1

    if len(args) == 0 or args[0] in ("~", ""):
        target = os.environ.get("HOME", os.environ.get("USERPROFILE", ""))
        if not target:
            _eprint("cd: HOME not set")
            return 1
    elif args[0] == "-":
        # Go to previous directory
        target = os.environ.get("OLDPWD", "")
        if not target:
            _eprint("cd: OLDPWD not set")
            return 1
        _print(target)
    else:
        target = expanduser(args[0])

    try:
        os.chdir(target)
        os.environ["OLDPWD"] = os.environ.get("PWD", "")
        os.environ["PWD"] = os.getcwd()
        return 0
    except FileNotFoundError:
        _eprint(f"cd: no such directory: {target}")
        return 1
    except PermissionError:
        _eprint(f"cd: permission denied: {target}")
        return 1
    except NotADirectoryError:
        _eprint(f"cd: not a directory: {target}")
        return 1


# ---------------------------------------------------------------------------
# pwd - Print working directory
# ---------------------------------------------------------------------------

def builtin_pwd(args: t.List[str]) -> int:
    """Print the current working directory.

    Usage: pwd
    """
    try:
        _print(os.getcwd())
        return 0
    except Exception as e:
        _eprint(f"pwd: {e}")
        return 1


# ---------------------------------------------------------------------------
# ls - List directory contents
# ---------------------------------------------------------------------------

def builtin_ls(args: t.List[str]) -> int:
    """List directory contents.

    Usage: ls [-la] [path...]
    """
    show_all = False
    long_format = False
    human_readable = False
    recursive = False
    dirs: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        flag = args[i]
        if flag == "--":
            i += 1
            break
        for c in flag[1:]:
            if c == "a":
                show_all = True
            elif c == "l":
                long_format = True
            elif c == "h":
                human_readable = True
            elif c == "R":
                recursive = True
            elif c == "d":
                # List directory entries themselves, not contents
                dirs.append(".")
                break
        i += 1

    if not dirs:
        dirs = args[i:] if i < len(args) else ["."]

    exit_code = 0
    first = True
    for d in dirs:
        if not first:
            _print()
        first = False

        try:
            path = expanduser(d)
            if not os.path.exists(path):
                _eprint(f"ls: cannot access '{d}': No such file or directory")
                exit_code = 1
                continue

            if os.path.isfile(path):
                if long_format:
                    _print_long_format(path)
                else:
                    _print(os.path.basename(path))
                continue

            entries = sorted(os.listdir(path))
            if not show_all:
                entries = [e for e in entries if not e.startswith(".")]

            if long_format:
                total_blocks = 0
                file_infos = []
                for entry in entries:
                    full_path = os.path.join(path, entry)
                    try:
                        st = os.stat(full_path)
                        total_blocks += st.st_blocks
                        file_infos.append((entry, full_path, st))
                    except OSError:
                        file_infos.append((entry, full_path, None))

                if len(dirs) > 1:
                    _print(f"{d}:")

                # Print total blocks (only for directories)
                if total_blocks > 0:
                    _print(f"total {total_blocks}")

                for entry, full_path, st in file_infos:
                    if st is None:
                        _print(f"?--------- ? ? ? ? {entry}")
                        continue
                    _print(_format_long(entry, full_path, st, human_readable))
            else:
                if len(dirs) > 1:
                    _print(f"{d}:")

                # Columnar output
                _print_columns(entries)

        except PermissionError:
            _eprint(f"ls: cannot open directory '{d}': Permission denied")
            exit_code = 1

    return exit_code


def _print_long_format(path: str) -> None:
    """Print a single file in long format."""
    try:
        st = os.stat(path)
        _print(_format_long(os.path.basename(path), path, st, True))
    except OSError:
        _print(f"?--------- ? ? ? ? {os.path.basename(path)}")


def _format_long(name: str, full_path: str, st: os.stat_result, human: bool = False) -> str:
    """Format a file entry in long format."""
    # File type and permissions
    mode = st.st_mode
    type_char = "d" if stat.S_ISDIR(mode) else "l" if stat.S_ISLNK(mode) else "-"
    perms = ""
    for who in "USR", "GRP", "OTH":
        for what in "R", "W", "X":
            bit = getattr(stat, f"S_I{what}{who}")
            perms += what.lower() if mode & bit else "-"
    perm_str = type_char + perms

    # Number of links
    nlink = st.st_nlink

    # Owner and group
    try:
        import pwd
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (ImportError, KeyError):
        owner = str(st.st_uid)

    try:
        import grp
        group = grp.getgrgid(st.st_gid).gr_name
    except (ImportError, KeyError):
        group = str(st.st_gid)

    # Size
    size = st.st_size
    size_str = human_readable_size(size) if human else str(size)

    # Modification time
    mtime = human_readable_time(st.st_mtime)

    return f"{perm_str} {nlink:>3} {owner:<8} {group:<8} {size_str:>8} {mtime} {name}"


def _print_columns(entries: t.List[str]) -> None:
    """Print entries in columnar format."""
    if not entries:
        return

    width = terminal_width()
    max_len = max(len(e) for e in entries) + 2
    cols = max(1, width // max_len)
    rows = (len(entries) + cols - 1) // cols

    for row in range(rows):
        line = ""
        for col in range(cols):
            idx = row + col * rows
            if idx < len(entries):
                line += entries[idx].ljust(max_len)
        _print(line.rstrip())


# ---------------------------------------------------------------------------
# echo - Print arguments
# ---------------------------------------------------------------------------

def builtin_echo(args: t.List[str]) -> int:
    """Print arguments to stdout.

    Usage: echo [-n] [text...]
    """
    no_newline = False
    texts: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-n":
            no_newline = True
        elif args[i] == "-e":
            pass  # Enable escape sequences (stub)
        elif args[i] == "-E":
            pass  # Disable escape sequences (stub)
        elif args[i] == "--":
            i += 1
            break
        else:
            break
        i += 1

    texts = args[i:]
    _print(" ".join(texts), end="" if no_newline else "\n")
    return 0


# ---------------------------------------------------------------------------
# cat - Concatenate files
# ---------------------------------------------------------------------------

def builtin_cat(args: t.List[str]) -> int:
    """Concatenate files and print to stdout.

    Usage: cat [file...]
    If no file, read from stdin.
    """
    if not args:
        # Read from stdin
        try:
            for line in sys.stdin:
                _print(line, end="")
        except KeyboardInterrupt:
            pass
        return 0

    exit_code = 0
    for arg in args:
        path = expanduser(arg)
        try:
            with open(path, "r") as f:
                shutil.copyfileobj(f, sys.stdout)
        except FileNotFoundError:
            _eprint(f"cat: {arg}: No such file or directory")
            exit_code = 1
        except PermissionError:
            _eprint(f"cat: {arg}: Permission denied")
            exit_code = 1
        except IsADirectoryError:
            _eprint(f"cat: {arg}: Is a directory")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# mkdir - Create directories
# ---------------------------------------------------------------------------

def builtin_mkdir(args: t.List[str]) -> int:
    """Create directories.

    Usage: mkdir [-p] directory...
    """
    parents = False
    dirs: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-p":
            parents = True
        elif args[i] == "--":
            i += 1
            break
        else:
            for c in args[i][1:]:
                if c == "p":
                    parents = True
        i += 1

    dirs = args[i:]
    if not dirs:
        _eprint("mkdir: missing operand")
        return 1

    exit_code = 0
    for d in dirs:
        path = expanduser(d)
        try:
            if parents:
                os.makedirs(path, exist_ok=True)
            else:
                os.mkdir(path)
        except FileExistsError:
            _eprint(f"mkdir: cannot create directory '{d}': File exists")
            exit_code = 1
        except PermissionError:
            _eprint(f"mkdir: cannot create directory '{d}': Permission denied")
            exit_code = 1
        except FileNotFoundError:
            _eprint(f"mkdir: cannot create directory '{d}': No such file or directory")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# rmdir - Remove empty directories
# ---------------------------------------------------------------------------

def builtin_rmdir(args: t.List[str]) -> int:
    """Remove empty directories.

    Usage: rmdir directory...
    """
    if not args:
        _eprint("rmdir: missing operand")
        return 1

    exit_code = 0
    for d in args:
        path = expanduser(d)
        try:
            os.rmdir(path)
        except FileNotFoundError:
            _eprint(f"rmdir: failed to remove '{d}': No such file or directory")
            exit_code = 1
        except OSError as e:
            _eprint(f"rmdir: failed to remove '{d}': {e}")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# rm - Remove files
# ---------------------------------------------------------------------------

def builtin_rm(args: t.List[str]) -> int:
    """Remove files or directories.

    Usage: rm [-rf] path...
    """
    recursive = False
    force = False
    paths: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-rf" or args[i] == "-fr":
            recursive = True
            force = True
        elif args[i] == "-r":
            recursive = True
        elif args[i] == "-f":
            force = True
        elif args[i] == "--":
            i += 1
            break
        else:
            for c in args[i][1:]:
                if c == "r":
                    recursive = True
                elif c == "f":
                    force = True
        i += 1

    paths = args[i:]
    if not paths:
        if not force:
            _eprint("rm: missing operand")
            return 1
        return 0

    exit_code = 0
    for p in paths:
        path = expanduser(p)
        try:
            if os.path.isdir(path) and not recursive:
                _eprint(f"rm: cannot remove '{p}': Is a directory")
                exit_code = 1
                continue

            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=force)
            else:
                os.remove(path)
        except FileNotFoundError:
            if not force:
                _eprint(f"rm: cannot remove '{p}': No such file or directory")
                exit_code = 1
        except PermissionError:
            if not force:
                _eprint(f"rm: cannot remove '{p}': Permission denied")
                exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# cp - Copy files
# ---------------------------------------------------------------------------

def builtin_cp(args: t.List[str]) -> int:
    """Copy files or directories.

    Usage: cp [-r] source destination
    """
    recursive = False
    interactive = False
    paths: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-r" or args[i] == "-R":
            recursive = True
        elif args[i] == "-i":
            interactive = True
        elif args[i] == "-ri" or args[i] == "-ir":
            recursive = True
            interactive = True
        elif args[i] == "--":
            i += 1
            break
        else:
            for c in args[i][1:]:
                if c == "r":
                    recursive = True
                elif c == "i":
                    interactive = True
        i += 1

    paths = args[i:]
    if len(paths) < 2:
        _eprint("cp: missing file operand")
        return 1

    src = expanduser(paths[0])
    dst = expanduser(paths[-1])

    if len(paths) > 2:
        # Multiple sources - destination must be a directory
        if not os.path.isdir(dst):
            _eprint(f"cp: target '{paths[-1]}' is not a directory")
            return 1
        for s in paths[:-1]:
            src_path = expanduser(s)
            try:
                if os.path.isdir(src_path):
                    if recursive:
                        shutil.copytree(src_path, os.path.join(dst, os.path.basename(src_path)))
                    else:
                        _eprint(f"cp: omitting directory '{s}'")
                else:
                    shutil.copy2(src_path, dst)
            except FileNotFoundError:
                _eprint(f"cp: cannot stat '{s}': No such file or directory")
                return 1
        return 0

    try:
        if os.path.isdir(src):
            if recursive:
                shutil.copytree(src, dst)
            else:
                _eprint(f"cp: omitting directory '{paths[0]}'")
                return 1
        else:
            shutil.copy2(src, dst)
        return 0
    except FileNotFoundError:
        _eprint(f"cp: cannot stat '{paths[0]}': No such file or directory")
        return 1
    except FileExistsError:
        if interactive:
            response = input(f"cp: overwrite '{paths[-1]}'? ")
            if response.lower() not in ("y", "yes"):
                return 0
        _eprint(f"cp: cannot create '{paths[-1]}': File exists")
        return 1


# ---------------------------------------------------------------------------
# mv - Move files
# ---------------------------------------------------------------------------

def builtin_mv(args: t.List[str]) -> int:
    """Move/rename files or directories.

    Usage: mv source destination
    """
    if len(args) < 2:
        _eprint("mv: missing file operand")
        return 1

    src = expanduser(args[0])
    dst = expanduser(args[-1])

    if len(args) > 2:
        if not os.path.isdir(dst):
            _eprint(f"mv: target '{args[-1]}' is not a directory")
            return 1
        for s in args[:-1]:
            try:
                shutil.move(expanduser(s), dst)
            except FileNotFoundError:
                _eprint(f"mv: cannot stat '{s}': No such file or directory")
                return 1
        return 0

    try:
        shutil.move(src, dst)
        return 0
    except FileNotFoundError:
        _eprint(f"mv: cannot stat '{args[0]}': No such file or directory")
        return 1
    except PermissionError:
        _eprint(f"mv: cannot move '{args[0]}': Permission denied")
        return 1


# ---------------------------------------------------------------------------
# touch - Create/update file timestamps
# ---------------------------------------------------------------------------

def builtin_touch(args: t.List[str]) -> int:
    """Create empty files or update timestamps.

    Usage: touch file...
    """
    if not args:
        _eprint("touch: missing file operand")
        return 1

    exit_code = 0
    for arg in args:
        path = expanduser(arg)
        try:
            if os.path.exists(path):
                # Update timestamp
                os.utime(path, None)
            else:
                # Create empty file
                with open(path, "a"):
                    os.utime(path, None)
        except PermissionError:
            _eprint(f"touch: cannot touch '{arg}': Permission denied")
            exit_code = 1
        except OSError as e:
            _eprint(f"touch: cannot touch '{arg}': {e}")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# head - Display first lines of files
# ---------------------------------------------------------------------------

def builtin_head(args: t.List[str]) -> int:
    """Display the first lines of a file.

    Usage: head [-n lines] [file]
    """
    num_lines = 10
    files: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-n" and i + 1 < len(args):
            try:
                num_lines = int(args[i + 1])
                i += 2
                continue
            except ValueError:
                pass
        elif args[i].startswith("-n"):
            try:
                num_lines = int(args[i][2:])
                i += 1
                continue
            except ValueError:
                pass
        elif args[i] == "--":
            i += 1
            break
        i += 1

    files = args[i:] if i < len(args) else []

    if not files:
        # Read from stdin
        count = 0
        for line in sys.stdin:
            if count >= num_lines:
                break
            _print(line, end="")
            count += 1
        return 0

    exit_code = 0
    for idx, f in enumerate(files):
        if len(files) > 1:
            if idx > 0:
                _print()
            _print(f"==> {f} <==")

        try:
            with open(expanduser(f), "r") as fh:
                for _ in range(num_lines):
                    line = fh.readline()
                    if not line:
                        break
                    _print(line, end="")
        except FileNotFoundError:
            _eprint(f"head: {f}: No such file or directory")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# tail - Display last lines of files
# ---------------------------------------------------------------------------

def builtin_tail(args: t.List[str]) -> int:
    """Display the last lines of a file.

    Usage: tail [-n lines] [file]
    """
    num_lines = 10
    files: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-n" and i + 1 < len(args):
            try:
                num_lines = int(args[i + 1])
                i += 2
                continue
            except ValueError:
                pass
        elif args[i].startswith("-n"):
            try:
                num_lines = int(args[i][2:])
                i += 1
                continue
            except ValueError:
                pass
        elif args[i] == "--":
            i += 1
            break
        i += 1

    files = args[i:] if i < len(args) else []

    if not files:
        # Read from stdin
        lines = list(sys.stdin)
        for line in lines[-num_lines:]:
            _print(line, end="")
        return 0

    exit_code = 0
    for idx, f in enumerate(files):
        if len(files) > 1:
            if idx > 0:
                _print()
            _print(f"==> {f} <==")

        try:
            with open(expanduser(f), "r") as fh:
                lines = fh.readlines()
                for line in lines[-num_lines:]:
                    _print(line, end="")
        except FileNotFoundError:
            _eprint(f"tail: {f}: No such file or directory")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# wc - Word count
# ---------------------------------------------------------------------------

def builtin_wc(args: t.List[str]) -> int:
    """Count lines, words, and characters.

    Usage: wc [-lwc] [file...]
    """
    count_lines = True
    count_words = True
    count_chars = True
    files: t.List[str] = []

    for arg in args:
        if arg.startswith("-"):
            count_lines = False
            count_words = False
            count_chars = False
            for c in arg[1:]:
                if c == "l":
                    count_lines = True
                elif c == "w":
                    count_words = True
                elif c == "c":
                    count_chars = True
                elif c == "m":
                    count_chars = True
        else:
            files.append(arg)

    if not files:
        text = sys.stdin.read()
        lines = text.count("\n")
        words = len(text.split())
        chars = len(text)
        parts = []
        if count_lines:
            parts.append(f"{lines:>7}")
        if count_words:
            parts.append(f"{words:>7}")
        if count_chars:
            parts.append(f"{chars:>7}")
        _print(" ".join(parts))
        return 0

    total_lines = 0
    total_words = 0
    total_chars = 0

    for f in files:
        try:
            with open(expanduser(f), "r") as fh:
                text = fh.read()
            lines = text.count("\n")
            words = len(text.split())
            chars = len(text)
            total_lines += lines
            total_words += words
            total_chars += chars

            parts = []
            if count_lines:
                parts.append(f"{lines:>7}")
            if count_words:
                parts.append(f"{words:>7}")
            if count_chars:
                parts.append(f"{chars:>7}")
            _print(" ".join(parts) + f" {f}")
        except FileNotFoundError:
            _eprint(f"wc: {f}: No such file or directory")

    if len(files) > 1:
        parts = []
        if count_lines:
            parts.append(f"{total_lines:>7}")
        if count_words:
            parts.append(f"{total_words:>7}")
        if count_chars:
            parts.append(f"{total_chars:>7}")
        _print(" ".join(parts) + " total")

    return 0


# ---------------------------------------------------------------------------
# grep - Search text
# ---------------------------------------------------------------------------

def builtin_grep(args: t.List[str]) -> int:
    """Search for patterns in text.

    Usage: grep [-i] [-n] [-r] [-c] [-v] pattern [file...]
    """
    ignore_case = False
    show_numbers = False
    recursive = False
    count_only = False
    invert = False
    pattern = ""
    files: t.List[str] = []

    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "--":
            i += 1
            break
        for c in args[i][1:]:
            if c == "i":
                ignore_case = True
            elif c == "n":
                show_numbers = True
            elif c == "r":
                recursive = True
            elif c == "c":
                count_only = True
            elif c == "v":
                invert = True
        i += 1

    if i < len(args):
        pattern = args[i]
        i += 1

    files = args[i:]

    if not pattern:
        _eprint("grep: missing pattern")
        return 2

    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE

    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        _eprint(f"grep: invalid pattern: {e}")
        return 2

    match_count = 0

    def _search_file(path: str, filepath: str = "") -> int:
        """Search a single file, returning match count."""
        local_count = 0
        try:
            with open(path, "r", errors="replace") as fh:
                for line_num, line in enumerate(fh, 1):
                    line_stripped = line.rstrip("\n\r")
                    is_match = bool(regex.search(line_stripped))
                    if invert:
                        is_match = not is_match
                    if is_match:
                        local_count += 1
                        if not count_only:
                            prefix = ""
                            if show_numbers:
                                prefix = f"{line_num}:"
                            if filepath:
                                prefix = f"{filepath}:{prefix}"
                            _print(f"{prefix}{line_stripped}")
        except FileNotFoundError:
            _eprint(f"grep: {path}: No such file or directory")
        except PermissionError:
            _eprint(f"grep: {path}: Permission denied")
        except IsADirectoryError:
            if recursive:
                for root, dirs, filenames in os.walk(path):
                    for fn in filenames:
                        fp = os.path.join(root, fn)
                        _search_file(fp, fp)
        return local_count

    if not files:
        # Read from stdin
        for line_num, line in enumerate(sys.stdin, 1):
            line_stripped = line.rstrip("\n\r")
            is_match = bool(regex.search(line_stripped))
            if invert:
                is_match = not is_match
            if is_match:
                match_count += 1
                if not count_only:
                    prefix = f"{line_num}:" if show_numbers else ""
                    _print(f"{prefix}{line_stripped}")
    else:
        for f in files:
            path = expanduser(f)
            if os.path.isdir(path) and not recursive:
                _eprint(f"grep: {f}: Is a directory")
                continue
            mc = _search_file(path, f if len(files) > 1 else "")
            match_count += mc

    if count_only:
        if len(files) > 1:
            for f in files:
                path = expanduser(f)
                if os.path.isfile(path):
                    mc = _search_file(path)
                    _print(f"{f}:{mc}")
                else:
                    _print(f"{f}:0")
        else:
            _print(str(match_count))

    return 0 if match_count > 0 else 1


# ---------------------------------------------------------------------------
# sort - Sort lines
# ---------------------------------------------------------------------------

def builtin_sort(args: t.List[str]) -> int:
    """Sort lines of text.

    Usage: sort [-r] [-n] [file...]
    """
    reverse = False
    numeric = False
    files: t.List[str] = []

    for arg in args:
        if arg.startswith("-"):
            for c in arg[1:]:
                if c == "r":
                    reverse = True
                elif c == "n":
                    numeric = True
        else:
            files.append(arg)

    lines: t.List[str] = []

    if not files:
        lines = list(sys.stdin)
    else:
        for f in files:
            try:
                with open(expanduser(f), "r") as fh:
                    lines.extend(fh.readlines())
            except FileNotFoundError:
                _eprint(f"sort: {f}: No such file or directory")
                return 1

    if numeric:
        lines.sort(key=lambda x: float(x.strip() or 0), reverse=reverse)
    else:
        lines.sort(reverse=reverse)

    for line in lines:
        _print(line, end="")

    return 0


# ---------------------------------------------------------------------------
# uniq - Filter unique lines
# ---------------------------------------------------------------------------

def builtin_uniq(args: t.List[str]) -> int:
    """Filter adjacent duplicate lines.

    Usage: uniq [file]
    """
    count = False
    files: t.List[str] = []

    for arg in args:
        if arg == "-c":
            count = True
        elif not arg.startswith("-"):
            files.append(arg)

    lines: t.List[str] = []

    if not files:
        lines = list(sys.stdin)
    else:
        try:
            with open(expanduser(files[0]), "r") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            _eprint(f"uniq: {files[0]}: No such file or directory")
            return 1

    prev = None
    run_count = 0
    for line in lines:
        if line != prev:
            if prev is not None:
                if count:
                    _print(f"  {run_count:>4} {prev}", end="")
                else:
                    _print(prev, end="")
            prev = line
            run_count = 1
        else:
            run_count += 1

    if prev is not None:
        if count:
            _print(f"  {run_count:>4} {prev}", end="")
        else:
            _print(prev, end="")

    return 0


# ---------------------------------------------------------------------------
# env - Display environment variables
# ---------------------------------------------------------------------------

def builtin_env(args: t.List[str]) -> int:
    """Display environment variables.

    Usage: env [VAR=value] [command]
    """
    if args:
        # Run command with modified environment
        cmd_parts = []
        env_updates = {}
        for arg in args:
            if "=" in arg and not cmd_parts:
                k, v = arg.split("=", 1)
                env_updates[k] = v
            else:
                cmd_parts.append(arg)

        if cmd_parts:
            env = os.environ.copy()
            env.update(env_updates)
            try:
                subprocess.run(cmd_parts, env=env)
                return 0
            except FileNotFoundError:
                _eprint(f"env: '{cmd_parts[0]}': No such file or directory")
                return 127
            except Exception as e:
                _eprint(f"env: {e}")
                return 1
        else:
            for k, v in env_updates.items():
                _print(f"{k}={v}")
            return 0

    # Print all environment variables
    for key, value in sorted(os.environ.items()):
        _print(f"{key}={value}")
    return 0


# ---------------------------------------------------------------------------
# export - Set environment variable
# ---------------------------------------------------------------------------

def builtin_export(args: t.List[str]) -> int:
    """Set environment variables.

    Usage: export VAR=value
    """
    if not args:
        # List all exported variables
        for key, value in sorted(os.environ.items()):
            _print(f"export {key}={value}")
        return 0

    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            os.environ[key] = value
        else:
            # Mark for export (already exported)
            if arg in os.environ:
                pass  # Already in environment
            else:
                os.environ[arg] = ""

    return 0


# ---------------------------------------------------------------------------
# unset - Remove environment variable
# ---------------------------------------------------------------------------

def builtin_unset(args: t.List[str]) -> int:
    """Remove environment variables.

    Usage: unset VAR...
    """
    if not args:
        _eprint("unset: missing variable name")
        return 1

    for arg in args:
        os.environ.pop(arg, None)

    return 0


# ---------------------------------------------------------------------------
# set - Set shell options
# ---------------------------------------------------------------------------

def builtin_set(args: t.List[str]) -> int:
    """Set or display shell options.

    Usage: set [-o option] [VAR=value]
    """
    if not args:
        # Print all shell variables
        for key, value in sorted(os.environ.items()):
            _print(f"{key}={value}")
        return 0

    # Handle options
    if args[0].startswith("-o"):
        if len(args) > 1:
            option = args[1]
            _print(f"set -o {option}: stub")
        return 0

    if args[0].startswith("+"):
        # Unset option
        return 0

    # Handle VAR=value
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            os.environ[key] = value

    return 0


# ---------------------------------------------------------------------------
# type - Display command type
# ---------------------------------------------------------------------------

def builtin_type(args: t.List[str]) -> int:
    """Display command type information.

    Usage: type command...
    """
    if not args:
        _eprint("type: missing operand")
        return 1

    from .builtins import BUILTINS

    exit_code = 0
    for arg in args:
        if arg in BUILTINS:
            _print(f"{arg} is a shell builtin")
        elif find_executable(arg):
            _print(f"{arg} is {find_executable(arg)}")
        elif arg in os.environ:
            _print(f"{arg} is an environment variable")
        else:
            _eprint(f"type: {arg}: not found")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# which - Locate executable
# ---------------------------------------------------------------------------

def builtin_which(args: t.List[str]) -> int:
    """Locate executables in PATH.

    Usage: which command...
    """
    if not args:
        _eprint("which: missing operand")
        return 1

    exit_code = 0
    for arg in args:
        path = find_executable(arg)
        if path:
            _print(path)
        else:
            _eprint(f"which: {arg}: not found")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# ps - Process status
# ---------------------------------------------------------------------------

def builtin_ps(args: t.List[str]) -> int:
    """Display process status.

    Usage: ps [-a] [-u] [-x]
    """
    show_all = False
    user_only = False
    show_extra = False

    for arg in args:
        if arg.startswith("-"):
            for c in arg[1:]:
                if c == "a":
                    show_all = True
                elif c == "u":
                    user_only = True
                elif c == "x":
                    show_extra = True

    processes = list_processes()

    if not show_all:
        # Show only current user's processes
        current_pid = os.getpid()
        processes = [p for p in processes if p["pid"] == current_pid or p["ppid"] == current_pid]

    # Print header
    _print(f"{'PID':>7} {'PPID':>5} {'STATE':>5} {'COMMAND':>20}")

    for p in processes:
        _print(f"{p['pid']:>7} {p['ppid']:>5} {p['state']:>5} {p['comm']:>20}")

    return 0


# ---------------------------------------------------------------------------
# kill - Send signal to process
# ---------------------------------------------------------------------------

def builtin_kill(args: t.List[str]) -> int:
    """Send a signal to a process.

    Usage: kill [-s SIGNAL] pid...
    """
    signal_name = "TERM"
    pids: t.List[int] = []

    i = 0
    while i < len(args):
        if args[i] == "-s" and i + 1 < len(args):
            signal_name = args[i + 1].upper()
            if not signal_name.startswith("SIG"):
                signal_name = "SIG" + signal_name
            i += 2
        elif args[i].startswith("-"):
            sig = args[i][1:].upper()
            if not sig.startswith("SIG"):
                sig = "SIG" + sig
            signal_name = sig
            i += 1
        else:
            try:
                pids.append(int(args[i]))
            except ValueError:
                _eprint(f"kill: invalid PID: {args[i]}")
                return 1
            i += 1

    if not pids:
        _eprint("kill: missing PID")
        return 1

    # Resolve signal
    sig_num = getattr(signal, signal_name, None)
    if sig_num is None:
        # Try by number
        try:
            sig_num = int(signal_name.replace("SIG", ""))
        except ValueError:
            _eprint(f"kill: unknown signal: {signal_name}")
            return 1

    exit_code = 0
    for pid in pids:
        if not kill_process(pid, sig_num):
            _eprint(f"kill: ({pid}) - No such process")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# jobs - Display background jobs
# ---------------------------------------------------------------------------

def builtin_jobs(args: t.List[str]) -> int:
    """Display background jobs.

    Usage: jobs [-l]
    """
    from .executor import get_executor
    executor = get_executor()
    processes = executor.get_background_processes()

    if not processes:
        return 0

    show_long = "-l" in args

    for i, proc in enumerate(processes, 1):
        status = "Running" if proc.running else "Done"
        if show_long:
            _print(f"[{i}] {status} {proc.pid} {proc.command}")
        else:
            _print(f"[{i}] {status} {proc.command}")

    return 0


# ---------------------------------------------------------------------------
# fg - Bring job to foreground
# ---------------------------------------------------------------------------

def builtin_fg(args: t.List[str]) -> int:
    """Bring a background job to the foreground.

    Usage: fg [job_spec]
    """
    from .executor import get_executor
    executor = get_executor()
    processes = executor.get_background_processes()

    if not processes:
        _eprint("fg: no current job")
        return 1

    # Get the most recent process
    proc = processes[-1]
    _print(f"{proc.command}")
    proc.wait()
    return proc.exit_code or 0


# ---------------------------------------------------------------------------
# bg - Resume job in background
# ---------------------------------------------------------------------------

def builtin_bg(args: t.List[str]) -> int:
    """Resume a stopped job in the background.

    Usage: bg [job_spec]
    """
    from .executor import get_executor
    executor = get_executor()
    processes = executor.get_background_processes()

    if not processes:
        _eprint("bg: no current job")
        return 1

    proc = processes[-1]
    _print(f"[{len(processes)}] {proc.command} &")
    return 0


# ---------------------------------------------------------------------------
# exit - Exit the shell
# ---------------------------------------------------------------------------

def builtin_exit(args: t.List[str]) -> int:
    """Exit the shell.

    Usage: exit [code]
    """
    if args:
        try:
            code = int(args[0])
        except ValueError:
            _eprint(f"exit: invalid exit code: {args[0]}")
            code = 1
    else:
        code = 0

    raise SystemExit(code)


# ---------------------------------------------------------------------------
# clear - Clear terminal
# ---------------------------------------------------------------------------

def builtin_clear(args: t.List[str]) -> int:
    """Clear the terminal screen.

    Usage: clear
    """
    # Use ANSI escape codes
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------------------
# help - Display help
# ---------------------------------------------------------------------------

def builtin_help(args: t.List[str]) -> int:
    """Display help information.

    Usage: help [command]
    """
    from .builtins import BUILTINS, BUILTIN_HELP

    if not args:
        _print("Ainos Shell (ainos-sh) - Built-in Commands")
        _print("=" * 50)
        _print()
        for name in sorted(BUILTINS.keys()):
            help_text = BUILTIN_HELP.get(name, "").split("\n")[0] if name in BUILTIN_HELP else ""
            _print(f"  {name:<15} {help_text}")
        _print()
        _print("For more information on a command, type: help <command>")
        return 0

    command = args[0]
    if command in BUILTIN_HELP:
        _print(BUILTIN_HELP[command])
    elif command in BUILTINS:
        _print(f"{command} is a built-in command")
    else:
        _eprint(f"help: no help for '{command}'")
        return 1

    return 0


# ---------------------------------------------------------------------------
# alias - Create/display aliases
# ---------------------------------------------------------------------------

def builtin_alias(args: t.List[str]) -> int:
    """Create or display aliases.

    Usage: alias [name=value...]
    """
    from .config import get_aliases, set_alias

    if not args:
        for name, value in sorted(get_aliases().items()):
            _print(f"alias {name}='{value}'")
        return 0

    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            set_alias(name, value)
            _print(f"alias {name}='{value}'")
        else:
            from .config import get_alias
            value = get_alias(arg)
            if value:
                _print(f"alias {arg}='{value}'")
            else:
                _eprint(f"alias: {arg}: not found")
                return 1

    return 0


# ---------------------------------------------------------------------------
# unalias - Remove aliases
# ---------------------------------------------------------------------------

def builtin_unalias(args: t.List[str]) -> int:
    """Remove aliases.

    Usage: unalias [-a] name...
    """
    remove_all = False
    names = []

    for arg in args:
        if arg == "-a":
            remove_all = True
        elif arg == "--":
            continue
        else:
            names.append(arg)

    if remove_all:
        from .config import get_config
        get_config().aliases.clear()
        return 0

    if not names:
        _eprint("unalias: missing operand")
        return 1

    from .config import unset_alias
    exit_code = 0
    for name in names:
        if not unset_alias(name):
            _eprint(f"unalias: {name}: not found")
            exit_code = 1

    return exit_code


# ---------------------------------------------------------------------------
# source - Execute commands from file
# ---------------------------------------------------------------------------

def builtin_source(args: t.List[str]) -> int:
    """Execute commands from a file.

    Usage: source filename [arguments]
    """
    if not args:
        _eprint("source: missing filename")
        return 1

    path = expanduser(args[0])
    if not file_exists(path):
        _eprint(f"source: {args[0]}: No such file or directory")
        return 1

    try:
        with open(path, "r") as f:
            content = f.read()
        # Execute the content - this will be handled by the shell
        # For now, store the content for later execution
        from .main import get_shell
        shell = get_shell()
        if shell:
            shell.execute_source(content)
            return 0
        return 0
    except Exception as e:
        _eprint(f"source: error sourcing {args[0]}: {e}")
        return 1


# ---------------------------------------------------------------------------
# history - Display history
# ---------------------------------------------------------------------------

def builtin_history(args: t.List[str]) -> int:
    """Display command history.

    Usage: history [-c] [-d N] [n]
    """
    from .history import get_history_manager
    history = get_history_manager()

    if not args:
        entries = history.get(limit=50)
        for entry in entries:
            _print(f"  {entry.id:>5}  {entry.command}")
        return 0

    if args[0] == "-c":
        history.clear()
        _print("History cleared")
        return 0

    if args[0] == "-d" and len(args) > 1:
        try:
            entry_id = int(args[1])
            if history.delete(entry_id):
                _print(f"Deleted entry {entry_id}")
            else:
                _eprint(f"history: entry {entry_id} not found")
                return 1
        except ValueError:
            _eprint(f"history: invalid entry ID: {args[1]}")
            return 1
        return 0

    if args[0] == "-n":
        # Read from history file, not just current session
        return 0

    if args[0].isdigit():
        n = int(args[0])
        entries = history.get(limit=n)
        for entry in entries:
            _print(f"  {entry.id:>5}  {entry.command}")
        return 0

    return 0


# ---------------------------------------------------------------------------
# date - Display date/time
# ---------------------------------------------------------------------------

def builtin_date(args: t.List[str]) -> int:
    """Display the current date and time.

    Usage: date
    """
    now = datetime.now()
    _print(now.strftime("%a %b %d %H:%M:%S %Z %Y"))
    return 0


# ---------------------------------------------------------------------------
# sleep - Delay execution
# ---------------------------------------------------------------------------

def builtin_sleep(args: t.List[str]) -> int:
    """Delay for a specified number of seconds.

    Usage: sleep seconds
    """
    if not args:
        _eprint("sleep: missing operand")
        return 1

    try:
        seconds = float(args[0])
        time.sleep(seconds)
        return 0
    except ValueError:
        _eprint(f"sleep: invalid time interval '{args[0]}'")
        return 1
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------------
# yes - Output repeated text
# ---------------------------------------------------------------------------

def builtin_yes(args: t.List[str]) -> int:
    """Repeatedly output a string.

    Usage: yes [text]
    """
    text = args[0] if args else "y"
    try:
        while True:
            _print(text)
    except KeyboardInterrupt:
        return 0


# ---------------------------------------------------------------------------
# true / false
# ---------------------------------------------------------------------------

def builtin_true(args: t.List[str]) -> int:
    """Return true (exit code 0)."""
    return 0


def builtin_false(args: t.List[str]) -> int:
    """Return false (exit code 1)."""
    return 1


# ---------------------------------------------------------------------------
# hostname - Display system hostname
# ---------------------------------------------------------------------------

def builtin_hostname(args: t.List[str]) -> int:
    """Display the system's hostname.

    Usage: hostname
    """
    try:
        import socket
        _print(socket.gethostname())
        return 0
    except Exception as e:
        _eprint(f"hostname: {e}")
        return 1


# ---------------------------------------------------------------------------
# uname - Display system information
# ---------------------------------------------------------------------------

def builtin_uname(args: t.List[str]) -> int:
    """Display system information.

    Usage: uname [-a] [-s] [-n] [-r] [-m]
    """
    all_info = False
    show_kernel = False
    show_node = False
    show_release = False
    show_machine = False

    if not args:
        show_kernel = True
    else:
        for arg in args:
            if arg.startswith("-"):
                for c in arg[1:]:
                    if c == "a":
                        all_info = True
                    elif c == "s":
                        show_kernel = True
                    elif c == "n":
                        show_node = True
                    elif c == "r":
                        show_release = True
                    elif c == "m":
                        show_machine = True

    if all_info:
        show_kernel = show_node = show_release = show_machine = True

    import platform
    parts = []
    if show_kernel:
        parts.append(platform.system())
    if show_node:
        parts.append(platform.node())
    if show_release:
        parts.append(platform.release())
    if show_machine:
        parts.append(platform.machine())

    _print(" ".join(parts))
    return 0


# ---------------------------------------------------------------------------
# whoami - Display current user
# ---------------------------------------------------------------------------

def builtin_whoami(args: t.List[str]) -> int:
    """Display the current user name.

    Usage: whoami
    """
    try:
        import getpass
        _print(getpass.getuser())
        return 0
    except Exception as e:
        _eprint(f"whoami: {e}")
        return 1


# ---------------------------------------------------------------------------
# id - Display user identity
# ---------------------------------------------------------------------------

def builtin_id(args: t.List[str]) -> int:
    """Display user and group information.

    Usage: id [user]
    """
    try:
        import os
        _print(f"uid={os.getuid()} gid={os.getgid()}")
        if IS_POSIX:
            groups = os.getgroups()
            if groups:
                _print(f"groups={','.join(str(g) for g in groups)}")
        return 0
    except Exception as e:
        _eprint(f"id: {e}")
        return 1


# ---------------------------------------------------------------------------
# uptime - System uptime
# ---------------------------------------------------------------------------

def builtin_uptime(args: t.List[str]) -> int:
    """Display system uptime.

    Usage: uptime
    """
    if IS_POSIX:
        try:
            with open("/proc/uptime", "r") as f:
                uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            parts = []
            if days > 0:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            parts.append(f"{hours:02d}:{minutes:02d}")
            _print(f"up {' '.join(parts)}")
            return 0
        except (FileNotFoundError, IndexError, ValueError):
            pass

    # Fallback
    import datetime
    import psutil  # May not be available
    try:
        uptime_seconds = time.time() - psutil.boot_time()
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        _print(f"up {days} days, {hours:02d}:{minutes:02d}")
        return 0
    except ImportError:
        _print("uptime: not available")
        return 1


# ---------------------------------------------------------------------------
# cal - Calendar
# ---------------------------------------------------------------------------

def builtin_cal(args: t.List[str]) -> int:
    """Display a calendar.

    Usage: cal [month] [year]
    """
    import calendar

    now = datetime.now()
    month = now.month
    year = now.year

    if len(args) >= 1:
        try:
            month = int(args[0])
        except ValueError:
            year = int(args[0])
            month = now.month

    if len(args) >= 2:
        try:
            month = int(args[0])
            year = int(args[1])
        except ValueError:
            pass

    if month < 1 or month > 12:
        _eprint("cal: invalid month")
        return 1

    cal_text = calendar.month(year, month)
    _print(cal_text.rstrip())
    return 0


# ---------------------------------------------------------------------------
# df - Disk free
# ---------------------------------------------------------------------------

def builtin_df(args: t.List[str]) -> int:
    """Display disk free space.

    Usage: df [-h] [path...]
    """
    human = False
    paths = []

    for arg in args:
        if arg == "-h":
            human = True
        elif arg.startswith("-"):
            for c in arg[1:]:
                if c == "h":
                    human = True
        else:
            paths.append(arg)

    if not paths:
        paths = ["/"] if IS_POSIX else ["C:\\"]

    import shutil

    _print(f"{'Filesystem':<20} {'Size':>8} {'Used':>8} {'Avail':>8} {'Use%':>6} {'Mounted':<20}")

    for path in paths:
        try:
            usage = shutil.disk_usage(expanduser(path))
            total = human_readable_size(usage.total) if human else str(usage.total)
            used = human_readable_size(usage.used) if human else str(usage.used)
            free = human_readable_size(usage.free) if human else str(usage.free)
            pct = f"{usage.used / usage.total * 100:.0f}%"
            _print(f"{'<filesystem>':<20} {total:>8} {used:>8} {free:>8} {pct:>6} {path:<20}")
        except PermissionError:
            _eprint(f"df: {path}: Permission denied")
        except FileNotFoundError:
            _eprint(f"df: {path}: No such file or directory")

    return 0


# ---------------------------------------------------------------------------
# du - Disk usage
# ---------------------------------------------------------------------------

def builtin_du(args: t.List[str]) -> int:
    """Display disk usage of files and directories.

    Usage: du [-sh] [path...]
    """
    summarize = False
    human = False
    paths = []

    for arg in args:
        if arg == "-s":
            summarize = True
        elif arg == "-h":
            human = True
        elif arg == "-sh" or arg == "-hs":
            summarize = True
            human = True
        elif arg.startswith("-"):
            for c in arg[1:]:
                if c == "s":
                    summarize = True
                elif c == "h":
                    human = True
        else:
            paths.append(arg)

    if not paths:
        paths = ["."]

    def _get_size(path: str) -> int:
        total = 0
        try:
            if os.path.isfile(path):
                return os.path.getsize(path)
            for root, dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except (PermissionError, FileNotFoundError):
            pass
        return total

    for path in paths:
        full = expanduser(path)
        if summarize:
            size = _get_size(full)
            size_str = human_readable_size(size) if human else str(size)
            _print(f"{size_str:>8} {path}")
        else:
            walk = []
            if os.path.isfile(full):
                size = os.path.getsize(full)
                size_str = human_readable_size(size) if human else str(size)
                _print(f"{size_str:>8} {path}")
            else:
                for root, dirs, files in os.walk(full):
                    dir_size = _get_size(root)
                    size_str = human_readable_size(dir_size) if human else str(dir_size)
                    _print(f"{size_str:>8} {root}")

    return 0


# ---------------------------------------------------------------------------
# free - Display memory usage
# ---------------------------------------------------------------------------

def builtin_free(args: t.List[str]) -> int:
    """Display memory usage.

    Usage: free [-h]
    """
    human = False
    for arg in args:
        if arg == "-h":
            human = True

    if IS_POSIX:
        try:
            with open("/proc/meminfo", "r") as f:
                meminfo = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip().split()[0]
                        try:
                            meminfo[key] = int(value) * 1024  # Convert kB to bytes
                        except ValueError:
                            meminfo[key] = 0
            total = meminfo.get("MemTotal", 0)
            free_mem = meminfo.get("MemFree", 0)
            available = meminfo.get("MemAvailable", 0)
            used = total - free_mem
            swap_total = meminfo.get("SwapTotal", 0)
            swap_free = meminfo.get("SwapFree", 0)
            swap_used = swap_total - swap_free

            if human:
                _print(f"{'':>8} {'total':>6} {'used':>6} {'free':>6} {'shared':>6} {'buff/cache':>10} {'available':>10}")
                _print(f"{'Mem:':>8} {human_readable_size(total):>6} {human_readable_size(used):>6} {human_readable_size(free_mem):>6} {'0B':>6} {human_readable_size(meminfo.get('Buffers', 0) + meminfo.get('Cached', 0)):>10} {human_readable_size(available):>10}")
                _print(f"{'Swap:':>8} {human_readable_size(swap_total):>6} {human_readable_size(swap_used):>6} {human_readable_size(swap_free):>6}")
            else:
                _print(f"{'':>8} {'total':>10} {'used':>10} {'free':>10} {'shared':>10} {'buff/cache':>10} {'available':>10}")
                _print(f"{'Mem:':>8} {total:>10} {used:>10} {free_mem:>10} {'0':>10} {meminfo.get('Buffers', 0) + meminfo.get('Cached', 0):>10} {available:>10}")
                _print(f"{'Swap:':>8} {swap_total:>10} {swap_used:>10} {swap_free:>10}")
            return 0
        except FileNotFoundError:
            pass

    _print("free: not available on this platform")
    return 1


# ---------------------------------------------------------------------------
# lsof - List open files (stub)
# ---------------------------------------------------------------------------

def builtin_lsof(args: t.List[str]) -> int:
    """List open files (stub, requires external lsof).

    Usage: lsof
    """
    try:
        result = subprocess.run(["lsof"] + args, capture_output=True, text=True)
        _print(result.stdout)
        if result.stderr:
            _eprint(result.stderr, end="")
        return result.returncode
    except FileNotFoundError:
        _eprint("lsof: command not found")
        return 127


# ---------------------------------------------------------------------------
# find - Find files
# ---------------------------------------------------------------------------

def builtin_find(args: t.List[str]) -> int:
    """Find files matching criteria.

    Usage: find [path] [-name pattern] [-type f|d] [-size N]
    """
    path = "."
    name_pattern = None
    file_type = None
    min_size = None
    max_size = None

    i = 0
    while i < len(args):
        if args[i] == "-name" and i + 1 < len(args):
            name_pattern = args[i + 1]
            i += 2
        elif args[i] == "-type" and i + 1 < len(args):
            file_type = args[i + 1]
            i += 2
        elif args[i] == "-size" and i + 1 < len(args):
            size_str = args[i + 1]
            if size_str.endswith("k"):
                min_size = float(size_str[:-1]) * 1024 if not size_str.startswith("-") else None
                max_size = float(size_str[1:-1]) * 1024 if size_str.startswith("-") else None
            elif size_str.endswith("M"):
                min_size = float(size_str[:-1]) * 1024 * 1024 if not size_str.startswith("-") else None
                max_size = float(size_str[1:-1]) * 1024 * 1024 if size_str.startswith("-") else None
            i += 2
        elif not args[i].startswith("-") and i == 0:
            path = args[i]
            i += 1
        else:
            i += 1

    import fnmatch

    path = expanduser(path)
    matches = []

    for root, dirs, files in os.walk(path):
        items = files if file_type != "d" else dirs
        if file_type is None:
            items = files + dirs

        for item in items:
            full = os.path.join(root, item)
            rel = os.path.relpath(full, os.getcwd())

            if name_pattern and not fnmatch.fnmatch(item, name_pattern):
                continue

            if min_size is not None:
                try:
                    if os.path.getsize(full) < min_size:
                        continue
                except OSError:
                    continue

            if max_size is not None:
                try:
                    if os.path.getsize(full) > max_size:
                        continue
                except OSError:
                    continue

            _print(rel)

    return 0


# ---------------------------------------------------------------------------
# which - Alias for find_executable
# ---------------------------------------------------------------------------

# Already defined above


# ---------------------------------------------------------------------------
# Built-in command registry
# ---------------------------------------------------------------------------

BUILTINS: t.Dict[str, BuiltinFunc] = {
    "cd": builtin_cd,
    "ls": builtin_ls,
    "pwd": builtin_pwd,
    "echo": builtin_echo,
    "cat": builtin_cat,
    "mkdir": builtin_mkdir,
    "rmdir": builtin_rmdir,
    "rm": builtin_rm,
    "cp": builtin_cp,
    "mv": builtin_mv,
    "touch": builtin_touch,
    "head": builtin_head,
    "tail": builtin_tail,
    "wc": builtin_wc,
    "grep": builtin_grep,
    "sort": builtin_sort,
    "uniq": builtin_uniq,
    "env": builtin_env,
    "export": builtin_export,
    "unset": builtin_unset,
    "set": builtin_set,
    "type": builtin_type,
    "which": builtin_which,
    "ps": builtin_ps,
    "kill": builtin_kill,
    "jobs": builtin_jobs,
    "fg": builtin_fg,
    "bg": builtin_bg,
    "exit": builtin_exit,
    "clear": builtin_clear,
    "help": builtin_help,
    "alias": builtin_alias,
    "unalias": builtin_unalias,
    "source": builtin_source,
    "history": builtin_history,
    "date": builtin_date,
    "sleep": builtin_sleep,
    "yes": builtin_yes,
    "true": builtin_true,
    "false": builtin_false,
    "hostname": builtin_hostname,
    "uname": builtin_uname,
    "whoami": builtin_whoami,
    "id": builtin_id,
    "uptime": builtin_uptime,
    "cal": builtin_cal,
    "df": builtin_df,
    "du": builtin_du,
    "free": builtin_free,
    "lsof": builtin_lsof,
    "find": builtin_find,
}

# ---------------------------------------------------------------------------
# Built-in command help texts
# ---------------------------------------------------------------------------

BUILTIN_HELP: t.Dict[str, str] = {
    "cd": """cd: cd [directory]
    Change the current working directory.
    If no directory is given, change to HOME.
    Use '-' to go to the previous directory.""",

    "ls": """ls: ls [-la] [path...]
    List directory contents.
    Options:
      -a  Show all files (including hidden)
      -l  Long format
      -h  Human-readable sizes
      -R  Recursive""",

    "pwd": """pwd: pwd
    Print the current working directory.""",

    "echo": """echo: echo [-n] [text...]
    Print arguments to stdout.
    Options:
      -n  Do not output trailing newline""",

    "cat": """cat: cat [file...]
    Concatenate files and print to stdout.
    If no file, read from stdin.""",

    "mkdir": """mkdir: mkdir [-p] directory...
    Create directories.
    Options:
      -p  Create parent directories as needed""",

    "rm": """rm: rm [-rf] path...
    Remove files or directories.
    Options:
      -r  Remove directories recursively
      -f  Force removal (ignore errors)""",

    "cp": """cp: cp [-r] source... destination
    Copy files or directories.
    Options:
      -r  Copy directories recursively""",

    "mv": """mv: mv source... destination
    Move/rename files or directories.""",

    "grep": """grep: grep [-i] [-n] pattern [file...]
    Search for patterns in text.
    Options:
      -i  Ignore case
      -n  Show line numbers
      -r  Recursive
      -c  Count matches only
      -v  Invert match""",

    "ps": """ps: ps [-a] [-u] [-x]
    Display process status.""",

    "kill": """kill: kill [-s SIGNAL] pid...
    Send a signal to a process.
    Signals: TERM, KILL, INT, HUP, etc.""",

    "exit": """exit: exit [code]
    Exit the shell with the given exit code.""",

    "clear": """clear: clear
    Clear the terminal screen.""",

    "help": """help: help [command]
    Display help information about built-in commands.""",

    "alias": """alias: alias [name=value...]
    Create or display aliases.""",

    "unalias": """unalias: unalias [-a] name...
    Remove aliases.
    Options:
      -a  Remove all aliases""",

    "source": """source: source filename [arguments]
    Execute commands from a file in the current shell.""",

    "history": """history: history [-c] [-d N] [n]
    Display command history.
    Options:
      -c  Clear history
      -d N  Delete entry N""",

    "env": """env: env [VAR=value] [command]
    Display environment variables or run a command with modified environment.""",

    "export": """export: export VAR=value
    Set environment variables.""",

    "unset": """unset: unset VAR...
    Remove environment variables.""",

    "which": """which: which command...
    Locate executables in PATH.""",

    "type": """type: type command...
    Display command type information (builtin, external, etc.).""",

    "date": """date: date
    Display the current date and time.""",

    "sleep": """sleep: sleep seconds
    Delay for a specified number of seconds.""",

    "true": """true: true
    Return a successful exit code (0).""",

    "false": """false: false
    Return a failure exit code (1).""",

    "hostname": """hostname: hostname
    Display the system's hostname.""",

    "uname": """uname: uname [-a] [-s] [-n] [-r] [-m]
    Display system information.""",

    "whoami": """whoami: whoami
    Display the current user name.""",

    "id": """id: id [user]
    Display user and group information.""",

    "uptime": """uptime: uptime
    Display system uptime.""",

    "cal": """cal: cal [month] [year]
    Display a calendar.""",

    "df": """df: df [-h] [path...]
    Display disk free space.""",

    "du": """du: du [-sh] [path...]
    Display disk usage.""",

    "free": """free: free [-h]
    Display memory usage.""",

    "find": """find: find [path] [-name pattern] [-type f|d] [-size N]
    Find files matching criteria.""",

    "wc": """wc: wc [-lwc] [file...]
    Count lines, words, and characters.""",

    "sort": """sort: sort [-r] [-n] [file...]
    Sort lines of text.""",

    "uniq": """uniq: uniq [-c] [file]
    Filter adjacent duplicate lines.""",

    "touch": """touch: touch file...
    Create empty files or update timestamps.""",

    "head": """head: head [-n lines] [file]
    Display the first lines of a file.""",

    "tail": """tail: tail [-n lines] [file]
    Display the last lines of a file.""",

    "jobs": """jobs: jobs [-l]
    Display background jobs.""",

    "fg": """fg: fg [job_spec]
    Bring a background job to the foreground.""",

    "bg": """bg: bg [job_spec]
    Resume a stopped job in the background.""",

    "rmdir": """rmdir: rmdir directory...
    Remove empty directories.""",

    "yes": """yes: yes [text]
    Repeatedly output a string.""",

    "set": """set: set [-o option] [VAR=value]
    Set or display shell options and variables.
    Without arguments, displays all shell variables.
    Use -o option to set a shell option.""",
}


__all__ = [
    "BUILTINS",
    "BUILTIN_HELP",
    "BuiltinFunc",
]