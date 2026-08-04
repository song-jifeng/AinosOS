# ============================================================================
# Ainos OS - macOS Platform Build Configuration
# ============================================================================
#
# This CMakeLists.txt defines build rules for macOS-specific components:
#   - libainos_xpc.dylib   : XPC service library (bridges XPC <-> daemon IPC)
#   - libainos_logging.dylib : Unified logging wrapper (os_log)
#   - libainos_thermal.dylib : Thermal monitoring via IOKit
#   - AinosMenuBar.app      : SwiftUI menu bar application
#   - install.sh            : Installer script (copied, not compiled)
#
# Requirements:
#   - macOS 11.0+ (Big Sur) or later
#   - Xcode 13+ with Command Line Tools
#   - CMake 3.20+
#
# Build:
#   mkdir build && cd build
#   cmake .. -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64"
#   make -j$(sysctl -n hw.logicalcpu)
#
# Universal binary:
#   The default CMAKE_OSX_ARCHITECTURES builds a universal binary for
#   both Intel (x86_64) and Apple Silicon (arm64).
# ============================================================================

cmake_minimum_required(VERSION 3.20)
project(ainos-platform-darwin
    VERSION 1.0.0
    LANGUAGES C CXX Swift
    DESCRIPTION "Ainos OS macOS Platform Components"
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Require macOS 11.0 (Big Sur) as the minimum deployment target
set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "Minimum macOS version")

# Build universal binary by default (Intel + Apple Silicon)
if(NOT CMAKE_OSX_ARCHITECTURES)
    set(CMAKE_OSX_ARCHITECTURES "x86_64;arm64" CACHE STRING "OS X architectures")
endif()

# Code signing identity (set via environment or cache)
# Example: -DCMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY="Apple Development: user@example.com"
if(NOT CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY)
    set(CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "$ENV{AINOS_CODE_SIGN_IDENTITY}" CACHE STRING "Code sign identity")
endif()

# Enable ARC for Objective-C/C++ files
set(CMAKE_XCODE_ATTRIBUTE_CLANG_ENABLE_OBJC_ARC YES)

# ---------------------------------------------------------------------------
# Build settings
# ---------------------------------------------------------------------------

# Use C17 and C++17 standards
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Strict warnings
add_compile_options(-Wall -Wextra -Wpedantic)
add_compile_options(-Werror=implicit-function-declaration)
add_compile_options(-Werror=return-type)
add_compile_options(-Werror=unused-variable)

# Objective-C runtimes need -fobjc-arc
add_compile_options(-fobjc-arc)

# macOS framework flags
set(MACOS_FRAMEWORKS
    Foundation
    CoreFoundation
    IOKit
    Security
    SystemConfiguration
    Cocoa
    SwiftUI
    ServiceManagement
)

# ---------------------------------------------------------------------------
# XPC Service Library
# ---------------------------------------------------------------------------

add_library(ainos_xpc SHARED
    ainos_xpc.c
)

target_include_directories(ainos_xpc
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/system-services/ai-daemon/src
)

target_link_libraries(ainos_xpc
    PUBLIC
        "-framework Foundation"
        "-framework CoreFoundation"
        "-framework Security"
)

# XPC service bundle identifier
set_target_properties(ainos_xpc PROPERTIES
    BUNDLE TRUE
    BUNDLE_EXTENSION "xpc"
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/com.ainos.daemon.xpc.plist"
    MACOSX_BUNDLE_GUI_IDENTIFIER "com.ainos.daemon.xpc"
    MACOSX_BUNDLE_BUNDLE_NAME "Ainos XPC Service"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}"
)

# Code sign the XPC service bundle
set_target_properties(ainos_xpc PROPERTIES
    XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/com.ainos.daemon.xpc.entitlements"
)

# ---------------------------------------------------------------------------
# Logging Library
# ---------------------------------------------------------------------------

add_library(ainos_logging SHARED
    ainos_logging.c
)

target_include_directories(ainos_logging
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(ainos_logging
    PUBLIC
        "-framework Foundation"
        "-framework CoreFoundation"
        "-framework OSLog"
)

set_target_properties(ainos_logging PROPERTIES
    MACOSX_FRAMEWORK_SHORT_VERSION_STRING "${PROJECT_VERSION}"
    MACOSX_FRAMEWORK_BUNDLE_VERSION "${PROJECT_VERSION}"
    FRAMEWORK TRUE
    FRAMEWORK_VERSION A
    PUBLIC_HEADER "ainos_logging.h"
)

# ---------------------------------------------------------------------------
# Thermal Monitoring Library
# ---------------------------------------------------------------------------

add_library(ainos_thermal SHARED
    ainos_thermal.c
)

target_include_directories(ainos_thermal
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/ai-runtime/include
)

target_link_libraries(ainos_thermal
    PUBLIC
        "-framework Foundation"
        "-framework CoreFoundation"
        "-framework IOKit"
)

set_target_properties(ainos_thermal PROPERTIES
    MACOSX_FRAMEWORK_SHORT_VERSION_STRING "${PROJECT_VERSION}"
    MACOSX_FRAMEWORK_BUNDLE_VERSION "${PROJECT_VERSION}"
    FRAMEWORK TRUE
    FRAMEWORK_VERSION A
    PUBLIC_HEADER "ainos_thermal.h"
)

# ---------------------------------------------------------------------------
# SwiftUI Menu Bar App
# ---------------------------------------------------------------------------

# Find Swift compiler
find_program(SWIFT_COMPILER swiftc REQUIRED)

# Swift source files
set(SWIFT_SOURCES
    AinosMenuBar.swift
)

# Build the menu bar app as a standalone executable
add_executable(AinosMenuBar
    MACOSX_BUNDLE
    ${SWIFT_SOURCES}
)

set_target_properties(AinosMenuBar PROPERTIES
    MACOSX_BUNDLE_GUI_IDENTIFIER "com.ainos.menubar"
    MACOSX_BUNDLE_BUNDLE_NAME "AinosOS"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}"
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/AinosMenuBar-Info.plist"
    XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/AinosMenuBar.entitlements"
    XCODE_ATTRIBUTE_LD_RUNPATH_SEARCH_PATHS "@executable_path/../Frameworks"
    XCODE_ATTRIBUTE_SWIFT_VERSION "5.0"
)

# Link Swift libraries
target_link_libraries(AinosMenuBar
    PRIVATE
        "-framework SwiftUI"
        "-framework Cocoa"
        "-framework ServiceManagement"
        "-framework Foundation"
        "-framework CoreFoundation"
        "-framework UserNotifications"
        # Link the XPC service for menu bar status queries
        ainos_xpc
)

# ---------------------------------------------------------------------------
# Custom target: build .dmg package
# ---------------------------------------------------------------------------

set(DMG_NAME "AinosOS-${PROJECT_VERSION}-macOS.dmg")
set(DMG_STAGING "${CMAKE_CURRENT_BINARY_DIR}/dmg-staging")

add_custom_target(package-dmg
    COMMAND ${CMAKE_COMMAND} -E make_directory "${DMG_STAGING}"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${DMG_STAGING}/Applications"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "$<TARGET_BUNDLE_DIR:AinosMenuBar>"
        "${DMG_STAGING}/Applications/AinosOS.app"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_SOURCE_DIR}/install.sh"
        "${DMG_STAGING}/install.sh"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_CURRENT_SOURCE_DIR}/com.ainos.daemon.plist"
        "${DMG_STAGING}/com.ainos.daemon.plist"
    COMMAND hdiutil create -volname "AinosOS" -srcfolder "${DMG_STAGING}"
        -ov -format UDZO "${CMAKE_CURRENT_BINARY_DIR}/${DMG_NAME}"
    COMMAND ${CMAKE_COMMAND} -E remove_directory "${DMG_STAGING}"
    COMMENT "Building macOS disk image: ${DMG_NAME}"
    DEPENDS AinosMenuBar ainos_xpc ainos_logging ainos_thermal
)

# ---------------------------------------------------------------------------
# Custom target: install via script (alias for convenience)
# ---------------------------------------------------------------------------

add_custom_target(install-macos
    COMMAND sudo bash "${CMAKE_CURRENT_SOURCE_DIR}/install.sh"
    COMMENT "Installing AinosOS macOS components"
    DEPENDS AinosMenuBar ainos_xpc ainos_logging ainos_thermal
)

# ---------------------------------------------------------------------------
# Custom target: code sign all binaries
# ---------------------------------------------------------------------------

add_custom_target(codesign
    COMMAND codesign --force --options runtime --sign "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
        "$<TARGET_FILE:ainos_xpc>"
    COMMAND codesign --force --options runtime --sign "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
        "$<TARGET_FILE:ainos_logging>"
    COMMAND codesign --force --options runtime --sign "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
        "$<TARGET_FILE:ainos_thermal>"
    COMMAND codesign --force --options runtime --sign "${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}"
        --entitlements "${CMAKE_CURRENT_SOURCE_DIR}/AinosMenuBar.entitlements"
        "$<TARGET_BUNDLE_DIR:AinosMenuBar>"
    COMMENT "Code signing all macOS binaries"
    DEPENDS AinosMenuBar ainos_xpc ainos_logging ainos_thermal
)

# ---------------------------------------------------------------------------
# Custom target: lint / check formatting
# ---------------------------------------------------------------------------

add_custom_target(lint
    COMMAND clang-format --dry-run -Werror
        ${CMAKE_CURRENT_SOURCE_DIR}/ainos_xpc.c
        ${CMAKE_CURRENT_SOURCE_DIR}/ainos_logging.c
        ${CMAKE_CURRENT_SOURCE_DIR}/ainos_thermal.c
    COMMENT "Checking code formatting"
)

# ---------------------------------------------------------------------------
# Installation rules
# ---------------------------------------------------------------------------

install(TARGETS ainos_xpc
    LIBRARY DESTINATION /usr/local/lib/ainos
    BUNDLE DESTINATION /usr/local/lib/ainos
)

install(TARGETS ainos_logging
    LIBRARY DESTINATION /usr/local/lib/ainos
    FRAMEWORK DESTINATION /usr/local/lib/ainos
)

install(TARGETS ainos_thermal
    LIBRARY DESTINATION /usr/local/lib/ainos
    FRAMEWORK DESTINATION /usr/local/lib/ainos
)

install(TARGETS AinosMenuBar
    BUNDLE DESTINATION /Applications
)

install(FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/com.ainos.daemon.plist
    DESTINATION /Library/LaunchDaemons
)

install(FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/install.sh
    DESTINATION /usr/local/lib/ainos
    PERMISSIONS OWNER_READ OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE
)

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------

message(STATUS "============================================")
message(STATUS "AinosOS macOS Platform Build")
message(STATUS "============================================")
message(STATUS "Deployment target : macOS ${CMAKE_OSX_DEPLOYMENT_TARGET}")
message(STATUS "Architectures     : ${CMAKE_OSX_ARCHITECTURES}")
message(STATUS "Code sign identity: ${CMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY}")
message(STATUS "")
message(STATUS "Targets:")
message(STATUS "  ainos_xpc        : XPC service library")
message(STATUS "  ainos_logging    : Unified logging wrapper")
message(STATUS "  ainos_thermal    : IOKit thermal monitoring")
message(STATUS "  AinosMenuBar     : SwiftUI menu bar app")
message(STATUS "  package-dmg      : Build .dmg installer image")
message(STATUS "  install-macos    : Run install.sh")
message(STATUS "  codesign         : Code sign all binaries")
message(STATUS "============================================")