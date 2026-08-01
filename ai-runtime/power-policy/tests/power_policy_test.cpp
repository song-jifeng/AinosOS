// Ainos OS - Power Policy Test
// 验证电源策略调度模式的正确性
// 编译: g++ -std=c++17 -I../include power_policy_test.cpp ../power-policy/thermal_monitor.cpp ../power-policy/power_policy.cpp -o power_policy_test

#include "ainos/power_policy.h"
#include <iostream>
#include <cassert>
#include <thread>
#include <chrono>

using namespace ainos::power;

// 测试1: 默认模式检查
void test_default_mode() {
    std::cout << "=== Test 1: Default Mode ===" << std::endl;
    PowerPolicyManager ppm;
    PowerPolicyConfig config;
    config.sample_interval_ms = 100; // 快速采样
    config.cooldown_ms = 10;

    assert(ppm.Initialize(config));
    assert(ppm.Start());

    // 默认应该是 MAX 模式（或模拟温度 < 70°C）
    PrecisionMode mode = ppm.GetCurrentMode();
    std::cout << "  Initial mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::MAX || mode == PrecisionMode::BALANCED);

    std::cout << "  Threads: " << ppm.GetRecommendedThreads() << std::endl;
    std::cout << "  Precision: " << ppm.GetRecommendedPrecision() << std::endl;
    std::cout << "  Vector: " << ppm.GetRecommendedVectorWidth() << std::endl;

    ppm.Stop();
    std::cout << "  PASSED" << std::endl;
}

// 测试2: 模拟温度变化
void test_temperature_change() {
    std::cout << "=== Test 2: Temperature Change ===" << std::endl;
    PowerPolicyManager ppm;
    PowerPolicyConfig config;
    config.sample_interval_ms = 100;
    config.cooldown_ms = 10; // 快速冷却以便测试恢复

    assert(ppm.Initialize(config));
    ppm.Start();

    // 模拟低温（< 70°C，应该 MAX 模式）
    ppm.GetThermalMonitor()->SetSimulatedTemp(50.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    PrecisionMode mode = ppm.GetCurrentMode();
    std::cout << "  50°C -> Mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::MAX);
    assert(ppm.GetRecommendedThreads() == 4);

    // 模拟中温（70-85°C，应该 BALANCED 模式）
    ppm.GetThermalMonitor()->SetSimulatedTemp(75.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    mode = ppm.GetCurrentMode();
    std::cout << "  75°C -> Mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::BALANCED);
    assert(ppm.GetRecommendedThreads() == 2);

    // 模拟高温（85-95°C，应该 EFFICIENT 模式）
    ppm.GetThermalMonitor()->SetSimulatedTemp(90.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    mode = ppm.GetCurrentMode();
    std::cout << "  90°C -> Mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::EFFICIENT);
    assert(ppm.GetRecommendedThreads() == 1);

    // 模拟临界高温（> 95°C，应该 EMERGENCY 模式）
    ppm.GetThermalMonitor()->SetSimulatedTemp(98.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    mode = ppm.GetCurrentMode();
    std::cout << "  98°C -> Mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::EMERGENCY);
    assert(ppm.GetRecommendedThreads() == 1);

    // 模拟温度回落（应该恢复到 MAX）
    ppm.GetThermalMonitor()->SetSimulatedTemp(45.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(500)); // 需要等待冷却期
    mode = ppm.GetCurrentMode();
    std::cout << "  45°C -> Mode: " << PowerPolicyManager::ModeToString(mode) << std::endl;
    assert(mode == PrecisionMode::MAX);

    ppm.Stop();
    std::cout << "  PASSED" << std::endl;
}

// 测试3: 手动覆盖模式
void test_manual_override() {
    std::cout << "=== Test 3: Manual Override ===" << std::endl;
    PowerPolicyManager ppm;
    PowerPolicyConfig config;
    config.sample_interval_ms = 100;

    assert(ppm.Initialize(config));
    ppm.Start();

    // 模拟高温
    ppm.GetThermalMonitor()->SetSimulatedTemp(90.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    std::cout << "  Auto mode at 90°C: " << PowerPolicyManager::ModeToString(ppm.GetCurrentMode()) << std::endl;

    // 手动覆盖为 MAX
    ppm.OverrideMode(PrecisionMode::MAX);
    assert(ppm.GetCurrentMode() == PrecisionMode::MAX);
    std::cout << "  Override to MAX: " << PowerPolicyManager::ModeToString(ppm.GetCurrentMode()) << std::endl;

    // 温度变化不应影响手动覆盖
    ppm.GetThermalMonitor()->SetSimulatedTemp(50.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    assert(ppm.GetCurrentMode() == PrecisionMode::MAX);
    std::cout << "  Still MAX after cooldown: " << PowerPolicyManager::ModeToString(ppm.GetCurrentMode()) << std::endl;

    // 清除覆盖
    ppm.ClearOverride();
    std::cout << "  After clear override: " << PowerPolicyManager::ModeToString(ppm.GetCurrentMode()) << std::endl;

    ppm.Stop();
    std::cout << "  PASSED" << std::endl;
}

// 测试4: 策略回调
void test_policy_callback() {
    std::cout << "=== Test 4: Policy Callback ===" << std::endl;
    PowerPolicyManager ppm;
    PowerPolicyConfig config;
    config.sample_interval_ms = 100;
    config.cooldown_ms = 10; // 快速冷却

    int callback_count = 0;
    ppm.SetPolicyCallback([&callback_count](const PolicyEvent& event) {
        callback_count++;
        std::cout << "  Callback: " << PowerPolicyManager::ModeToString(event.old_mode)
                  << " -> " << PowerPolicyManager::ModeToString(event.new_mode)
                  << " at " << event.temperature << "°C" << std::endl;
    });

    assert(ppm.Initialize(config));
    ppm.Start();

    // 升温触发回调
    ppm.GetThermalMonitor()->SetSimulatedTemp(90.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    // 降温触发回调
    ppm.GetThermalMonitor()->SetSimulatedTemp(45.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    std::cout << "  Callback count: " << callback_count << std::endl;
    assert(callback_count >= 2);

    ppm.Stop();
    std::cout << "  PASSED" << std::endl;
}

int main() {
    std::cout << "============================================" << std::endl;
    std::cout << "  Ainos OS Power Policy Test Suite" << std::endl;
    std::cout << "============================================" << std::endl;
    std::cout << std::endl;

    test_default_mode();
    std::cout << std::endl;
    test_temperature_change();
    std::cout << std::endl;
    test_manual_override();
    std::cout << std::endl;
    test_policy_callback();
    std::cout << std::endl;

    std::cout << "============================================" << std::endl;
    std::cout << "  ALL TESTS PASSED!" << std::endl;
    std::cout << "============================================" << std::endl;
    return 0;
}