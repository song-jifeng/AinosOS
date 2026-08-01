// Ainos AI Daemon - Thermal Monitor
// 跨平台 CPU 温度监控，为电源策略调度提供数据

use std::io::{self, BufRead};
use std::path::Path;
use std::time::Duration;
use tokio::time;
use tracing::{info, debug};

/// 温度区间
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ThermalZone {
    Cool = 0,      // < 70°C
    Warm = 1,      // 70-85°C
    Hot = 2,       // 85-95°C
    Critical = 3,  // > 95°C
}

/// 电源策略模式
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd)]
pub enum PowerMode {
    Max = 0,        // 全速: 4线程, FP32
    Balanced = 1,   // 平衡: 2线程, FP16
    Efficient = 2,  // 节能: 1线程, INT8
    Emergency = 3,  // 紧急: 1线程, INT4
}

/// 温度快照
#[derive(Debug, Clone)]
pub struct ThermalSnapshot {
    pub cpu_temp_celsius: f64,
    pub zone: ThermalZone,
    pub power_mode: PowerMode,
    pub recommended_threads: u32,
    pub sensor_available: bool,
    pub throttle_active: bool,
}

impl ThermalSnapshot {
    pub fn new() -> Self {
        Self {
            cpu_temp_celsius: 40.0,
            zone: ThermalZone::Cool,
            power_mode: PowerMode::Max,
            recommended_threads: 4,
            sensor_available: false,
            throttle_active: false,
        }
    }
}

/// 温度监控器
pub struct ThermalMonitor {
    snapshot: std::sync::Mutex<ThermalSnapshot>,
    sample_interval: Duration,
}

impl std::fmt::Debug for ThermalMonitor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let snap = self.snapshot.lock().unwrap();
        f.debug_struct("ThermalMonitor")
            .field("temp", &snap.cpu_temp_celsius)
            .field("mode", &snap.power_mode)
            .field("interval", &self.sample_interval)
            .finish()
    }
}

impl ThermalMonitor {
    pub fn new() -> Self {
        Self {
            snapshot: std::sync::Mutex::new(ThermalSnapshot::new()),
            sample_interval: Duration::from_secs(2),
        }
    }

    /// 设置采样间隔
    pub fn set_interval(&mut self, interval_ms: u64) {
        self.sample_interval = Duration::from_millis(interval_ms);
    }

    /// 获取当前温度快照
    pub fn get_snapshot(&self) -> ThermalSnapshot {
        self.snapshot.lock().unwrap().clone()
    }

    /// 获取当前电源模式
    pub fn get_power_mode(&self) -> PowerMode {
        self.snapshot.lock().unwrap().power_mode
    }

    /// 获取推荐线程数
    pub fn get_recommended_threads(&self) -> u32 {
        self.snapshot.lock().unwrap().recommended_threads
    }

    /// 启动监控循环
    pub async fn start(&self) {
        info!("[ThermalMonitor] Started (interval={:?})", self.sample_interval);
        let mut interval = time::interval(self.sample_interval);

        loop {
            interval.tick().await;
            self.check_temperature().await;
        }
    }

    /// 温度检测
    async fn check_temperature(&self) {
        let temp = match Self::read_cpu_temperature() {
            Some(t) => t,
            None => {
                // 传感器不可用，使用模拟模式
                let mut snap = self.snapshot.lock().unwrap();
                if !snap.sensor_available {
                    // 只在首次标记
                    snap.sensor_available = false;
                    debug!("[ThermalMonitor] No thermal sensor available");
                }
                return;
            }
        };

        let old_snapshot = self.snapshot.lock().unwrap().clone();
        let zone = Self::celsius_to_zone(temp);
        let mode = Self::zone_to_power_mode(zone);
        let threads = Self::power_mode_to_threads(mode);
        let throttle = mode >= PowerMode::Efficient;

        let new_snapshot = ThermalSnapshot {
            cpu_temp_celsius: temp,
            zone,
            power_mode: mode,
            recommended_threads: threads,
            sensor_available: true,
            throttle_active: throttle,
        };

        // 更新快照
        {
            let mut snap = self.snapshot.lock().unwrap();
            *snap = new_snapshot.clone();
        }

        // 检查模式变化
        if old_snapshot.power_mode != mode {
            info!(
                "[ThermalMonitor] Mode change: {:?} -> {:?} (temp={:.1}°C, threads={})",
                old_snapshot.power_mode, mode, temp, threads
            );
        }
    }

    /// 读取 CPU 温度（跨平台）
    fn read_cpu_temperature() -> Option<f64> {
        // Linux: /sys/class/thermal/thermal_zone0/temp
        let thermal_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input",
        ];

        for path in &thermal_paths {
            if Path::new(path).exists() {
                if let Ok(file) = std::fs::File::open(path) {
                    let reader = io::BufReader::new(file);
                    if let Some(Ok(line)) = reader.lines().next() {
                        if let Ok(milli) = line.trim().parse::<i32>() {
                            if milli > 0 {
                                return Some(milli as f64 / 1000.0);
                            }
                        }
                    }
                }
            }
        }

        // Windows: 尝试读取 WMI (简化处理)
        #[cfg(windows)]
        {
            // 这里可以调用 Windows API 读取温度
            // 简化: 返回 None 使用模拟模式
        }

        None
    }

    fn celsius_to_zone(temp: f64) -> ThermalZone {
        if temp >= 95.0 { ThermalZone::Critical }
        else if temp >= 85.0 { ThermalZone::Hot }
        else if temp >= 70.0 { ThermalZone::Warm }
        else { ThermalZone::Cool }
    }

    fn zone_to_power_mode(zone: ThermalZone) -> PowerMode {
        match zone {
            ThermalZone::Cool => PowerMode::Max,
            ThermalZone::Warm => PowerMode::Balanced,
            ThermalZone::Hot => PowerMode::Efficient,
            ThermalZone::Critical => PowerMode::Emergency,
        }
    }

    fn power_mode_to_threads(mode: PowerMode) -> u32 {
        match mode {
            PowerMode::Max => 4,
            PowerMode::Balanced => 2,
            PowerMode::Efficient => 1,
            PowerMode::Emergency => 1,
        }
    }
}

/// 电源模式名称
pub fn power_mode_name(mode: PowerMode) -> &'static str {
    match mode {
        PowerMode::Max => "MAX",
        PowerMode::Balanced => "BALANCED",
        PowerMode::Efficient => "EFFICIENT",
        PowerMode::Emergency => "EMERGENCY",
    }
}

/// 温度区间名称
pub fn thermal_zone_name(zone: ThermalZone) -> &'static str {
    match zone {
        ThermalZone::Cool => "COOL",
        ThermalZone::Warm => "WARM",
        ThermalZone::Hot => "HOT",
        ThermalZone::Critical => "CRITICAL",
    }
}