# ============================================================================
# Ainos OS - Windows Platform Build Configuration
# ============================================================================
#
# Build rules for Windows-specific components of AinosOS:
#   - ainos_service.exe    Windows Service wrapper
#   - ainos_registry_config.exe  Registry configuration tool
#   - ainos_etw.exe        ETW logging provider
#   - ainos_tray.exe       System tray tool
#
# Requirements:
#   - CMake 3.16 or later
#   - Windows SDK (for ETW, Service, Registry APIs)
#   - MSVC or MinGW-w64
#
# Build:
#   mkdir build && cd build
#   cmake .. -G "Visual Studio 17 2022"
#   cmake --build . --config Release
# ============================================================================

cmake_minimum_required(VERSION 3.16)
project(AinosOS-Win32
    VERSION 0.1.0
    DESCRIPTION "Ainos OS Windows Platform Components"
    LANGUAGES CXX
)

# ============================================================================
# C++ Standard
# ============================================================================

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ============================================================================
# Build Configuration
# ============================================================================

# Set default build type if not specified
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release" CACHE STRING "Build type" FORCE)
endif()

# Enable Ninja or MSBuild generator support
if(MSVC)
    # MSVC-specific settings
    add_compile_options(/W4 /WX- /utf-8 /MP)
    add_compile_options(/D_UNICODE /DUNICODE)
    add_compile_options(/D_WIN32_WINNT=0x0601)  # Windows 7+
    add_compile_options(/D_WINSOCK_DEPRECATED_NO_WARNINGS)
    add_compile_options(/D_CRT_SECURE_NO_WARNINGS)
    add_compile_options(/DNOMINMAX /DWIN32_LEAN_AND_MEAN)

    # Release flags
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /O2 /Oy- /GL /GS-")
    set(CMAKE_EXE_LINKER_FLAGS_RELEASE "${CMAKE_EXE_LINKER_FLAGS_RELEASE} /LTCG")

    # Debug flags
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} /Od /RTC1 /ZI")

    # Set subsystem for GUI applications
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} /NXCOMPAT /DYNAMICBASE /HIGHENTROPYVA")
else()
    # MinGW-w64 settings
    add_compile_options(-Wall -Wextra -Wno-unused-parameter)
    add_compile_options(-DUNICODE -D_UNICODE)
    add_compile_options(-D_WIN32_WINNT=0x0601)
    add_compile_options(-DNOMINMAX -DWIN32_LEAN_AND_MEAN)
endif()

# ============================================================================
# Windows Libraries
# ============================================================================

# Common Windows libraries
set(WINDOWS_LIBS
    advapi32      # Registry, Service Control, Event Log, Security
    kernel32      # Core Windows API
    user32        # Window management, message boxes
    gdi32         # Graphics (icon creation)
    shell32       # Shell operations, shortcuts
    ole32         # COM
    oleaut32      # COM automation
    ws2_32        # Windows Sockets (for ETW/tracing)
    comctl32      # Common controls
    shlwapi       # Shell light-weight API
    crypt32       # Cryptography (for certificate handling)
    version       # File version info
)

# ETW requires advapi32 (for EventRegister/EventWrite)
# Service requires advapi32 (for OpenSCManager, CreateService, etc.)
# Registry requires advapi32 (for RegOpenKeyEx, etc.)
# System tray requires shell32, user32, gdi32, comctl32

# ============================================================================
# Source Files
# ============================================================================

set(SERVICE_SOURCES
    ainos_service.cpp
)

set(REGISTRY_CONFIG_SOURCES
    ainos_registry_config.cpp
)

set(ETW_SOURCES
    ainos_etw.cpp
)

set(TRAY_SOURCES
    ainos_tray.cpp
)

# Version resource file for all executables
set(VERSION_RESOURCE
    ainos_resource.rc
)

# ============================================================================
# Executable Targets
# ============================================================================

# ---- ainos_service.exe ----
# Windows Service wrapper (console application for install/uninstall commands)
add_executable(ainos_service
    ${SERVICE_SOURCES}
    ${VERSION_RESOURCE}
)

target_link_libraries(ainos_service PRIVATE
    ${WINDOWS_LIBS}
)

target_include_directories(ainos_service PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

set_target_properties(ainos_service PROPERTIES
    OUTPUT_NAME "ainos_service"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    WIN32_EXECUTABLE FALSE  # Console app for --install/--uninstall/--start/--stop commands
)

# ---- ainos_registry_config.exe ----
# Registry configuration tool (console application)
add_executable(ainos_registry_config
    ${REGISTRY_CONFIG_SOURCES}
    ${VERSION_RESOURCE}
)

target_link_libraries(ainos_registry_config PRIVATE
    ${WINDOWS_LIBS}
)

target_include_directories(ainos_registry_config PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

set_target_properties(ainos_registry_config PROPERTIES
    OUTPUT_NAME "ainos_registry_config"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    WIN32_EXECUTABLE FALSE
)

# ---- ainos_etw.exe ----
# ETW logging provider (console application)
add_executable(ainos_etw
    ${ETW_SOURCES}
    ${VERSION_RESOURCE}
)

target_link_libraries(ainos_etw PRIVATE
    ${WINDOWS_LIBS}
)

target_include_directories(ainos_etw PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

set_target_properties(ainos_etw PROPERTIES
    OUTPUT_NAME "ainos_etw"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    WIN32_EXECUTABLE FALSE
)

# ---- ainos_tray.exe ----
# System tray tool (GUI application, no console window)
add_executable(ainos_tray
    ${TRAY_SOURCES}
    ${VERSION_RESOURCE}
)

target_link_libraries(ainos_tray PRIVATE
    ${WINDOWS_LIBS}
)

target_include_directories(ainos_tray PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

set_target_properties(ainos_tray PROPERTIES
    OUTPUT_NAME "ainos_tray"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    WIN32_EXECUTABLE TRUE  # GUI subsystem - no console window
)

# ============================================================================
# Resource File
# ============================================================================

# Generate the version resource file if it doesn't exist
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/ainos_resource.rc")
    file(WRITE "${CMAKE_CURRENT_SOURCE_DIR}/ainos_resource.rc" [[
// Ainos OS - Version Resource File
// Auto-generated by CMake

#include <windows.h>

VS_VERSION_INFO VERSIONINFO
    FILEVERSION     0,1,0,0
    PRODUCTVERSION  0,1,0,0
    FILEFLAGSMASK   0x3fL
    FILEFLAGS       0x0L
    FILEOS          VOS_NT_WINDOWS32
    FILETYPE        VFT_APP
    FILESUBTYPE     0x0L
BEGIN
    BLOCK "StringFileInfo"
    BEGIN
        BLOCK "040904B0" // English (United States), Unicode
        BEGIN
            VALUE "CompanyName",      "Ainos Project"
            VALUE "FileDescription",  "Ainos OS Windows Component"
            VALUE "FileVersion",      "0.1.0.0"
            VALUE "InternalName",     "AinosOS"
            VALUE "LegalCopyright",   "Copyright (C) 2025 Ainos Project"
            VALUE "OriginalFilename", "AinosOS.exe"
            VALUE "ProductName",      "Ainos OS"
            VALUE "ProductVersion",   "0.1.0"
        END
    END
    BLOCK "VarFileInfo"
    BEGIN
        VALUE "Translation", 0x0409, 0x04B0
    END
END
]])
endif()

# ============================================================================
# Custom Targets
# ============================================================================

# Target: Build all
add_custom_target(all_win32
    DEPENDS
        ainos_service
        ainos_registry_config
        ainos_etw
        ainos_tray
    COMMENT "Building all Ainos OS Windows components"
)

# Target: Install (via PowerShell)
add_custom_target(install_win32
    COMMAND powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${CMAKE_CURRENT_SOURCE_DIR}/install.ps1"
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Running Ainos OS Windows installer"
)

# Target: Create distribution package
add_custom_target(package_win32
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/dist"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_BINARY_DIR}/bin/ainos_service.exe" "${CMAKE_BINARY_DIR}/dist/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_BINARY_DIR}/bin/ainos_registry_config.exe" "${CMAKE_BINARY_DIR}/dist/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_BINARY_DIR}/bin/ainos_etw.exe" "${CMAKE_BINARY_DIR}/dist/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_BINARY_DIR}/bin/ainos_tray.exe" "${CMAKE_BINARY_DIR}/dist/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/install.ps1" "${CMAKE_BINARY_DIR}/dist/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../configs/ai-daemon.toml" "${CMAKE_BINARY_DIR}/dist/"
    COMMENT "Creating distribution package"
    DEPENDS all_win32
)

# ============================================================================
# Install Rules
# ============================================================================

install(TARGETS
    ainos_service
    ainos_registry_config
    ainos_etw
    ainos_tray
    RUNTIME DESTINATION bin
)

install(FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/install.ps1"
    DESTINATION .
)

# ============================================================================
# Compiler-specific configuration
# ============================================================================

if(MSVC)
    # Enable parallel builds (MSBuild)
    set(CMAKE_VS_WINRT_BY_DEFAULT OFF)

    # Suppress specific warnings
    add_compile_options(
        /wd4996     # '_wcsicmp': The POSIX name for this item is deprecated
        /wd4244     # 'argument': conversion from 'type1' to 'type2', possible loss of data
        /wd4267     # 'var': conversion from 'size_t' to 'type', possible loss of data
        /wd4477     # 'printf' format string requires an argument of type 'type'
        /wd4838     # conversion from 'type' to 'type' requires a narrowing conversion
    )

    # Use static CRT for release builds to avoid vcredist dependency
    if(CMAKE_BUILD_TYPE STREQUAL "Release")
        foreach(flag_var
            CMAKE_CXX_FLAGS CMAKE_CXX_FLAGS_RELEASE
            CMAKE_C_FLAGS CMAKE_C_FLAGS_RELEASE)
            string(REGEX REPLACE "/MD" "/MT" ${flag_var} "${${flag_var}}")
        endforeach()
    endif()
endif()

# ============================================================================
# Print build summary
# ============================================================================

message(STATUS "========================================")
message(STATUS "Ainos OS Windows Platform Build")
message(STATUS "========================================")
message(STATUS "Build type:    ${CMAKE_BUILD_TYPE}")
message(STATUS "Generator:     ${CMAKE_GENERATOR}")
message(STATUS "Compiler:      ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "C++ Standard:  ${CMAKE_CXX_STANDARD}")
message(STATUS "Output dir:    ${CMAKE_BINARY_DIR}/bin")
message(STATUS "")
message(STATUS "Targets:")
message(STATUS "  ainos_service.exe        - Windows Service wrapper")
message(STATUS "  ainos_registry_config.exe - Registry configuration tool")
message(STATUS "  ainos_etw.exe           - ETW logging provider")
message(STATUS "  ainos_tray.exe          - System tray tool (GUI)")
message(STATUS "========================================")