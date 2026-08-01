// Ainos OS - Thermal Monitor Header
// 实时监控 CPU 温度，为电源策略调度提供数据

#ifndef AINOS_THERMAL_MONITOR_H
#define AINOS_THERMAL_MONITOR_H

#include <string>
#include <thread>
#include <chrono>
#include <mutex>
#include <functional>
#include <cstdint>

namespace ainos {
namespace power {

// 温度阈值区间
enum class ThermalZone {
    COOL    = 0,  // < 70°C: 全速模式
    WARM    = 1,  // 70-85°C: 平衡模式
    HOT     = 2,  // > 85°C: 节能模式
    CRITICAL = 3, // > 95°C: 紧急降频
};

// 当前温度快照
struct ThermalSnapshot {
    double cpu_temp;          // 当前 CPU 温度 (°C)
    ThermalZone zone;         // 温度区间
    double gpu_temp;          // GPU 温度（如有）
    uint64_t timestamp_ms;    // 采样时间戳
    bool sensor_available;    // 传感器是否可用
};

// 温度变化回调
using ThermalCallback = std::function<void(const ThermalSnapshot&, ThermalZone old_zone)>;

class ThermalMonitor {
public:
    ThermalMonitor();
    ~ThermalMonitor();

    // 初始化（指定采样间隔，默认 2 秒）
    bool Initialize(int sample_interval_ms = 2000);

    // 启动监控线程
    bool Start();

    // 停止监控
    void Stop();

    // 获取当前温度快照
    ThermalSnapshot GetCurrentSnapshot() const;

    // 获取当前温度区间
    ThermalZone GetCurrentZone() const;

    // 设置温度变化回调
    void SetCallback(ThermalCallback cb);

    // 设置温度阈值（自定义）
    void SetThresholds(double cool_warm, double warm_hot, double hot_critical);

    // 手动设置温度（用于无传感器环境或测试）
    void SetSimulatedTemp(double temp_celsius);

    // 是否正在运行
    bool IsRunning() const { return running_; }

private:
    // 从系统读取 CPU 温度
    double ReadCpuTemperature();

    // 计算温度区间
    ThermalZone CalculateZone(double temp_celsius) const;

    // 监控线程函数
    void MonitorThread();

    // 内容
    mutable std::mutex mutex_;
    bool initialized_;
    bool running_;
    int sample_interval_ms_;
    ThermalSnapshot current_snapshot_;
    ThermalCallback callback_;

    // 阈值配置
    double threshold_cool_warm_;    // 70°C
    double threshold_warm_hot_;     // 85°C
    double threshold_hot_critical_; // 95°C

    // 模拟模式
    bool simulated_mode_;
    double simulated_temp_;

    // 线程
    std::thread monitor_thread_;
};

} // namespace power
} // namespace ainos

#endif // AINOS_THERMAL_MONITOR_H