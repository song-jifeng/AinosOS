cmake_minimum_required(VERSION 3.20)

# GGML 推理引擎
add_library(ggml_engine SHARED ggml_engine.cpp)
target_include_directories(ggml_engine PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/../include)

# 链接电源策略模块
target_link_libraries(ggml_engine PRIVATE power_policy)

if(ggml_FOUND)
    target_link_libraries(ggml_engine PRIVATE ggml::ggml)
    target_compile_definitions(ggml_engine PRIVATE AINOS_USE_GGML)
endif()

# 安装
install(TARGETS ggml_engine DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)