// Ainos AI Daemon - Thermal Monitor
// 跨平台 CPU 温度监控，自适应轮询间隔
// 温度变化剧烈时加快采样 (0.5s-1s)，稳定时降低采样 (5s-10s)
// Linux 上通过 inotify 监听 thermal sysfs 实现事件驱动

use std::collections::VecDeque;
use std::io::{self, BufRead};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::time;
use tracing::{info, debug};
#[cfg(target_os = "linux")]
use tracing::warn;

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

/// 自适应温控配置
#[derive(Debug, Clone)]
pub struct AdaptiveThermalConfig {
    /// 最小轮询间隔 (毫秒) - 温度剧烈变化时
    pub min_interval_ms: u64,
    /// 最大轮询间隔 (毫秒) - 温度稳定时
    pub max_interval_ms: u64,
    /// 默认轮询间隔 (毫秒)
    pub default_interval_ms: u64,
    /// 温度变化率阈值 (°C/s) - 超过此值视为剧烈变化
    pub high_change_rate_threshold: f64,
    /// 温度变化率阈值 (°C/s) - 低于此值视为稳定
    pub low_change_rate_threshold: f64,
    /// 用于计算变化率的历史采样数
    pub history_size: usize,
}

impl Default for AdaptiveThermalConfig {
    fn default() -> Self {
        Self {
            min_interval_ms: 500,
            max_interval_ms: 10000,
            default_interval_ms: 2000,
            high_change_rate_threshold: 2.0,
            low_change_rate_threshold: 0.5,
            history_size: 5,
        }
    }
}

/// 温度监控器
pub struct ThermalMonitor {
    snapshot: std::sync::Mutex<ThermalSnapshot>,
    config: AdaptiveThermalConfig,
    temp_history: std::sync::Mutex<VecDeque<(f64, std::time::Instant)>>,
    last_interval: std::sync::Mutex<Duration>,
    #[cfg(target_os = "linux")]
    inotify_fd: std::sync::Mutex<Option<std::os::unix::io::RawFd>>,
}

impl std::fmt::Debug for ThermalMonitor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let snap = self.snapshot.lock().unwrap();
        let interval = self.last_interval.lock().unwrap();
        f.debug_struct("ThermalMonitor")
            .field("temp", &snap.cpu_temp_celsius)
            .field("mode", &snap.power_mode)
            .field("interval", &*interval)
            .finish()
    }
}

impl ThermalMonitor {
    pub fn new() -> Self {
        Self {
            snapshot: std::sync::Mutex::new(ThermalSnapshot::new()),
            config: AdaptiveThermalConfig::default(),
            temp_history: std::sync::Mutex::new(VecDeque::with_capacity(10)),
            last_interval: std::sync::Mutex::new(Duration::from_millis(2000)),
            #[cfg(target_os = "linux")]
            inotify_fd: std::sync::Mutex::new(None),
        }
    }

    /// 使用自定义配置创建监控器
    pub fn with_config(config: AdaptiveThermalConfig) -> Self {
        Self {
            snapshot: std::sync::Mutex::new(ThermalSnapshot::new()),
            config: config.clone(),
            temp_history: std::sync::Mutex::new(VecDeque::with_capacity(10)),
            last_interval: std::sync::Mutex::new(Duration::from_millis(config.default_interval_ms)),
            #[cfg(target_os = "linux")]
            inotify_fd: std::sync::Mutex::new(None),
        }
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

    /// 获取当前采样间隔
    pub fn get_current_interval(&self) -> Duration {
        *self.last_interval.lock().unwrap()
    }

    /// 计算自适应轮询间隔
    /// 根据温度变化率动态调整: 剧烈变化时缩短, 稳定时延长
    fn compute_adaptive_interval(&self, current_temp: f64) -> Duration {
        let cfg = &self.config;
        let now = std::time::Instant::now();

        // 记录温度历史
        {
            let mut history = self.temp_history.lock().unwrap();
            history.push_back((current_temp, now));
            while history.len() > cfg.history_size + 2 {
                history.pop_front();
            }
        }

        // 计算温度变化率 (滑动窗口)
        let rate = {
            let history = self.temp_history.lock().unwrap();
            if history.len() < 2 {
                return Duration::from_millis(cfg.default_interval_ms);
            }

            let newest = history.back().unwrap();
            let oldest = history.front().unwrap();
            let dt = newest.1.duration_since(oldest.1).as_secs_f64();
            if dt < 0.01 {
                return Duration::from_millis(cfg.default_interval_ms);
            }
            let delta_temp = (newest.0 - oldest.0).abs();
            delta_temp / dt
        };

        // 根据变化率决定间隔
        let interval_ms = if rate > cfg.high_change_rate_threshold {
            // 剧烈变化: 快速采样
            cfg.min_interval_ms
        } else if rate < cfg.low_change_rate_threshold {
            // 稳定: 降低采样
            cfg.max_interval_ms
        } else {
            // 中等变化: 线性插值 (max -> min 随着 rate 增加)
            let ratio = (rate - cfg.low_change_rate_threshold)
                / (cfg.high_change_rate_threshold - cfg.low_change_rate_threshold);
            let range = (cfg.max_interval_ms - cfg.min_interval_ms) as f64;
            (cfg.max_interval_ms as f64 - ratio * range) as u64
        };

        let interval = Duration::from_millis(interval_ms.clamp(cfg.min_interval_ms, cfg.max_interval_ms));

        // 更新当前间隔
        {
            let mut last = self.last_interval.lock().unwrap();
            *last = interval;
        }

        debug!(
            "[ThermalMonitor] Adaptive interval: rate={:.2}°C/s, interval={:?}",
            rate, interval
        );

        interval
    }

    /// 启动监控循环 (自适应轮询 + 事件驱动)
    pub async fn start(self: Arc<Self>) {
        let mut interval_dur = Duration::from_millis(self.config.default_interval_ms);

        // 在 Linux 上尝试设置 inotify 事件监听
        #[cfg(target_os = "linux")]
        let inotify_notify = self.try_setup_inotify();

        info!(
            "[ThermalMonitor] Started adaptive polling (min={:?}, max={:?})",
            Duration::from_millis(self.config.min_interval_ms),
            Duration::from_millis(self.config.max_interval_ms),
        );

        let mut interval = time::interval(interval_dur);
        interval.tick().await; // 立即执行第一次采样

        loop {
            // 等待轮询间隔或 inotify 事件
            // 使用 notify.notified() 创建新 future 以支持重复使用
            #[cfg(target_os = "linux")]
            {
                if let Some(ref notify) = inotify_notify {
                    tokio::select! {
                        _ = interval.tick() => {
                            self.check_temperature().await;
                        }
                        _ = notify.notified() => {
                            self.check_temperature().await;
                        }
                    }
                } else {
                    interval.tick().await;
                    self.check_temperature().await;
                }
            }

            #[cfg(not(target_os = "linux"))]
            {
                interval.tick().await;
                self.check_temperature().await;
            }

            // 动态调整下一次轮询间隔
            let new_interval = {
                let snap = self.snapshot.lock().unwrap();
                self.compute_adaptive_interval(snap.cpu_temp_celsius)
            };

            // 间隔变化超过 100ms 时才重置计时器，避免频繁重建
            if (new_interval.as_millis() as i64 - interval_dur.as_millis() as i64).abs() > 100 {
                interval_dur = new_interval;
                interval = time::interval(interval_dur);
                interval.tick().await; // 重置计时器，避免突发捕获
            }
        }
    }

    /// 尝试设置 inotify 监听 (Linux)
    /// 成功时返回 Notify 信号，用于事件驱动唤醒
    #[cfg(target_os = "linux")]
    fn try_setup_inotify(self: &Arc<Self>) -> Option<Arc<tokio::sync::Notify>> {
        let thermal_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
            "/sys/class/hwmon/hwmon0/temp1_input",
            "/sys/class/hwmon/hwmon1/temp1_input",
        ];

        for path in &thermal_paths {
            if !Path::new(path).exists() {
                continue;
            }

            let cpath = match std::ffi::CString::new(*path) {
                Ok(p) => p,
                Err(_) => continue,
            };

            let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK) };
            if fd < 0 {
                warn!(
                    "[ThermalMonitor] Failed to create inotify fd: {}",
                    std::io::Error::last_os_error()
                );
                continue;
            }

            let wd = unsafe { libc::inotify_add_watch(fd, cpath.as_ptr(), libc::IN_MODIFY) };
            if wd < 0 {
                unsafe {
                    libc::close(fd);
                }
                debug!(
                    "[ThermalMonitor] inotify not available for {}: {}",
                    path,
                    std::io::Error::last_os_error()
                );
                continue;
            }

            // 保存 inotify fd
            {
                let mut fd_slot = self.inotify_fd.lock().unwrap();
                *fd_slot = Some(fd);
            }

            let notify = Arc::new(tokio::sync::Notify::new());
            let notify_clone = notify.clone();

            // 启动后台阻塞任务读取 inotify 事件
            tokio::task::spawn_blocking(move || {
                Self::inotify_event_loop(fd, notify_clone);
            });

            info!("[ThermalMonitor] inotify watch established on {}", path);
            return Some(notify);
        }

        warn!("[ThermalMonitor] inotify not available, falling back to pure polling");
        None
    }

    /// inotify 事件循环 (在阻塞线程中运行)
    #[cfg(target_os = "linux")]
    fn inotify_event_loop(fd: std::os::unix::io::RawFd, notify: Arc<tokio::sync::Notify>) {
        let mut buffer = [0u8; 4096];
        loop {
            // 使用非阻塞读，无事件时短暂休眠
            let result = unsafe {
                libc::read(
                    fd,
                    buffer.as_mut_ptr() as *mut libc::c_void,
                    buffer.len(),
                )
            };

            match result {
                -1 => {
                    let err = std::io::Error::last_os_error();
                    match err.raw_os_error() {
                        Some(libc::EINTR) => continue,
                        Some(libc::EAGAIN) | Some(libc::EWOULDBLOCK) => {
                            // 无事件，短暂休眠后重试
                            std::thread::sleep(Duration::from_millis(50));
                            continue;
                        }
                        _ => {
                            warn!("[ThermalMonitor] inotify read error: {}", err);
                            break;
                        }
                    }
                }
                0 => {
                    // EOF
                    break;
                }
                _ => {
                    // 有温度变化事件，通知主循环
                    notify.notify_one();
                }
            }
        }

        // 清理 inotify fd
        unsafe {
            libc::close(fd);
        }
    }

    /// 温度检测
    async fn check_temperature(&self) {
        let temp = match Self::read_cpu_temperature() {
            Some(t) => t,
            None => {
                let mut snap = self.snapshot.lock().unwrap();
                if !snap.sensor_available {
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

    pub(crate) fn celsius_to_zone(temp: f64) -> ThermalZone {
        if temp >= 95.0 {
            ThermalZone::Critical
        } else if temp >= 85.0 {
            ThermalZone::Hot
        } else if temp >= 70.0 {
            ThermalZone::Warm
        } else {
            ThermalZone::Cool
        }
    }

    pub(crate) fn zone_to_power_mode(zone: ThermalZone) -> PowerMode {
        match zone {
            ThermalZone::Cool => PowerMode::Max,
            ThermalZone::Warm => PowerMode::Balanced,
            ThermalZone::Hot => PowerMode::Efficient,
            ThermalZone::Critical => PowerMode::Emergency,
        }
    }

    pub(crate) fn power_mode_to_threads(mode: PowerMode) -> u32 {
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