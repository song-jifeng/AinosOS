#=============================================================================
# CMakeLists.txt - iOS Native Build Configuration for Ainos Platform
#=============================================================================

cmake_minimum_required(VERSION 3.18)
project(ainos_ios
    VERSION 1.0.0
    DESCRIPTION "Ainos iOS Platform Support Layer"
    LANGUAGES CXX C Swift)

# C++ Standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# iOS specific settings
set(CMAKE_SYSTEM_NAME iOS)
set(CMAKE_OSX_DEPLOYMENT_TARGET "13.0")
set(CMAKE_XCODE_ATTRIBUTE_SWIFT_VERSION "5.9")

# Include paths
set(AINOS_INCLUDE_DIR "../include")

# Common C source files
set(COMMON_SOURCES
    ../common/ainos_mobile_common.c
)

# Swift source files
set(SWIFT_SOURCES
    AinosPlatform/AinosPlatform.swift
    AinosPlatform/AinosCoreML.swift
    AinosPlatform/AinosNeuralEngine.swift
    AinosPlatform/AinosThermal.swift
    AinosPlatform/AinosBackground.swift
    AinosPlatform/AinosBattery.swift
)

# Objective-C source files
set(OBJC_SOURCES
    AinosPlatform.m
)

# Build the static library
add_library(ainos_ios STATIC
    ${COMMON_SOURCES}
    ${OBJC_SOURCES}
)

# Include directories
target_include_directories(ainos_ios PRIVATE
    ${AINOS_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

# Compile definitions
target_compile_definitions(ainos_ios PRIVATE
    AINOS_EXPORT=__attribute__((visibility("default")))
    PLATFORM_IOS
    $<$<CONFIG:DEBUG>:AINOS_DEBUG>
)

# Compile options
target_compile_options(ainos_ios PRIVATE
    -Wall -Wextra
    -Wno-unused-parameter
    -fvisibility=hidden
    -fobjc-arc
)

# Link frameworks
target_link_libraries(ainos_ios
    "-framework Foundation"
    "-framework UIKit"
    "-framework CoreML"
    "-framework Metal"
    "-framework MetalPerformanceShaders"
    "-framework BackgroundTasks"
    "-framework UserNotifications"
    "-framework Accelerate"
    "-framework CoreGraphics"
    "-framework ImageIO"
    "-framework CoreVideo"
    "-framework CoreMedia"
)

# Set output properties
set_target_properties(ainos_ios PROPERTIES
    VERSION ${PROJECT_VERSION}
    SOVERSION 1
    POSITION_INDEPENDENT_CODE ON
    XCODE_ATTRIBUTE_SWIFT_VERSION "5.9"
    XCODE_ATTRIBUTE_CLANG_ENABLE_OBJC_ARC "YES"
    PUBLIC_HEADER "${AINOS_INCLUDE_DIR}/ainos/platform_mobile.h;AinosPlatform.h"
)

# Create framework target
add_library(AinosPlatform SHARED
    ${COMMON_SOURCES}
    ${SWIFT_SOURCES}
    ${OBJC_SOURCES}
)

set_target_properties(AinosPlatform PROPERTIES
    FRAMEWORK TRUE
    FRAMEWORK_VERSION "A"
    MACOSX_FRAMEWORK_IDENTIFIER "com.ainos.platform"
    MACOSX_FRAMEWORK_SHORT_VERSION_STRING "1.0.0"
    MACOSX_FRAMEWORK_BUNDLE_VERSION "1"
    XCODE_ATTRIBUTE_SWIFT_VERSION "5.9"
    XCODE_ATTRIBUTE_CLANG_ENABLE_OBJC_ARC "YES"
    PUBLIC_HEADER "${AINOS_INCLUDE_DIR}/ainos/platform_mobile.h;AinosPlatform.h"
)

target_include_directories(AinosPlatform PRIVATE
    ${AINOS_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

target_compile_definitions(AinosPlatform PRIVATE
    AINOS_EXPORT=__attribute__((visibility("default")))
    PLATFORM_IOS
)

target_link_libraries(AinosPlatform
    "-framework Foundation"
    "-framework UIKit"
    "-framework CoreML"
    "-framework Metal"
    "-framework MetalPerformanceShaders"
    "-framework BackgroundTasks"
    "-framework UserNotifications"
    "-framework Accelerate"
    "-framework CoreGraphics"
    "-framework ImageIO"
    "-framework CoreVideo"
    "-framework CoreMedia"
)

# Install rules
install(TARGETS AinosPlatform ainos_ios
    FRAMEWORK DESTINATION Library/Frameworks
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)

# Source group for IDE organization
source_group("common" FILES ${COMMON_SOURCES})
source_group("swift" FILES ${SWIFT_SOURCES})
source_group("objc" FILES ${OBJC_SOURCES})

# Custom target for building
add_custom_target(ainos_ios_all
    COMMAND ${CMAKE_COMMAND} --build .
    COMMENT "Building Ainos iOS framework"
)