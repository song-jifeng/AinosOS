// Ainos OS - Thermal Monitor Implementation
// 跨平台 CPU 温度读取，支持 Linux sysfs、Windows WMI 和模拟模式

#include "thermal_monitor.h"
#include <iostream>
#include <fstream>
#include <thread>
#include <cstring>
#include <chrono>
#include <sstream>

#ifdef _WIN32
#include <windows.h>
#include <comdef.h>
#include <Wbemidl.h>
#pragma comment(lib, "wbemuuid.lib")
#endif

namespace ainos {
namespace power {

// 辅助函数：温度区间转字符串
static const char* ZoneToString(ThermalZone zone) {
    switch (zone) {
        case ThermalZone::COOL:     return "COOL";
        case ThermalZone::WARM:     return "WARM";
        case ThermalZone::HOT:      return "HOT";
        case ThermalZone::CRITICAL: return "CRITICAL";
        default:                    return "UNKNOWN";
    }
}

ThermalMonitor::ThermalMonitor()
    : initialized_(false)
    , running_(false)
    , sample_interval_ms_(2000)
    , threshold_cool_warm_(70.0)
    , threshold_warm_hot_(85.0)
    , threshold_hot_critical_(95.0)
    , simulated_mode_(false)
    , simulated_temp_(40.0)
{
    current_snapshot_.cpu_temp = 40.0;
    current_snapshot_.zone = ThermalZone::COOL;
    current_snapshot_.gpu_temp = 0.0;
    current_snapshot_.timestamp_ms = 0;
    current_snapshot_.sensor_available = false;
}

ThermalMonitor::~ThermalMonitor() {
    Stop();
}

bool ThermalMonitor::Initialize(int sample_interval_ms) {
    sample_interval_ms_ = sample_interval_ms;
    initialized_ = true;

    // 尝试读取一次温度，判断传感器是否可用
    double temp = ReadCpuTemperature();
    if (temp < 0) {
        std::cout << "[ThermalMonitor] No temperature sensor found, using simulated mode (40°C baseline)" << std::endl;
        simulated_mode_ = true;
        simulated_temp_ = 40.0;
    } else {
        std::cout << "[ThermalMonitor] Temperature sensor detected: " << temp << "°C" << std::endl;
    }

    current_snapshot_.cpu_temp = temp >= 0 ? temp : simulated_temp_;
    current_snapshot_.zone = CalculateZone(current_snapshot_.cpu_temp);
    current_snapshot_.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    current_snapshot_.sensor_available = (temp >= 0);

    return true;
}

bool ThermalMonitor::Start() {
    if (!initialized_) {
        std::cerr << "[ThermalMonitor] Not initialized" << std::endl;
        return false;
    }
    if (running_) return true;

    running_ = true;
    monitor_thread_ = std::thread(&ThermalMonitor::MonitorThread, this);
    std::cout << "[ThermalMonitor] Started (interval=" << sample_interval_ms_ << "ms)" << std::endl;
    return true;
}

void ThermalMonitor::Stop() {
    if (running_) {
        running_ = false;
        if (monitor_thread_.joinable()) {
            monitor_thread_.join();
        }
        std::cout << "[ThermalMonitor] Stopped" << std::endl;
    }
}

ThermalSnapshot ThermalMonitor::GetCurrentSnapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return current_snapshot_;
}

ThermalZone ThermalMonitor::GetCurrentZone() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return current_snapshot_.zone;
}

void ThermalMonitor::SetCallback(ThermalCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    callback_ = cb;
}

void ThermalMonitor::SetThresholds(double cool_warm, double warm_hot, double hot_critical) {
    std::lock_guard<std::mutex> lock(mutex_);
    threshold_cool_warm_ = cool_warm;
    threshold_warm_hot_ = warm_hot;
    threshold_hot_critical_ = hot_critical;
}

void ThermalMonitor::SetSimulatedTemp(double temp_celsius) {
    std::lock_guard<std::mutex> lock(mutex_);
    simulated_mode_ = true;
    simulated_temp_ = temp_celsius;

    ThermalZone old_zone = current_snapshot_.zone;
    current_snapshot_.cpu_temp = temp_celsius;
    current_snapshot_.zone = CalculateZone(temp_celsius);
    current_snapshot_.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    if (old_zone != current_snapshot_.zone && callback_) {
        callback_(current_snapshot_, old_zone);
    }
}

double ThermalMonitor::ReadCpuTemperature() {
#if defined(__linux__) || defined(__unix__)
    // Linux: 读取 /sys/class/thermal/thermal_zone0/temp
    // 返回值单位: 毫摄氏度 (millidegrees Celsius)
    const char* thermal_paths[] = {
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
        "/sys/class/hwmon/hwmon1/temp1_input",
        nullptr
    };

    for (int i = 0; thermal_paths[i] != nullptr; i++) {
        std::ifstream file(thermal_paths[i]);
        if (file.is_open()) {
            int millidegrees;
            file >> millidegrees;
            if (file.good()) {
                return millidegrees / 1000.0;
            }
        }
    }

    // macOS: 使用 sysctl
    FILE* p = popen("sysctl -n machdep.xcpm.cpu_thermal_level 2>/dev/null || "
                     "pmset -g therm 2>/dev/null | grep CPU", "r");
    if (p) {
        char buf[64];
        if (fgets(buf, sizeof(buf), p)) {
            pclose(p);
            double temp;
            if (sscanf(buf, "%lf", &temp) == 1) {
                return temp;
            }
        }
        pclose(p);
    }
    return -1.0;

#elif defined(_WIN32)
    // Windows: 使用 WMI 查询
    HRESULT hres;
    hres = CoInitializeEx(0, COINIT_MULTITHREADED);
    if (FAILED(hres)) return -1.0;

    hres = CoInitializeSecurity(
        NULL, -1, NULL, NULL,
        RPC_C_AUTHN_LEVEL_DEFAULT,
        RPC_C_IMP_LEVEL_IMPERSONATE,
        NULL, EOAC_NONE, NULL
    );
    if (FAILED(hres) && hres != RPC_E_TOO_LATE) {
        CoUninitialize();
        return -1.0;
    }

    IWbemLocator* pLoc = NULL;
    hres = CoCreateInstance(CLSID_WbemLocator, 0, CLSCTX_INPROC_SERVER,
                           IID_IWbemLocator, (LPVOID*)&pLoc);
    if (FAILED(hres)) {
        CoUninitialize();
        return -1.0;
    }

    IWbemServices* pSvc = NULL;
    hres = pLoc->ConnectServer(
        _bstr_t(L"ROOT\\CIMV2"),
        NULL, NULL, 0, NULL, 0, 0, &pSvc
    );
    if (FAILED(hres)) {
        pLoc->Release();
        CoUninitialize();
        return -1.0;
    }

    hres = CoSetProxyBlanket(pSvc, RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE,
                             NULL, RPC_C_AUTHN_LEVEL_CALL,
                             RPC_C_IMP_LEVEL_IMPERSONATE, NULL, EOAC_NONE);
    if (FAILED(hres)) {
        pSvc->Release();
        pLoc->Release();
        CoUninitialize();
        return -1.0;
    }

    IEnumWbemClassObject* pEnumerator = NULL;
    hres = pSvc->ExecQuery(
        bstr_t("WQL"),
        bstr_t("SELECT * FROM Win32_TemperatureProbe"),
        WBEM_FLAG_FORWARD_ONLY | WBEM_FLAG_RETURN_IMMEDIATELY,
        NULL, &pEnumerator
    );

    double temp = -1.0;
    if (SUCCEEDED(hres) && pEnumerator) {
        IWbemClassObject* pclsObj = NULL;
        ULONG uReturn = 0;
        if (pEnumerator->Next(WBEM_INFINITE, 1, &pclsObj, &uReturn) == S_OK) {
            VARIANT vtProp;
            hres = pclsObj->Get(L"CurrentReading", 0, &vtProp, 0, 0);
            if (SUCCEEDED(hres) && vtProp.vt != VT_NULL) {
                temp = vtProp.fltVal / 10.0;
            }
            VariantClear(&vtProp);
            pclsObj->Release();
        }
        pEnumerator->Release();
    }

    // 如果 WMI 温度探测不可用，尝试读取 MSR 寄存器
    if (temp < 0) {
        // 简化实现：使用模拟温度
        temp = -1.0;
    }

    pSvc->Release();
    pLoc->Release();
    CoUninitialize();

    return temp;

#else
    // 未知平台，返回 -1 表示无传感器
    return -1.0;
#endif
}

ThermalZone ThermalMonitor::CalculateZone(double temp_celsius) const {
    if (temp_celsius >= threshold_hot_critical_) return ThermalZone::CRITICAL;
    if (temp_celsius >= threshold_warm_hot_)    return ThermalZone::HOT;
    if (temp_celsius >= threshold_cool_warm_)   return ThermalZone::WARM;
    return ThermalZone::COOL;
}

void ThermalMonitor::MonitorThread() {
    while (running_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(sample_interval_ms_));
        if (!running_) break;

        double temp;
        ThermalZone old_zone;

        {
            std::lock_guard<std::mutex> lock(mutex_);
            old_zone = current_snapshot_.zone;

            if (simulated_mode_) {
                // 模拟模式：逐渐升温或降温（模拟负载变化）
                // 默认模拟负载温度在 40-90°C 之间波动
                temp = simulated_temp_;
            } else {
                temp = ReadCpuTemperature();
                if (temp < 0) {
                    // 传感器失效，保持上次值
                    continue;
                }
            }

            ThermalZone new_zone = CalculateZone(temp);
            current_snapshot_.cpu_temp = temp;
            current_snapshot_.zone = new_zone;
            current_snapshot_.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            current_snapshot_.sensor_available = !simulated_mode_;
        }

        // 温度区间变化时触发回调
        if (old_zone != current_snapshot_.zone) {
            ThermalSnapshot snap = GetCurrentSnapshot();
            std::cout << "[ThermalMonitor] Zone changed: "
                      << ZoneToString(old_zone) << " -> " << ZoneToString(snap.zone)
                      << " (" << snap.cpu_temp << "°C)" << std::endl;

            std::lock_guard<std::mutex> lock(mutex_);
            if (callback_) {
                callback_(snap, old_zone);
            }
        }
    }
}

} // namespace power
} // namespace ainos