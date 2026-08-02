// Ainos AI Runtime - 单元测试
// 验证核心模块的初始化和基本功能

#include "ainos/ai_runtime.h"
#include "ainos/power_policy.h"
#include <cassert>
#include <iostream>
#include <string>

using namespace ainos::ai;
using namespace ainos::power;

// 测试 GGML 引擎创建
static void test_ggml_engine_create() {
    std::cout << "[TEST] GGML Engine Create..." << std::endl;
    auto engine = CreateGGMLEngine();
    assert(engine != nullptr);
    std::cout << "  [PASS] GGML Engine created" << std::endl;
}

// 测试模型管理器创建
static void test_model_manager_create() {
    std::cout << "[TEST] Model Manager Create..." << std::endl;
    auto mgr = CreateModelManager();
    assert(mgr != nullptr);
    std::cout << "  [PASS] Model Manager created" << std::endl;
}

// 测试上下文管理器创建
static void test_context_manager_create() {
    std::cout << "[TEST] Context Manager Create..." << std::endl;
    auto ctx = CreateContextManager();
    assert(ctx != nullptr);
    std::cout << "  [PASS] Context Manager created" << std::endl;
}

// 测试电源策略管理器
static void test_power_policy_manager() {
    std::cout << "[TEST] Power Policy Manager..." << std::endl;
    PowerPolicyManager ppm;
    bool ok = ppm.Initialize();
    assert(ok);
    std::cout << "  [PASS] Power Policy Manager initialized" << std::endl;

    PrecisionMode mode = ppm.GetCurrentMode();
    std::cout << "  Current mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode >= PrecisionMode::MAX && mode <= PrecisionMode::EMERGENCY);
}

// 测试模型元数据结构
static void test_model_metadata() {
    std::cout << "[TEST] Model Metadata..." << std::endl;
    ModelMetadata meta;
    meta.model_id = "test-model";
    meta.model_path = "/models/test.gguf";
    meta.framework = "ggml";
    assert(meta.model_id == "test-model");
    assert(meta.framework == "ggml");
    std::cout << "  [PASS] Model metadata structure OK" << std::endl;
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "Ainos AI Runtime Test Suite" << std::endl;
    std::cout << "========================================" << std::endl;

    test_ggml_engine_create();
    test_model_manager_create();
    test_context_manager_create();
    test_power_policy_manager();
    test_model_metadata();

    std::cout << "========================================" << std::endl;
    std::cout << "ALL TESTS PASSED" << std::endl;
    std::cout << "========================================" << std::endl;
    return 0;
}