cmake_minimum_required(VERSION 3.20)

# 电源策略调度模块
add_library(power_policy STATIC
    thermal_monitor.cpp
    power_policy.cpp
)

target_include_directories(power_policy
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

# 安装
install(TARGETS power_policy DESTINATION ${CMAKE_INSTALL_LIBDIR}/ainos)