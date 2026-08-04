# Ainos i18n - Internationalization Framework

A comprehensive internationalization (i18n) and localization (l10n) framework for the AinosOS ecosystem.

## Features

- **Translation Engine** - Key-value and ICU message format translation with nested key resolution
- **Locale Management** - Auto-detection, manual setting, locale stack, Accept-Language header parsing
- **CLDR Plural Rules** - Support for 6 plural categories (zero, one, two, few, many, other) across 10+ languages
- **Locale-Aware Formatting** - Dates, times, numbers, currencies, and percentages per locale
- **Context-Aware Translation** - Disambiguate translations based on usage context
- **Configurable Fallback** - Multiple strategies (key chain, locale chain, combined)
- **Multiple Loaders** - JSON, YAML, GNU gettext (.mo/.po), and database backends
- **10 Languages** - zh_CN, en_US, ja_JP, ko_KR, fr_FR, de_DE, es_ES, ru_RU, ar_SA, pt_BR
- **Developer Tools** - Extract, compile, validate, and sync translations
- **Framework Integration** - Shell, Desktop GUI, Web Panel, and CLI components

## Quick Start

```python
from ainos_i18n import AinosI18n

# Create the i18n instance
i18n = AinosI18n()

# Set locale manually
i18n.set_locale("zh_CN")

# Or auto-detect from system
i18n.detect_locale()

# Basic translation
print(i18n.t("welcome"))  # "欢迎使用 Ainos 系统"

# Translation with interpolation
print(i18n.t("errors.not_found", resource="file.txt"))  # "未找到: file.txt"

# Pluralization
print(i18n.n("items", 1))  # "1 个项目"
print(i18n.n("items", 5))  # "5 个项目"

# Date formatting
print(i18n.format_date("2026-08-04"))  # "2026年8月4日"

# Number formatting
print(i18n.format_number(1234567.89))  # "1,234,567.89"

# Currency formatting
print(i18n.format_currency(1234.56, "USD"))  # "$1,234.56"

# Context-aware translation
print(i18n.t("run", context="verb"))  # "跑步" (or locale-specific)

# Check if key exists
if i18n.exists("welcome"):
    print("Key exists!")

# List available locales
print(i18n.list_locales())
```

## Architecture

```
ainos_i18n/
├── __init__.py            # AinosI18n facade
├── core/
│   ├── translator.py      # Translation engine
│   ├── locale.py          # Locale management
│   ├── plural.py          # CLDR plural rules
│   ├── format.py          # Date/time/number/currency formatting
│   ├── context.py         # Context-aware translation
│   └── fallback.py        # Fallback strategies
├── loaders/
│   ├── base.py            # Loader abstract base
│   ├── json.py            # JSON file loader
│   ├── yaml.py            # YAML file loader
│   ├── gettext.py         # GNU gettext loader (.mo/.po)
│   └── database.py        # Database loader
├── locales/               # 10 language translation files
│   ├── zh_CN/
│   ├── en_US/
│   ├── ja_JP/
│   ├── ko_KR/
│   ├── fr_FR/
│   ├── de_DE/
│   ├── es_ES/
│   ├── ru_RU/
│   ├── ar_SA/
│   └── pt_BR/
├── tools/
│   ├── extract.py         # Translation string extraction
│   ├── compile.py         # Translation compilation
│   ├── validate.py        # Translation validation
│   └── sync.py            # Translation synchronization
├── ainos_integration/
│   ├── shell.py           # AI Shell integration
│   ├── desktop.py         # Desktop GUI integration
│   ├── web.py             # Web Panel integration
│   └── cli.py             # CLI tools integration
├── tests/
│   ├── test_translator.py
│   ├── test_locale.py
│   ├── test_format.py
│   └── test_plural.py
├── setup.py
└── pyproject.toml
```

## Supported Locales

| Locale   | Language         | Region          | Direction | Plural Forms               |
| -------- | ---------------- | --------------- | --------- | -------------------------- |
| zh_CN    | Chinese          | China           | LTR       | other                      |
| en_US    | English          | United States   | LTR       | one, other                 |
| ja_JP    | Japanese         | Japan           | LTR       | other                      |
| ko_KR    | Korean           | South Korea     | LTR       | other                      |
| fr_FR    | French           | France          | LTR       | one, other (0 treated as singular) |
| de_DE    | German           | Germany         | LTR       | one, other                 |
| es_ES    | Spanish          | Spain           | LTR       | one, other                 |
| ru_RU    | Russian          | Russia          | LTR       | one, few, many, other      |
| ar_SA    | Arabic           | Saudi Arabia    | RTL       | zero, one, two, few, many, other |
| pt_BR    | Portuguese       | Brazil          | LTR       | one, other                 |

## Installation

```bash
# Install from source
pip install -e .

# With YAML support
pip install -e ".[yaml]"

# With development tools
pip install -e ".[dev]"
```

## CLI Tools

```bash
# Extract translatable strings from source code
ainos-i18n-extract --source-dir ./src --output translations.json

# Compile translation files
ainos-i18n-compile --source-dir ./locales --output-dir ./compiled

# Validate translations
ainos-i18n-validate --locales-dir ./locales

# Synchronize translations
ainos-i18n-sync --locales-dir ./locales --reference en_US
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=ainos_i18n --cov-report=html

# Run specific test file
pytest tests/test_translator.py -v
```

## License

MIT License

## Author

AinosOS Internationalization Team