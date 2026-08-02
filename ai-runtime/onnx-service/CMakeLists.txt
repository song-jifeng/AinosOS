cmake_minimum_required(VERSION 3.20)

# ONNX 推理服务
add_library(onnx_service STATIC
    onnx_service.cpp
)

target_include_directories(onnx_service
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

if(onnxruntime_FOUND)
    target_link_libraries(onnx_service PRIVATE onnxruntime::onnxruntime)
    target_compile_definitions(onnx_service PRIVATE AINOS_USE_ONNX)
endif()

# 安装
install(TARGETS onnx_service DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)