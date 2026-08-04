# Ainos Shell (ainos-sh)

An AI-powered shell for developers, built with Python.

## Features

- **Complete REPL** with command history, tab completion, and syntax highlighting
- **Built-in Commands**: cd, ls, pwd, echo, cat, grep, find, ps, kill, and 40+ more
- **Pipelines & Redirection**: Full support for `|`, `>`, `<`, `>>`, `2>&1`, `&>`
- **AI Integration**: Natural language to command, error explanation, smart suggestions
- **Plugin System**: Extensible with Git, Docker, and AinosOS plugins
- **Theme System**: Customizable prompts with Powerline, Fish, Starship styles
- **SQLite History**: Persistent, searchable, with full-text search
- **Tab Completion**: Commands, files, arguments, environment variables, AI-powered
- **Cross-Platform**: Windows, macOS, Linux

## Quick Start

```bash
# Install
pip install ainos-sh

# Or install with AI support
pip install ainos-sh[ai]

# Run
ainos-sh
```

## AI Features

```bash
# Natural language to command
? list all Python files in current directory

# Explain a command
? explain: ls -la | grep "^d"

# Get AI suggestions
? suggest a git command to undo last commit

# AI-powered error explanation
$ unknown_command
# AI automatically explains the error and suggests fixes
```

## Configuration

Configuration file: `~/.ainoshrc` or `~/.config/ainos/ainos.conf`

```ini
[theme]
name = powerline
show_git = true
show_ai = true

[ai]
provider = openai
model = gpt-4o
api_key = your-key-here

[history]
size = 10000
dedup = true
```

## Built-in Commands

File operations: `cd`, `ls`, `pwd`, `echo`, `cat`, `mkdir`, `rmdir`, `rm`, `cp`, `mv`, `touch`, `head`, `tail`, `wc`
Text processing: `grep`, `sort`, `uniq`
Process management: `ps`, `kill`, `jobs`, `fg`, `bg`
Shell: `exit`, `help`, `source`, `alias`, `unalias`, `set`, `unset`, `export`, `type`, `which`
System: `date`, `sleep`, `yes`, `true`, `false`, `hostname`, `uname`, `whoami`, `id`, `uptime`, `cal`, `df`, `du`, `free`, `find`

## Plugins

- **Git**: Status in prompt, command shortcuts (`gs`, `ga`, `gc`, `gp`, etc.)
- **Docker**: Container management, shortcuts (`dps`, `dlogs`, `dcup`, etc.)
- **AinosOS**: Model management and inference

## Development

```bash
# Clone
git clone https://github.com/ainos/ainos-sh.git
cd ainos-sh

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src

# Format code
black src/ tests/ plugins/

# Type check
mypy src/
```

## Project Structure

```
ainos-sh/
├── src/
│   ├── main.py          # Entry point + REPL
│   ├── shell.py         # Shell core
│   ├── parser.py        # Command parser
│   ├── executor.py      # Command executor
│   ├── builtins.py      # Built-in commands
│   ├── commands.py      # Command dispatch
│   ├── prompt.py        # Prompt rendering
│   ├── completer.py     # Tab completion
│   ├── history.py       # SQLite history
│   ├── config.py        # Configuration
│   ├── themes.py        # Theme system
│   ├── ai_assist.py     # AI assistant
│   ├── ai_commands.py   # AI commands
│   ├── completion.py    # AI completion
│   ├── plugins.py       # Plugin system
│   └── utils.py         # Utilities
├── plugins/
│   ├── git_plugin.py    # Git integration
│   ├── docker_plugin.py # Docker integration
│   └── ainos_plugin.py  # AinosOS integration
├── tests/
│   ├── test_shell.py
│   ├── test_parser.py
│   ├── test_commands.py
│   └── test_ai_assist.py
├── setup.py
├── pyproject.toml
└── README.md
```

## License

MIT License

Copyright (c) 2026 Ainos Team