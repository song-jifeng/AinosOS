// Ainos OS - Power Policy Manager Implementation
// 管理电源策略，根据温度自动调整 AI 推理精度和并行度

#include "ainos/power_policy.h"
#include <iostream>
#include <algorithm>

namespace ainos {
namespace power {

// 默认配置
PowerPolicyConfig::PowerPolicyConfig()
    : cool_warm_threshold(70.0)
    , warm_hot_threshold(85.0)
    , hot_critical_threshold(95.0)
    , sample_interval_ms(2000)
    , cooldown_ms(30000)    // 降级后至少保持 30 秒
    , auto_recover(true)
{
    // MAX 模式: 全速
    modes[0] = { 4, "AVX-256", "FP32", 8, true };
    // BALANCED 模式: 平衡
    modes[1] = { 2, "AVX-128", "FP16", 4, true };
    // EFFICIENT 模式: 节能
    modes[2] = { 1, "NEON/SCALAR", "INT8", 2, false };
    // EMERGENCY 模式: 紧急
    modes[3] = { 1, "SCALAR", "INT4", 1, false };
}

PowerPolicyManager::PowerPolicyManager()
    : current_mode_(PrecisionMode::MAX)
    , override_mode_(PrecisionMode::MAX)
    , has_override_(false)
    , initialized_(false)
    , running_(false)
    , last_downgrade_ms_(0)
{
}

PowerPolicyManager::~PowerPolicyManager() {
    Stop();
}

bool PowerPolicyManager::Initialize(const PowerPolicyConfig& config) {
    config_ = config;

    // 初始化温度监控器
    if (!thermal_monitor_.Initialize(config_.sample_interval_ms)) {
        std::cerr << "[PowerPolicy] Failed to initialize thermal monitor" << std::endl;
        return false;
    }

    // 设置温度阈值
    thermal_monitor_.SetThresholds(
        config_.cool_warm_threshold,
        config_.warm_hot_threshold,
        config_.hot_critical_threshold
    );

    // 注册温度变化回调
    thermal_monitor_.SetCallback([this](const ThermalSnapshot& snap, ThermalZone old_zone) {
        OnThermalChange(snap, old_zone);
    });

    // 初始化模式
    current_mode_ = CalculateMode(thermal_monitor_.GetCurrentZone());

    initialized_ = true;
    std::cout << "[PowerPolicy] Initialized (mode=" << ModeToString(current_mode_)
              << ", temp=" << thermal_monitor_.GetCurrentSnapshot().cpu_temp << "°C)" << std::endl;
    return true;
}

bool PowerPolicyManager::Start() {
    if (!initialized_) {
        std::cerr << "[PowerPolicy] Not initialized" << std::endl;
        return false;
    }

    running_ = true;
    thermal_monitor_.Start();
    std::cout << "[PowerPolicy] Started" << std::endl;
    return true;
}

void PowerPolicyManager::Stop() {
    if (running_) {
        thermal_monitor_.Stop();
        running_ = false;
        std::cout << "[PowerPolicy] Stopped" << std::endl;
    }
}

PrecisionMode PowerPolicyManager::GetCurrentMode() const {
    if (has_override_) return override_mode_;
    return current_mode_;
}

ThermalZone PowerPolicyManager::GetCurrentZone() const {
    return thermal_monitor_.GetCurrentZone();
}

double PowerPolicyManager::GetCurrentTemperature() const {
    return thermal_monitor_.GetCurrentSnapshot().cpu_temp;
}

int PowerPolicyManager::GetRecommendedThreads() const {
    PrecisionMode mode = GetCurrentMode();
    return config_.modes[static_cast<int>(mode)].num_threads;
}

std::string PowerPolicyManager::GetRecommendedVectorWidth() const {
    PrecisionMode mode = GetCurrentMode();
    return config_.modes[static_cast<int>(mode)].vector_width;
}

std::string PowerPolicyManager::GetRecommendedPrecision() const {
    PrecisionMode mode = GetCurrentMode();
    return config_.modes[static_cast<int>(mode)].precision;
}

void PowerPolicyManager::SetPolicyCallback(PolicyCallback cb) {
    policy_callback_ = cb;
}

void PowerPolicyManager::OverrideMode(PrecisionMode mode) {
    PrecisionMode old_mode = GetCurrentMode();
    override_mode_ = mode;
    has_override_ = true;

    ThermalZone zone = GetCurrentZone();
    std::cout << "[PowerPolicy] Manual override: " << ModeToString(old_mode)
              << " -> " << ModeToString(mode) << " (temp=" << GetCurrentTemperature() << "°C)" << std::endl;

    // 触发策略事件
    if (old_mode != mode && policy_callback_) {
        PolicyEvent event;
        event.old_zone = zone;
        event.new_zone = zone;
        event.old_mode = old_mode;
        event.new_mode = mode;
        event.temperature = GetCurrentTemperature();
        event.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        policy_callback_(event);
    }
}

void PowerPolicyManager::ClearOverride() {
    if (has_override_) {
        PrecisionMode old_mode = override_mode_;
        has_override_ = false;
        current_mode_ = CalculateMode(GetCurrentZone());

        std::cout << "[PowerPolicy] Override cleared, auto mode restored: "
                  << ModeToString(old_mode) << " -> " << ModeToString(current_mode_)
                  << " (temp=" << GetCurrentTemperature() << "°C)" << std::endl;

        if (old_mode != current_mode_ && policy_callback_) {
            PolicyEvent event;
            event.old_zone = GetCurrentZone();
            event.new_zone = GetCurrentZone();
            event.old_mode = old_mode;
            event.new_mode = current_mode_;
            event.temperature = GetCurrentTemperature();
            event.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            policy_callback_(event);
        }
    }
}

PrecisionMode PowerPolicyManager::CalculateMode(ThermalZone zone) const {
    switch (zone) {
        case ThermalZone::COOL:     return PrecisionMode::MAX;
        case ThermalZone::WARM:     return PrecisionMode::BALANCED;
        case ThermalZone::HOT:      return PrecisionMode::EFFICIENT;
        case ThermalZone::CRITICAL: return PrecisionMode::EMERGENCY;
        default:                    return PrecisionMode::MAX;
    }
}

void PowerPolicyManager::OnThermalChange(const ThermalSnapshot& snapshot, ThermalZone old_zone) {
    if (has_override_) {
        // 手动覆盖模式下，仅记录日志，不自动调整
        std::cout << "[PowerPolicy] (override active, ignoring auto-switch) temp="
                  << snapshot.cpu_temp << "°C" << std::endl;
        return;
    }

    PrecisionMode old_mode = current_mode_;
    PrecisionMode new_mode = CalculateMode(snapshot.zone);

    uint64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    // 降级保护：检查是否在冷却期
    if (new_mode > old_mode) {
        // 温度升高，需要降级
        current_mode_ = new_mode;
        last_downgrade_ms_ = now_ms;

        std::cout << "[PowerPolicy] DOWNGRADE: " << ModeToString(old_mode)
                  << " -> " << ModeToString(new_mode)
                  << " (temp=" << snapshot.cpu_temp << "°C, zone="
                  << ZoneToString(snapshot.zone) << ")" << std::endl;
    } else if (new_mode < old_mode && config_.auto_recover) {
        // 温度降低，尝试恢复（需检查冷却期）
        uint64_t elapsed = now_ms - last_downgrade_ms_;
        if (elapsed >= static_cast<uint64_t>(config_.cooldown_ms)) {
            current_mode_ = new_mode;

            std::cout << "[PowerPolicy] UPGRADE: " << ModeToString(old_mode)
                      << " -> " << ModeToString(new_mode)
                      << " (temp=" << snapshot.cpu_temp << "°C, cooldown="
                      << elapsed << "ms)" << std::endl;
        } else {
            std::cout << "[PowerPolicy] (cooldown active, holding " << ModeToString(old_mode)
                      << " for " << (config_.cooldown_ms - elapsed) / 1000 << "s more)" << std::endl;
            return;
        }
    }

    // 触发策略回调
    if (old_mode != current_mode_ && policy_callback_) {
        PolicyEvent event;
        event.old_zone = old_zone;
        event.new_zone = snapshot.zone;
        event.old_mode = old_mode;
        event.new_mode = current_mode_;
        event.temperature = snapshot.cpu_temp;
        event.timestamp_ms = now_ms;
        policy_callback_(event);
    }
}

const char* PowerPolicyManager::ModeToString(PrecisionMode mode) {
    switch (mode) {
        case PrecisionMode::MAX:        return "MAX";
        case PrecisionMode::BALANCED:   return "BALANCED";
        case PrecisionMode::EFFICIENT:  return "EFFICIENT";
        case PrecisionMode::EMERGENCY:  return "EMERGENCY";
        default:                        return "UNKNOWN";
    }
}

const char* PowerPolicyManager::ZoneToString(ThermalZone zone) {
    switch (zone) {
        case ThermalZone::COOL:     return "COOL";
        case ThermalZone::WARM:     return "WARM";
        case ThermalZone::HOT:      return "HOT";
        case ThermalZone::CRITICAL: return "CRITICAL";
        default:                    return "UNKNOWN";
    }
}

} // namespace power
} // namespace ainos