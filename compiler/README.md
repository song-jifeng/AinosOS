# AI Compiler Toolchain

AI 编译器工具链 -- 一个支持 AI 自动调优的编译器，可将自定义 AI 语言代码转换为 C、Python、LLVM IR 或 x86 汇编。

## 功能特性

- **词法分析**: 支持标识符、关键字、数字、字符串、运算符等完整 Token 类型
- **语法分析**: 递归下降分析器，支持表达式、语句、函数、类、模块
- **语义分析**: 类型检查、符号表、作用域管理
- **中间表示**: 三地址码 IR，支持 SSA 形式
- **优化**: 常量折叠、死代码消除、循环不变式外提、公共子表达式消除、复制传播、强度削弱、窥孔优化
- **AI 自动调优**: Q-Learning 强化学习优化最优优化顺序，成本模型预测优化收益
- **性能分析**: 性能分析引导优化（PGO）
- **代码生成**: 支持 C、Python、LLVM IR、x86 汇编

## 快速开始

### 安装

```bash
pip install -e .
```

### 编译源文件

```bash
# 编译为 C 代码
python -m src.compiler examples/hello.ai -o hello.c

# 编译为 Python 代码
python -m src.compiler examples/fib.ai -t python -o fib.py

# 编译为 LLVM IR
python -m src.compiler examples/sort.ai -t llvm -o sort.ll

# 启用 AI 自动调优
python -m src.compiler examples/fib.ai --ai-tuning -O3
```

### 作为库使用

```python
from src.compiler import Compiler, compile_source

# 编译源代码
source = """
fn add(a: int, b: int) -> int {
    return a + b;
}

fn main() {
    let result = add(3, 4);
    return result;
}
"""

success, code, compiler = compile_source(source, target="c")
if success:
    print(code)
else:
    print(compiler.get_errors())
```

## 项目结构

```
compiler/
├── src/
│   ├── compiler.py          # 主编译器类
│   ├── frontend/            # 前端
│   │   ├── lexer.py         # 词法分析器
│   │   ├── parser.py        # 语法分析器
│   │   ├── ast.py           # AST 节点定义
│   │   └── token.py         # Token 类型定义
│   ├── middle/              # 中间层
│   │   ├── ir.py            # IR 定义
│   │   ├── optimizer.py     # 优化器
│   │   ├── analyzer.py      # 语义分析器
│   │   └── transform.py     # IR 变换
│   ├── backend/             # 后端
│   │   ├── codegen.py       # 代码生成器
│   │   ├── x86_gen.py       # x86 汇编生成
│   │   └── llvm_gen.py      # LLVM IR 生成
│   ├── ai/                  # AI 模块
│   │   ├── autotune.py      # AI 自动调优
│   │   ├── profile.py       # 性能分析
│   │   └── cost_model.py    # 成本模型
│   └── utils/               # 工具
│       ├── errors.py        # 错误处理
│       └── config.py        # 配置
├── tests/                   # 测试
├── examples/                # 示例
├── setup.py
├── pyproject.toml
└── README.md
```

## 自定义 AI 语言语法

### 变量声明

```python
let x: int = 42;         # 可变变量
const MAX: int = 100;    # 不可变常量
```

### 函数定义

```python
fn add(a: int, b: int) -> int {
    return a + b;
}
```

### 控制流

```python
if (condition) {
    # then
} else {
    # else
}

while (condition) {
    # loop body
}

for (let i = 0; i < n; i = i + 1) {
    # loop body
}
```

### 类定义

```python
class Point {
    let x: int;
    let y: int;
    fn new(x: int, y: int) -> Point {
        return null;
    }
}
```

### 张量类型（AI 专用）

```python
let tensor: tensor<float, [3, 224, 224]> = init_tensor();
```

## 优化级别

- **O0**: 无优化
- **O1**: 基本优化（常量折叠、死代码消除、窥孔优化）
- **O2**: 标准优化（+ CSE、复制传播、强度削弱、循环不变式外提）
- **O3**: 激进优化（+ 内联、尾调用消除、向量化）

## AI 自动调优

启用 AI 自动调优后，编译器将通过强化学习（Q-Learning）自动学习最优的优化 pass 顺序，根据代码特征动态调整优化策略。

```bash
python -m src.compiler source.ai --ai-tuning -O3
```

## 运行测试

```bash
pytest tests/ -v
```

## 许可证

MIT License