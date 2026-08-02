cmake_minimum_required(VERSION 3.20)

# 模型管理器
add_library(model_manager STATIC
    model_manager.cpp
)

target_include_directories(model_manager
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

target_link_libraries(model_manager
    PUBLIC
        ggml_engine
        onnx_service
)

# 安装
install(TARGETS model_manager DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)