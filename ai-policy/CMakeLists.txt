cmake_minimum_required(VERSION 3.20)
project(ainos-ai-policy VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# 查找 SQLite3
find_package(PkgConfig REQUIRED)
pkg_check_modules(SQLITE3 REQUIRED sqlite3)

# ============================================
# 策略引擎库
# ============================================
add_library(ai_policy_engine STATIC
    policy-engine/policy_engine.c
    policy-db/policy_db.c
)
target_include_directories(ai_policy_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/policy-engine
    ${CMAKE_CURRENT_SOURCE_DIR}/policy-db
)
target_link_libraries(ai_policy_engine PRIVATE ${SQLITE3_LIBRARIES})

# ============================================
# 策略执行器
# ============================================
add_library(ai_policy_enforcer STATIC
    enforcer/enforcer.c
)
target_include_directories(ai_policy_enforcer PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/enforcer
)
target_link_libraries(ai_policy_enforcer PRIVATE ai_policy_engine)

# ============================================
# 策略编译工具
# ============================================
add_executable(ai-policyc
    tools/policy_compiler.c
)
target_link_libraries(ai-policyc PRIVATE ai_policy_engine)

# ============================================
# 策略守护进程
# ============================================
add_executable(ai-policyd
    daemon/policy_daemon.c
)
target_link_libraries(ai-policyd PRIVATE ai_policy_engine ai_policy_enforcer)

# ============================================
# 安装
# ============================================
install(TARGETS ai-policyc ai-policyd DESTINATION /usr/lib/ainos/bin)
install(DIRECTORY include/ DESTINATION include/ainos)
install(DIRECTORY policy-profiles/ DESTINATION /etc/ainos/policy)
install(FILES policy-profiles/default.apl DESTINATION /etc/ainos/policy)

# ============================================
# 测试
# ============================================
enable_testing()
add_test(NAME ai_policy_test COMMAND ai-policyc --test)