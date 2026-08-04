# Ainos OS - Platform Abstraction Layer (PAL)
# 跨平台抽象层构建脚本
#
# Copyright (c) 2024 AinosOS
# SPDX-License-Identifier: MIT
#
# 用法:
#   mkdir build && cd build
#   cmake .. -DAINOS_BUILD_TESTS=ON
#   cmake --build .
#   ctest

cmake_minimum_required(VERSION 3.20)
project(ainos-platform VERSION 1.0.0 LANGUAGES C)

# ============================================
# 项目配置
# ============================================
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# 选项
option(AINOS_BUILD_TESTS "Build platform tests" ON)
option(AINOS_BUILD_SHARED "Build shared library" ON)
option(AINOS_BUILD_STATIC "Build static library" ON)

# ============================================
# 平台检测
# ============================================
if(WIN32)
    set(AINOS_PLATFORM "win32")
    set(AINOS_PLATFORM_SRC "win32/ainos_platform_win32.c")
    set(AINOS_PLATFORM_LIBS "ws2_32;iphlpapi;psapi;rpcrt4")
elseif(APPLE)
    set(AINOS_PLATFORM "darwin")
    set(AINOS_PLATFORM_SRC "darwin/ainos_platform_darwin.c")
    find_library(IOKIT_FRAMEWORK IOKit)
    find_library(COREFOUNDATION_FRAMEWORK CoreFoundation)
    set(AINOS_PLATFORM_LIBS "${IOKIT_FRAMEWORK};${COREFOUNDATION_FRAMEWORK};pthread;dl")
elseif(UNIX)
    set(AINOS_PLATFORM "linux")
    set(AINOS_PLATFORM_SRC "linux/ainos_platform_linux.c")
    set(AINOS_PLATFORM_LIBS "pthread;dl;rt")
else()
    message(FATAL_ERROR "Unsupported platform")
endif()

message(STATUS "AinosOS Platform: ${AINOS_PLATFORM}")

# ============================================
# 头文件路径
# ============================================
set(AINOS_PLATFORM_INCLUDE_DIR
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# ============================================
# 源文件列表
# ============================================
set(AINOS_PLATFORM_SOURCES
    ${AINOS_PLATFORM_SRC}
)

# ============================================
# 构建静态库
# ============================================
if(AINOS_BUILD_STATIC)
    add_library(ainos-platform STATIC
        ${AINOS_PLATFORM_SOURCES}
    )
    target_include_directories(ainos-platform
        PUBLIC
            $<BUILD_INTERFACE:${AINOS_PLATFORM_INCLUDE_DIR}>
            $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    )
    target_link_libraries(ainos-platform
        PUBLIC
            ${AINOS_PLATFORM_LIBS}
    )
    set_target_properties(ainos-platform PROPERTIES
        OUTPUT_NAME "ainos-platform"
        POSITION_INDEPENDENT_CODE ON
    )
endif()

# ============================================
# 构建动态库
# ============================================
if(AINOS_BUILD_SHARED)
    add_library(ainos-platform-shared SHARED
        ${AINOS_PLATFORM_SOURCES}
    )
    target_include_directories(ainos-platform-shared
        PUBLIC
            $<BUILD_INTERFACE:${AINOS_PLATFORM_INCLUDE_DIR}>
            $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    )
    target_link_libraries(ainos-platform-shared
        PUBLIC
            ${AINOS_PLATFORM_LIBS}
    )
    set_target_properties(ainos-platform-shared PROPERTIES
        OUTPUT_NAME "ainos-platform"
        POSITION_INDEPENDENT_CODE ON
    )

    if(WIN32)
        set_target_properties(ainos-platform-shared PROPERTIES
            SUFFIX ".dll"
            IMPORT_SUFFIX ".dll.a"
        )
    elseif(APPLE)
        set_target_properties(ainos-platform-shared PROPERTIES
            SUFFIX ".dylib"
        )
    endif()
endif()

# ============================================
# 构建测试
# ============================================
if(AINOS_BUILD_TESTS)
    enable_testing()

    add_executable(ainos-platform-test
        tests/test_platform.c
    )
    target_include_directories(ainos-platform-test
        PRIVATE
            ${AINOS_PLATFORM_INCLUDE_DIR}
    )
    target_link_libraries(ainos-platform-test
        PRIVATE
            ainos-platform
            ${AINOS_PLATFORM_LIBS}
    )

    # 注册测试
    add_test(NAME platform-test
        COMMAND ainos-platform-test
    )

    # 各 API 组独立测试
    add_test(NAME platform-mutex-test
        COMMAND ainos-platform-test --mutex
    )
    add_test(NAME platform-thread-test
        COMMAND ainos-platform-test --thread
    )
    add_test(NAME platform-socket-test
        COMMAND ainos-platform-test --socket
    )
    add_test(NAME platform-file-test
        COMMAND ainos-platform-test --file
    )
    add_test(NAME platform-memory-test
        COMMAND ainos-platform-test --memory
    )
    add_test(NAME platform-time-test
        COMMAND ainos-platform-test --time
    )
    add_test(NAME platform-process-test
        COMMAND ainos-platform-test --process
    )
    add_test(NAME platform-dl-test
        COMMAND ainos-platform-test --dl
    )
    add_test(NAME platform-env-test
        COMMAND ainos-platform-test --env
    )
endif()

# ============================================
# 安装
# ============================================
install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/ainos
    FILES_MATCHING
        PATTERN "*.h"
)

if(AINOS_BUILD_STATIC)
    install(
        TARGETS ainos-platform
        EXPORT ainos-platform-targets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    )
endif()

if(AINOS_BUILD_SHARED)
    install(
        TARGETS ainos-platform-shared
        EXPORT ainos-platform-targets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    )
endif()

install(
    EXPORT ainos-platform-targets
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/ainos-platform
)

# ============================================
# 导出包配置
# ============================================
include(CMakePackageConfigHelpers)
write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/ainos-platform-config-version.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY AnyNewerVersion
)

install(
    FILES
        ${CMAKE_CURRENT_BINARY_DIR}/ainos-platform-config-version.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/ainos-platform
)