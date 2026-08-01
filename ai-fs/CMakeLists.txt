cmake_minimum_required(VERSION 3.20)
project(ainos-ai-fs VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# 依赖: FUSE3, FAISS, nlohmann_json
find_package(PkgConfig REQUIRED)
pkg_check_modules(FUSE3 REQUIRED fuse3)
# pkg_check_modules(FAISS REQUIRED faiss)  # 可选，用于向量索引

# ============================================
# 索引引擎
# ============================================
add_library(ai_fs_indexer STATIC
    indexer/indexer.cpp
)
target_include_directories(ai_fs_indexer PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/indexer
)
target_link_libraries(ai_fs_indexer PRIVATE ${FUSE3_LIBRARIES})

# ============================================
# 搜索守护进程
# ============================================
add_executable(ai-fsd
    search-daemon/search_daemon.cpp
    search-daemon/vector_store.cpp
)
target_include_directories(ai-fsd PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/search-daemon
    ${CMAKE_CURRENT_SOURCE_DIR}/indexer
)
target_link_libraries(ai-fsd PRIVATE
    ai_fs_indexer
    ${FUSE3_LIBRARIES}
)

# ============================================
# 安装
# ============================================
install(TARGETS ai-fsd DESTINATION /usr/lib/ainos/bin)
install(DIRECTORY include/ DESTINATION include/ainos)

# ============================================
# 测试
# ============================================
enable_testing()
add_test(NAME ai_fs_test COMMAND ai-fsd --test)