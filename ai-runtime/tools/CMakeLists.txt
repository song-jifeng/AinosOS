cmake_minimum_required(VERSION 3.20)

# 工具库
add_library(ainos_tools STATIC
    ainos_cli.cpp
)

target_include_directories(ainos_tools
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

target_link_libraries(ainos_tools
    PUBLIC
        model_manager
        context_manager
)

# 安装
install(TARGETS ainos_tools DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)