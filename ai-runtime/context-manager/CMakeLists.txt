cmake_minimum_required(VERSION 3.20)

# 上下文管理器
add_library(context_manager STATIC
    context_manager.cpp
)

target_include_directories(context_manager
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

# 安装
install(TARGETS context_manager DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)