# AinosOS 开发指南

## 概述

本文档指导开发者如何设置 AinosOS 开发环境、遵循代码风格规范、编写测试以及使用 CI/CD 流程。

## 开发环境设置

### 必备工具

| 工具 | 版本 | 用途 |
|------|------|------|
| Git | >= 2.30 | 版本控制 |
| CMake | >= 3.22 | 构建系统 |
| C 编译器 | GCC >= 11 / Clang >= 14 / MSVC 2022 | 编译 |
| Python | >= 3.10 | 构建脚本和测试 |
| Ninja | >= 1.10 | 构建加速 |
| clang-format | >= 14 | 代码格式化 |
| clang-tidy | >= 14 | 静态分析 |
| cppcheck | >= 2.8 | 静态分析 |
| valgrind | >= 3.19 | 内存检查 |
| gdb / lldb | - | 调试器 |

### 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/ainos/ainos.git
cd ainos

# 2. 安装依赖
# Linux (Ubuntu/Debian)
sudo apt-get install -y \
    build-essential cmake ninja-build python3 python3-pip \
    libssl-dev libcurl4-openssl-dev pkg-config \
    clang-format clang-tidy cppcheck valgrind lldb

# 3. 安装 pre-commit 钩子
pip install pre-commit
pre-commit install

# 4. 创建开发构建
mkdir build && cd build
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DAINOS_TESTS=ON \
    -DAINOS_SANITIZER=ON \
    -DAINOS_COVERAGE=ON

# 5. 编译
ninja -j$(nproc)

# 6. 运行测试
ctest --output-on-failure
```

### 编辑器配置

#### VS Code 配置

```json
{
    "recommendations": [
        "ms-vscode.cpptools",
        "ms-vscode.cmake-tools",
        "twxs.cmake",
        "xaver.clang-format",
        "cschlosser.doxdocgen",
        "ms-python.python",
        "yzhang.markdown-all-in-one"
    ]
}
```

#### VS Code settings.json

```json
{
    "editor.formatOnSave": true,
    "editor.rulers": [80, 100, 120],
    "C_Cpp.clang_format_style": "file",
    "C_Cpp.codeAnalysis.enable": true,
    "cmake.configureOnOpen": true,
    "cmake.buildDirectory": "${workspaceFolder}/build",
    "files.associations": {
        "*.h": "c",
        "*.c": "c"
    }
}
```

#### CLion 配置

- 设置 Code Style: File | Settings | Editor | Code Style | C/C++
- 导入项目根目录的 `.clang-format` 文件
- 启用 Clang-Tidy: File | Settings | Editor | Inspections | C/C++ | Clang-Tidy

## 项目结构

```
ainos/
├── CMakeLists.txt              # 顶层 CMake 配置
├── .clang-format               # 代码格式配置
├── .clang-tidy                 # 静态分析配置
├── .pre-commit-config.yaml     # pre-commit 钩子配置
├── src/                        # 源代码
│   ├── core/                   # 核心组件
│   │   ├── inference.c         # 推理引擎
│   │   ├── model.c             # 模型管理
│   │   ├── context.c           # 上下文管理
│   │   └── memory.c            # 内存管理
│   ├── pal/                    # 平台抽象层
│   │   ├── thread.c
│   │   ├── mutex.c
│   │   ├── memory.c
│   │   ├── fs.c
│   │   ├── net.c
│   │   └── time.c
│   ├── server/                 # 服务端
│   │   ├── main.c
│   │   ├── config.c
│   │   ├── protocol.c
│   │   └── session.c
│   ├── ipc/                    # IPC 通信
│   │   ├── ndjson.c
│   │   └── transport.c
│   └── utils/                  # 工具函数
│       ├── hash.c
│       ├── uuid.c
│       └── log.c
├── include/                    # 公共头文件
│   ├── ainos/                  # 公共 API
│   │   ├── ainos.h
│   │   ├── syscalls.h
│   │   └── pal/
│   │       ├── thread.h
│   │       ├── mutex.h
│   │       ├── memory.h
│   │       ├── fs.h
│   │       ├── net.h
│   │       └── time.h
├── bindings/                   # 语言绑定
│   ├── go/ainos/
│   ├── rust/ainos-sdk/
│   ├── java/
│   ├── csharp/AinosSdk/
│   └── node/
├── tests/                      # 测试
│   ├── unit/                   # 单元测试
│   ├── integration/            # 集成测试
│   ├── fuzz/                   # 模糊测试
│   └── performance/            # 性能测试
├── docs/                       # 文档
│   ├── architecture/
│   ├── api/
│   ├── guides/
│   └── tutorials/
└── models/                     # 模型配置
    └── model_configs/
        ├── embedding/
        ├── vision/
        └── llm/
```

## 代码风格

### C 语言风格

#### 命名约定

```c
// 文件命名: snake_case
// inference_engine.c, model_manager.c

// 函数命名: ainos_{module}_{action}
// 公共 API
int ainos_inference_create(ainos_inference_params_t* params);
int ainos_model_load(const char* path, uint32_t* model_id);

// 内部函数: 静态 + snake_case
static int parse_config_line(const char* line, config_entry_t* entry);
static uint64_t compute_hash(const void* data, size_t len);

// 类型命名: snake_case + _t 后缀
typedef struct ainos_model_info {
    uint32_t id;
    char name[128];
    uint64_t size;
} ainos_model_info_t;

// 宏命名: 全大写 + AINOS_ 前缀
#define AINOS_MAX_PATH 4096
#define AINOS_FLAG_ASYNC (1 << 0)

// 枚举命名: 全大写 + AINOS_ 前缀
enum ainos_log_level {
    AINOS_LOG_LEVEL_ERROR = 0,
    AINOS_LOG_LEVEL_WARN,
    AINOS_LOG_LEVEL_INFO,
    AINOS_LOG_LEVEL_DEBUG
};
```

#### 缩进和格式

```c
// 缩进: 4 空格，不使用 Tab
// 行宽: 100 字符
// 括号: K&R 风格

int ainos_inference_create(ainos_inference_params_t* params) {
    int ret;

    if (params == NULL || params->size == 0) {
        return -EINVAL;
    }

    ret = validate_params(params);
    if (ret != 0) {
        return ret;
    }

    // 空行分隔逻辑块
    ret = allocate_inference_context(params);
    if (ret != 0) {
        return -ENOMEM;
    }

    return 0;
}

// 指针: * 靠近变量名
int* ptr;
char* str;

// 条件语句始终使用大括号
if (condition) {
    do_something();
}

// switch 语句
switch (type) {
    case AINOS_TYPE_A:
        handle_type_a();
        break;
    case AINOS_TYPE_B:
        handle_type_b();
        break;
    default:
        handle_default();
        break;
}
```

#### 注释风格

```c
// 文件头注释
/**
 * @file inference_engine.c
 * @brief AI 推理引擎实现
 * @author AinosOS Team
 * @date 2024-08-01
 */

// 函数注释
/**
 * @brief 执行 AI 模型推理
 * @param params 推理参数结构体指针
 * @return 0 表示成功，负数表示错误码
 * @retval 0 成功
 * @retval -EINVAL 参数无效
 * @retval -ENOMEM 内存不足
 * @note 此函数是线程安全的
 * @see ainos_model_load
 */
int ainos_inference_create(ainos_inference_params_t* params);

// 行内注释
// 关键逻辑的简短说明
int count = calculate_count();  // 计算推理批次大小
```

### Git 提交规范

#### 提交信息格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

#### 类型 (type)

| 类型 | 说明 |
|------|------|
| feat | 新功能 |
| fix | 修复 Bug |
| docs | 文档变更 |
| style | 代码格式变更 |
| refactor | 重构 |
| perf | 性能优化 |
| test | 测试相关 |
| chore | 构建/工具变更 |
| ci | CI 配置变更 |

#### 示例

```
feat(inference): 添加流式推理支持

实现流式推理的服务器端支持，包括：
- 新增 stream 消息类型
- 实现 Token 逐块发送
- 添加流式超时控制

Closes #123
```

### Python 代码风格

```python
# 遵循 PEP 8
# 命名: snake_case

def create_inference(
    model_id: str,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> InferenceResult:
    """创建推理请求。

    Args:
        model_id: 模型标识符
        prompt: 输入提示
        temperature: 温度参数
        max_tokens: 最大生成 Token 数

    Returns:
        推理结果对象

    Raises:
        AinosError: 推理失败时抛出
    """
    # 实现代码
    pass
```

## 测试指南

### 测试类型

| 测试类型 | 目录 | 说明 |
|---------|------|------|
| 单元测试 | tests/unit/ | 测试单个函数/模块 |
| 集成测试 | tests/integration/ | 测试组件间交互 |
| 模糊测试 | tests/fuzz/ | 随机输入测试 |
| 性能测试 | tests/performance/ | 延迟和吞吐量测试 |

### 编写单元测试

```c
#include <unity.h>
#include "ainos/core/inference.h"

void setUp(void) {
    // 每个测试前的初始化
}

void tearDown(void) {
    // 每个测试后的清理
}

void test_inference_params_validation(void) {
    // 测试 NULL 参数
    int ret = ainos_inference_create(NULL);
    TEST_ASSERT_EQUAL(-EINVAL, ret);

    // 测试无效的 size
    ainos_inference_params_t params = {0};
    params.size = 0;
    ret = ainos_inference_create(&params);
    TEST_ASSERT_EQUAL(-EINVAL, ret);

    // 测试有效的参数
    params.size = sizeof(params);
    params.model_id = 1;
    params.context_id = 1;
    params.flags = AINOS_INFERENCE_FLAG_SYNC;
    params.input_data = "test";
    params.input_size = 5;
    params.output_data = malloc(1024);
    params.output_size = 1024;
    // 设置 mock 返回成功
    ret = ainos_inference_create(&params);
    TEST_ASSERT_EQUAL(0, ret);
    free(params.output_data);
}

void test_inference_temperature_range(void) {
    ainos_inference_params_t params = {0};
    params.size = sizeof(params);
    params.temperature = 3.0f;  // 超出范围
    int ret = ainos_inference_create(&params);
    TEST_ASSERT_EQUAL(-EINVAL, ret);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_inference_params_validation);
    RUN_TEST(test_inference_temperature_range);
    return UNITY_END();
}
```

### 编写集成测试

```python
import pytest
import subprocess
import time
import json
from ainos import AinosClient

@pytest.fixture(scope="module")
def ainos_server():
    """启动测试用 Ainos 服务器"""
    proc = subprocess.Popen(
        ["ainosd", "--config", "tests/config_test.yaml"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)  # 等待启动
    yield proc
    proc.terminate()
    proc.wait()

@pytest.fixture
def client(ainos_server):
    """创建测试客户端"""
    client = AinosClient(host="127.0.0.1", port=9501)
    client.connect()
    yield client
    client.disconnect()

class TestInferenceIntegration:
    def test_sync_inference(self, client):
        """测试同步推理"""
        result = client.inference(
            model_id="test-model",
            prompt="Hello",
            max_tokens=50
        )
        assert result.output is not None
        assert len(result.output) > 0
        assert result.tokens_generated > 0

    def test_stream_inference(self, client):
        """测试流式推理"""
        tokens = []
        for token in client.inference(
            model_id="test-model",
            prompt="Hello",
            stream=True,
            max_tokens=50
        ):
            tokens.append(token)
        assert len(tokens) > 0
        assert "".join(tokens) is not None

    def test_batch_inference(self, client):
        """测试批量推理"""
        prompts = ["Hello", "World", "Test"]
        results = client.batch_inference(
            model_id="test-model",
            prompts=prompts,
            max_tokens=20
        )
        assert len(results) == 3
        for result in results:
            assert result.output is not None

    def test_model_management(self, client):
        """测试模型管理"""
        # 加载模型
        model = client.load_model("/models/test-model.gguf")
        assert model.model_id is not None

        # 列出模型
        models = client.list_models()
        assert len(models) > 0

        # 卸载模型
        result = client.unload_model(model.model_id)
        assert result is True
```

### 测试覆盖率

```bash
# 生成覆盖率报告
cmake .. -DAINOS_COVERAGE=ON
ninja -j$(nproc)
ctest --output-on-failure

# 生成 HTML 报告
gcovr -r . --html --html-details -o coverage.html

# 生成 XML 报告（用于 CI）
gcovr -r . --xml -o coverage.xml
```

### 测试要求

- 单元测试覆盖率 >= 80%
- 核心模块覆盖率 >= 90%
- 新功能必须包含测试
- 所有测试必须通过才能合并 PR

## CI/CD 流程

### GitHub Actions 配置

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        build_type: [Debug, Release]

    runs-on: ${{ matrix.os }}

    steps:
    - uses: actions/checkout@v4
      with:
        submodules: recursive

    - name: Setup dependencies
      run: |
        if [ "$RUNNER_OS" == "Linux" ]; then
          sudo apt-get update
          sudo apt-get install -y cmake ninja-build libssl-dev
        elif [ "$RUNNER_OS" == "macOS" ]; then
          brew install cmake ninja
        fi
      shell: bash

    - name: Configure
      run: |
        cmake -B build -G Ninja \
          -DCMAKE_BUILD_TYPE=${{ matrix.build_type }} \
          -DAINOS_TESTS=ON \
          -DAINOS_SANITIZER=ON

    - name: Build
      run: cmake --build build --config ${{ matrix.build_type }}

    - name: Test
      run: ctest --test-dir build --output-on-failure -j$(nproc)

    - name: Lint
      run: |
        cmake --build build --target lint
        cmake --build build --target clang-tidy

  code_quality:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Run clang-format
      uses: jidicula/clang-format-action@v4.11
      with:
        clang-format-version: '14'

    - name: Run cppcheck
      run: |
        cppcheck --enable=all --suppress=missingIncludeSystem \
          --error-exitcode=1 --std=c11 src/

  fuzz:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Build and run fuzz tests
      run: |
        cmake -B build -DAINOS_FUZZ=ON
        cmake --build build
        ./build/tests/fuzz/test_ipc_fuzz
        ./build/tests/fuzz/test_fuzz

  performance:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Build benchmarks
      run: |
        cmake -B build -DAINOS_BENCHMARKS=ON -DCMAKE_BUILD_TYPE=Release
        cmake --build build
    - name: Run benchmarks
      run: |
        ./build/tests/performance/test_latency
        ./build/tests/performance/test_throughput
```

### 代码审查清单

#### 功能检查
- [ ] 功能是否按需求实现
- [ ] 边界情况是否处理
- [ ] 错误处理是否完善
- [ ] 日志是否适当

#### 代码质量
- [ ] 代码风格是否符合规范
- [ ] 是否有重复代码
- [ ] 函数是否过于复杂
- [ ] 命名是否清晰

#### 安全性
- [ ] 输入验证是否完整
- [ ] 内存管理是否正确
- [ ] 是否存在竞态条件
- [ ] 敏感信息是否妥善处理

#### 性能
- [ ] 是否有性能瓶颈
- [ ] 内存使用是否合理
- [ ] 是否避免了不必要的复制
- [ ] 并发处理是否正确

#### 测试
- [ ] 是否有单元测试
- [ ] 测试覆盖率是否达标
- [ ] 边界情况是否测试
- [ ] 测试是否可重复

## 调试技巧

### GDB 调试

```bash
# 编译调试版本
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build

# 使用 GDB 调试
gdb --args ./build/ainosd --config test_config.yaml

# GDB 常用命令
(gdb) break ainos_inference_create  # 设置断点
(gdb) run                           # 运行
(gdb) next                          # 下一步
(gdb) step                          # 进入函数
(gdb) print params                  # 打印变量
(gdb) backtrace                     # 查看调用栈
(gdb) info threads                  # 查看线程
(gdb) thread apply all bt           # 所有线程的调用栈
```

### 内存检查

```bash
# 使用 AddressSanitizer（已集成在 Debug 构建中）
# 编译时自动启用，运行即可检测内存错误

# 使用 Valgrind
valgrind --leak-check=full \
    --show-leak-kinds=all \
    --track-origins=yes \
    ./build/ainosd --config test_config.yaml
```

### 性能分析

```bash
# 使用 perf（Linux）
perf record -g ./build/ainosd --config test_config.yaml
perf report

# 使用 gperftools
CPUPROFILE=/tmp/ainos.prof ./build/ainosd --config test_config.yaml
pprof --text ./build/ainosd /tmp/ainos.prof

# 使用火焰图
perf script | stackcollapse-perf.pl | flamegraph.pl > flame.svg
```

## 版本发布流程

### 版本号规范

遵循语义化版本控制 (SemVer): `MAJOR.MINOR.PATCH`

| 版本 | 说明 |
|------|------|
| MAJOR | 不兼容的 API 变更 |
| MINOR | 向下兼容的功能新增 |
| PATCH | 向下兼容的 Bug 修复 |

### 发布步骤

```bash
# 1. 创建发布分支
git checkout -b release/v2.1.0 develop

# 2. 更新版本号
# 修改 CMakeLists.txt 中的 PROJECT_VERSION
# 修改 docs/ 中的版本信息

# 3. 更新 CHANGELOG
# 在 CHANGELOG.md 中添加新版本条目

# 4. 提交变更
git add .
git commit -m "chore(release): v2.1.0"

# 5. 创建标签
git tag -a v2.1.0 -m "AinosOS v2.1.0"

# 6. 合并到主分支
git checkout main
git merge release/v2.1.0

# 7. 发布
git push origin main --tags
```

## 贡献指南

1. Fork 仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交变更 (`git commit -m 'feat: add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### PR 模板

```markdown
## 描述

请简要描述此 PR 的变更内容。

## 相关 Issue

Closes #(issue number)

## 变更类型

- [ ] 新功能 (feat)
- [ ] Bug 修复 (fix)
- [ ] 重构 (refactor)
- [ ] 性能优化 (perf)
- [ ] 文档更新 (docs)
- [ ] 测试 (test)
- [ ] 构建/CI (chore)

## 测试

- [ ] 单元测试已添加/更新
- [ ] 集成测试已通过
- [ ] 手动测试已执行

## 检查清单

- [ ] 代码风格符合规范
- [ ] 文档已更新
- [ ] 无新的编译器警告
- [ ] 所有测试通过
```