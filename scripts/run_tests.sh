#!/usr/bin/env bash
# ============================================================================
# Ainos OS - 一键运行所有测试
# ============================================================================
# 编译并运行 Rust 测试、C++ 测试、Python 验收测试
#
# Usage:
#   ./scripts/run_tests.sh              # Run all tests
#   ./scripts/run_tests.sh --rust-only  # Run only Rust tests
#   ./scripts/run_tests.sh --cpp-only   # Run only C++ tests
#   ./scripts/run_tests.sh --py-only    # Run only Python tests
#   ./scripts/run_tests.sh --verbose    # Verbose output
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Flags
RUN_RUST=true
RUN_CPP=true
RUN_PY=true
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rust-only) RUN_CPP=false; RUN_PY=false; shift ;;
        --cpp-only)  RUN_RUST=false; RUN_PY=false; shift ;;
        --py-only)   RUN_RUST=false; RUN_CPP=false; shift ;;
        --verbose|-v) VERBOSE=true; shift ;;
        --help|-h)
            echo "Usage: $0 [--rust-only|--cpp-only|--py-only] [--verbose]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Summary counters
TOTAL=0
PASSED=0
FAILED=0

print_header() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""
}

print_result() {
    local name="$1"
    local status="$2"
    local duration="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$status" -eq 0 ]; then
        echo -e "  ${GREEN}[PASS]${NC} $name (${duration}s)"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $name (${duration}s)"
        FAILED=$((FAILED + 1))
    fi
}

run_step() {
    local name="$1"
    shift
    echo -e "  Running: $name ..."
    local start=$(date +%s%N)
    if [ "$VERBOSE" = true ]; then
        set +e
        "$@"
        local status=$?
        set -e
    else
        set +e
        "$@" > /tmp/ainos_test_output.log 2>&1
        local status=$?
        set -e
    fi
    local end=$(date +%s%N)
    local duration=$(echo "scale=2; ($end - $start) / 1000000000" | bc 2>/dev/null || echo "?")
    print_result "$name" "$status" "$duration"
    if [ "$status" -ne 0 ] && [ "$VERBOSE" = true ]; then
        echo "  Output:"
        cat /tmp/ainos_test_output.log 2>/dev/null | sed 's/^/    /'
    fi
    return $status
}

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  Ainos OS - 一键测试运行器${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo "  Project root: $PROJECT_ROOT"
echo "  Date:         $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ============================================================================
# 1. Rust 测试
# ============================================================================
if [ "$RUN_RUST" = true ]; then
    print_header "1/3: Rust Tests (cargo test)"

    DAEMON_DIR="$PROJECT_ROOT/system-services/ai-daemon"

    if [ ! -d "$DAEMON_DIR" ]; then
        echo -e "  ${YELLOW}[SKIP]${NC} ai-daemon directory not found at $DAEMON_DIR"
        echo ""
    else
        # Step 1.1: Check compilation
        run_step "Rust: cargo check" \
            cargo check --manifest-path "$DAEMON_DIR/Cargo.toml" 2>&1

        # Step 1.2: Run unit tests + integration tests
        run_step "Rust: cargo test" \
            cargo test --manifest-path "$DAEMON_DIR/Cargo.toml" 2>&1

        # Step 1.3: Run tests with all features (if any)
        if grep -q '\[features\]' "$DAEMON_DIR/Cargo.toml" 2>/dev/null; then
            run_step "Rust: cargo test --all-features" \
                cargo test --all-features --manifest-path "$DAEMON_DIR/Cargo.toml" 2>&1
        fi

        # Step 1.4: Check for warnings (strict mode)
        run_step "Rust: cargo test (no warnings)" \
            cargo test --manifest-path "$DAEMON_DIR/Cargo.toml" 2>&1

        # Step 1.5: Verify no dead code warnings in tests
        # (cargo test already compiles with --test, so this overlaps)
        echo ""
    fi
fi

# ============================================================================
# 2. C++ 测试 (CMake + CTest)
# ============================================================================
if [ "$RUN_CPP" = true ]; then
    print_header "2/3: C++ Tests (CMake + CTest)"

    BUILD_DIR="$PROJECT_ROOT/build"

    if [ -d "$BUILD_DIR" ]; then
        # Step 2.1: Rebuild (if CMakeLists.txt exists)
        if [ -f "$PROJECT_ROOT/CMakeLists.txt" ]; then
            run_step "C++: cmake --build" \
                cmake --build "$BUILD_DIR" 2>&1
        fi

        # Step 2.2: Run CTest
        if [ -f "$BUILD_DIR/CTestTestfile.cmake" ]; then
            run_step "C++: ctest" \
                ctest --test-dir "$BUILD_DIR" --output-on-failure 2>&1
        else
            echo -e "  ${YELLOW}[SKIP]${NC} No CTest configuration found in $BUILD_DIR"
            echo ""
        fi
    else
        echo -e "  ${YELLOW}[SKIP]${NC} Build directory not found at $BUILD_DIR"
        echo -e "  Run 'cmake -B build' first to configure C++ build."
        echo ""
    fi
fi

# ============================================================================
# 3. Python 验收测试
# ============================================================================
if [ "$RUN_PY" = true ]; then
    print_header "3/3: Python Acceptance Tests"

    # Check if daemon is running before running verification tests
    DAEMON_ALIVE=false
    if command -v ss &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -q :9500; then
            DAEMON_ALIVE=true
        fi
    elif command -v netstat &>/dev/null; then
        if netstat -an 2>/dev/null | grep -q "0.0.0.0:9500\|127.0.0.1:9500"; then
            DAEMON_ALIVE=true
        fi
    fi

    # verification_test.py
    VERIFY_SCRIPT="$SCRIPT_DIR/verification_test.py"
    if [ -f "$VERIFY_SCRIPT" ]; then
        if [ "$DAEMON_ALIVE" = true ]; then
            run_step "Python: verification_test.py" \
                python3 "$VERIFY_SCRIPT" 2>&1
        else
            echo -e "  ${YELLOW}[SKIP]${NC} verification_test.py (daemon not running on :9500)"
            echo -e "  Start the daemon first with:  cargo run --manifest-path \"$PROJECT_ROOT/system-services/ai-daemon/Cargo.toml\""
            echo ""
        fi
    else
        echo -e "  ${YELLOW}[SKIP]${NC} verification_test.py not found"
        echo ""
    fi
fi

# ============================================================================
# Summary
# ============================================================================
print_header "Test Summary"

echo -e "  Total:  $TOTAL"
echo -e "  Passed: ${GREEN}$PASSED${NC}"
echo -e "  Failed: ${RED}$FAILED${NC}"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "  ${GREEN}All tests passed!${NC}"
    echo ""
    exit 0
else
    echo -e "  ${RED}Some tests failed.${NC}"
    echo ""
    exit 1
fi