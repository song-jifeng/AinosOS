// Ainos OS - Power Policy Manager Header
// 电源策略管理：根据温度自动调整 AI 推理精度和并行度

#ifndef AINOS_POWER_POLICY_H
#define AINOS_POWER_POLICY_H

#include "thermal_monitor.h"
#include <string>
#include <memory>
#include <functional>

namespace ainos {
namespace power {

// 推理精度模式
enum class PrecisionMode {
    MAX     = 0,  // 全速模式: AVX-256, 4核推理, FP32
    BALANCED = 1, // 平衡模式: AVX-128, 2核推理, FP16
    EFFICIENT = 2,// 节能模式: NEON/标量, 1核推理, INT8
    EMERGENCY = 3,// 紧急模式: 仅标量, 1核推理, INT4
};

// 电源策略配置
struct PowerPolicyConfig {
    // 温度阈值
    double cool_warm_threshold;      // 默认 70°C
    double warm_hot_threshold;       // 默认 85°C
    double hot_critical_threshold;   // 默认 95°C

    // 各模式配置
    struct {
        int num_threads;             // 推理线程数
        const char* vector_width;    // 向量指令宽度
        const char* precision;       // 精度等级
        int batch_size;              // 批处理大小
        bool use_kv_cache;           // 是否使用 KV 缓存
    } modes[4];                      // MAX, BALANCED, EFFICIENT, EMERGENCY

    // 温控行为
    int sample_interval_ms;          // 采样间隔
    int cooldown_ms;                 // 降级后最低持续时间
    bool auto_recover;               // 温度回落后自动恢复

    PowerPolicyConfig();
};

// 电源策略事件
struct PolicyEvent {
    ThermalZone old_zone;
    ThermalZone new_zone;
    PrecisionMode old_mode;
    PrecisionMode new_mode;
    double temperature;
    uint64_t timestamp_ms;
};

// 策略变更回调
using PolicyCallback = std::function<void(const PolicyEvent& event)>;

class PowerPolicyManager {
public:
    PowerPolicyManager();
    ~PowerPolicyManager();

    // 初始化
    bool Initialize(const PowerPolicyConfig& config = PowerPolicyConfig());

    // 启动策略监控
    bool Start();

    // 停止
    void Stop();

    // 获取当前精度模式
    PrecisionMode GetCurrentMode() const;

    // 获取当前温度区间
    ThermalZone GetCurrentZone() const;

    // 获取当前温度
    double GetCurrentTemperature() const;

    // 获取推荐的推理线程数
    int GetRecommendedThreads() const;

    // 获取推荐的向量指令宽度
    std::string GetRecommendedVectorWidth() const;

    // 获取推荐的精度
    std::string GetRecommendedPrecision() const;

    // 获取完整配置
    const PowerPolicyConfig& GetConfig() const { return config_; }

    // 设置策略变更回调
    void SetPolicyCallback(PolicyCallback cb);

    // 手动设置模式（覆盖自动温控）
    void OverrideMode(PrecisionMode mode);

    // 清除手动覆盖，恢复自动温控
    void ClearOverride();

    // 获取底层温度监控器
    ThermalMonitor* GetThermalMonitor() { return &thermal_monitor_; }

    // 获取当前模式名称
    static const char* ModeToString(PrecisionMode mode);

    // 获取温度区间名称
    static const char* ZoneToString(ThermalZone zone);

private:
    // 根据温度区间计算精度模式
    PrecisionMode CalculateMode(ThermalZone zone) const;

    // 温度变化回调
    void OnThermalChange(const ThermalSnapshot& snapshot, ThermalZone old_zone);

    // 内部状态
    ThermalMonitor thermal_monitor_;
    PowerPolicyConfig config_;
    PrecisionMode current_mode_;
    PrecisionMode override_mode_;
    bool has_override_;
    bool initialized_;
    bool running_;
    PolicyCallback policy_callback_;

    // 降级时间追踪
    uint64_t last_downgrade_ms_;
};

} // namespace power
} // namespace ainos

#endif // AINOS_POWER_POLICY_H