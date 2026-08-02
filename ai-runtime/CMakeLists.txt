cmake_minimum_required(VERSION 3.20)
project(ainos-ai-runtime VERSION 0.1.0 LANGUAGES C CXX)

# ============================================
# 项目配置
# ============================================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# 选项
option(AINOS_ENABLE_GGML "Build with GGML support" ON)
option(AINOS_ENABLE_ONNX "Build with ONNX Runtime support" OFF)
option(AINOS_BUILD_TESTS "Build tests" ON)
option(AINOS_BUILD_TOOLS "Build tools" OFF)

# ============================================
# 依赖查找
# ============================================

# GGML (可选)
if(AINOS_ENABLE_GGML)
    find_package(ggml QUIET)
    if(NOT ggml_FOUND)
        message(STATUS "GGML not found, will use vendored version")
        # TODO: 自动下载/编译 GGML
        set(GGML_FOUND OFF)
    endif()
endif()

# ONNX Runtime (可选)
if(AINOS_ENABLE_ONNX)
    find_package(onnxruntime QUIET)
    if(NOT onnxruntime_FOUND)
        message(STATUS "ONNX Runtime not found, cloud fallback will use API only")
        set(ONNX_FOUND OFF)
    endif()
endif()

# ============================================
# 子目录
# ============================================

# 电源策略调度 (先编译，被 GGML 引擎依赖)
add_subdirectory(power-policy)

# GGML 引擎
if(AINOS_ENABLE_GGML)
    add_subdirectory(ggml-engine)
endif()

# ONNX 服务
if(AINOS_ENABLE_ONNX)
    add_subdirectory(onnx-service)
endif()

# 模型管理器
add_subdirectory(model-manager)

# 上下文管理器
add_subdirectory(context-manager)

# ============================================
# 工具
# ============================================
if(AINOS_BUILD_TOOLS)
    add_subdirectory(tools)
endif()

# ============================================
# 测试
# ============================================
if(AINOS_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

# ============================================
# 安装
# ============================================
install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/ainos
)