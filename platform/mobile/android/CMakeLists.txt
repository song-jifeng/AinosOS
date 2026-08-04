#=============================================================================
# CMakeLists.txt - Android Native Build Configuration for Ainos Platform
#=============================================================================

cmake_minimum_required(VERSION 3.18)
project(ainos_android
    VERSION 1.0.0
    DESCRIPTION "Ainos Android Platform Support Layer"
    LANGUAGES CXX C)

# C++ Standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Android specific settings
set(ANDROID_PLATFORM android-24)
set(CMAKE_ANDROID_ARCH_ABI ${ANDROID_ABI})

# Include paths
set(AINOS_INCLUDE_DIR "../include")

# Source files
set(CPP_SOURCES
    cpp/ainos_android_platform.cpp
    cpp/ainos_android_thermal.cpp
    cpp/ainos_android_nn.cpp
    cpp/ainos_android_jni.cpp
    ../common/ainos_mobile_common.c
)

# Build the shared library
add_library(ainos_android SHARED
    ${CPP_SOURCES}
)

# Include directories
target_include_directories(ainos_android PRIVATE
    ${AINOS_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../common
)

# Compile definitions
target_compile_definitions(ainos_android PRIVATE
    AINOS_EXPORT=__attribute__((visibility("default")))
    PLATFORM_ANDROID
    $<$<CONFIG:DEBUG>:AINOS_DEBUG>
)

# Compile options
target_compile_options(ainos_android PRIVATE
    -Wall -Wextra -Werror=return-type
    -Wno-unused-parameter
    -fvisibility=hidden
    -fstack-protector-strong
    -funwind-tables
    -Wno-psabi
)

# Link libraries
target_link_libraries(ainos_android
    jnigraphics
    log
    android
    z
    dl
)

# Set output properties
set_target_properties(ainos_android PROPERTIES
    VERSION ${PROJECT_VERSION}
    SOVERSION 1
    POSITION_INDEPENDENT_CODE ON
    BUILD_WITH_INSTALL_RPATH ON
)

# Install rules
install(TARGETS ainos_android
    LIBRARY DESTINATION lib/${ANDROID_ABI}
)

# Custom target for building all platforms
add_custom_target(ainos_android_all
    COMMAND ${CMAKE_COMMAND} --build . --target ainos_android
    COMMENT "Building Ainos Android for all ABIs"
)

# Helper function to build for a specific ABI
function(ainos_build_android target_abi)
    set(CMAKE_ANDROID_ARCH_ABI ${target_abi})
    add_library(ainos_android_${target_abi} SHARED ${CPP_SOURCES})
    target_include_directories(ainos_android_${target_abi} PRIVATE
        ${AINOS_INCLUDE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../common
    )
    target_compile_definitions(ainos_android_${target_abi} PRIVATE
        AINOS_EXPORT=__attribute__((visibility("default")))
        PLATFORM_ANDROID
    )
    target_link_libraries(ainos_android_${target_abi}
        jnigraphics log android z dl
    )
endfunction()

# Build for common ABIs
if(ANDROID_ABI STREQUAL "all" OR NOT ANDROID_ABI)
    ainos_build_android("arm64-v8a")
    ainos_build_android("armeabi-v7a")
    ainos_build_android("x86_64")
    ainos_build_android("x86")
endif()

# Source group for IDE organization
source_group("cpp" FILES ${CPP_SOURCES})
source_group("include" FILES
    ${AINOS_INCLUDE_DIR}/ainos/platform_mobile.h
    ../common/ainos_mobile_common.h
)