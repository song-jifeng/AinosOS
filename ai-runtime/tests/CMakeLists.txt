cmake_minimum_required(VERSION 3.20)

# 测试套件
add_executable(ainos_runtime_test
    test_runtime.cpp
)

target_include_directories(ainos_runtime_test
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

target_link_libraries(ainos_runtime_test
    PRIVATE
        ggml_engine
        model_manager
        context_manager
        power_policy
)

# 注册测试
add_test(NAME ainos_runtime_test COMMAND ainos_runtime_test)