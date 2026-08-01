# 文件名: desktop/CMakeLists.txt
cmake_minimum_required(VERSION 3.10)
project(ainos-desktop-env C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# 查找依赖
find_package(PkgConfig REQUIRED)

# Wayland Compositor 依赖 (wlroots)
pkg_check_modules(WLR REQUIRED wlroots)
pkg_check_modules(WAYLAND_SERVER REQUIRED wayland-server)
pkg_check_modules(PIXMAN REQUIRED pixman-1)

# Panel 依赖 (GTK3)
pkg_check_modules(GTK3 REQUIRED gtk+-3.0)

# 编译 Ainos Desktop (Wayland Compositor)
add_executable(ainos-desktop ainos-desktop.c)
target_include_directories(ainos-desktop PRIVATE 
    ${WLR_INCLUDE_DIRS} 
    ${WAYLAND_SERVER_INCLUDE_DIRS}
    ${PIXMAN_INCLUDE_DIRS}
)
target_link_libraries(ainos-desktop 
    ${WLR_LIBRARIES} 
    ${WAYLAND_SERVER_LIBRARIES}
    ${PIXMAN_LIBRARIES}
    m
)
target_compile_options(ainos-desktop PRIVATE ${WLR_CFLAGS_OTHER})

# 编译 Ainos Panel (任务栏)
add_executable(ainos-panel ainos-panel.c)
target_include_directories(ainos-panel PRIVATE ${GTK3_INCLUDE_DIRS})
target_link_libraries(ainos-panel ${GTK3_LIBRARIES})
target_compile_options(ainos-panel PRIVATE ${GTK3_CFLAGS_OTHER})

# 安装规则
install(TARGETS ainos-desktop ainos-panel DESTINATION bin)
