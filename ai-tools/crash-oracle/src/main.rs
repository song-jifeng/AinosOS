// Crash Oracle - 崩溃预测器
// 监控系统指标，预测即将发生的崩溃

use clap::Parser;
use std::collections::VecDeque;

#[derive(Parser)]
#[command(name = "crash-oracle", version, about = "Predictive crash detection")]
struct Cli {
    /// 监控间隔 (秒)
    #[arg(short, long, default_value = "5")]
    interval: u64,

    /// 运行时长
    #[arg(short, long, default_value = "0")]
    duration: u64,

    /// 输出 JSON
    #[arg(short, long)]
    json: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    println!("[crash-oracle] Crash Oracle started");
    println!("[crash-oracle] Interval: {}s", cli.interval);

    let mut predictor = Predictor::new();

    let start = std::time::Instant::now();
    let max_duration = if cli.duration > 0 {
        std::time::Duration::from_secs(cli.duration)
    } else {
        std::time::Duration::MAX
    };

    while start.elapsed() < max_duration {
        // 采集系统指标
        let metrics = collect_metrics().await;

        // 预测
        let prediction = predictor.predict(&metrics);

        if cli.json {
            println!("{}", serde_json::json!({
                "timestamp": chrono::Local::now().to_rfc3339(),
                "metrics": metrics,
                "prediction": prediction,
            }));
        } else {
            println!("\n[crash-oracle] --- System Check ---");
            println!("{}", metrics);
            println!("{}", prediction);
        }

        if prediction.risk_level >= 7 {
            println!("\n[crash-oracle] WARNING: High crash risk detected!");
            println!("[crash-oracle] Recommended action: {}", prediction.action);
        }

        tokio::time::sleep(tokio::time::Duration::from_secs(cli.interval)).await;
    }

    Ok(())
}

/// 系统指标
#[derive(Debug, serde::Serialize)]
struct SystemMetrics {
    memory_fragmentation: f64,  // 0.0 - 1.0
    cpu_temperature: f64,       // °C
    io_error_rate: f64,         // 错误/秒
    syscall_latency: f64,       // ms
    memory_pressure: f64,       // 0.0 - 1.0
    context_switches: u64,
    oom_score: f64,             // 0.0 - 1.0
}

impl std::fmt::Display for SystemMetrics {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "  Memory frag:  {:.1}%\n  CPU temp:     {:.1}°C\n  IO errors:    {:.2}/s\n  Syscall lat:  {:.1}ms\n  Memory press: {:.1}%\n  Ctx switches: {}\n  OOM score:    {:.2}",
            self.memory_fragmentation * 100.0,
            self.cpu_temperature,
            self.io_error_rate,
            self.syscall_latency,
            self.memory_pressure * 100.0,
            self.context_switches,
            self.oom_score,
        )
    }
}

/// 预测结果
#[derive(Debug, serde::Serialize)]
struct Prediction {
    risk_level: u8,       // 0-10
    time_to_crash: String, // 估计时间
    action: String,        // 建议操作
    confidence: f64,       // 0.0-1.0
    indicators: Vec<String>,
}

impl std::fmt::Display for Prediction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "[crash-oracle] Risk level: {}/10 | Confidence: {:.0}% | ETA: {}",
            self.risk_level,
            self.confidence * 100.0,
            self.time_to_crash,
        )
    }
}

/// 收集系统指标
async fn collect_metrics() -> SystemMetrics {
    // 在实际实现中，应该从 /proc 和 /sys 读取真实数据
    // 这里用模拟数据展示

    SystemMetrics {
        memory_fragmentation: rand_f64(0.0, 0.3),
        cpu_temperature: rand_f64(40.0, 85.0),
        io_error_rate: rand_f64(0.0, 5.0),
        syscall_latency: rand_f64(0.1, 10.0),
        memory_pressure: rand_f64(0.0, 0.8),
        context_switches: rand_u64(1000, 50000),
        oom_score: rand_f64(0.0, 0.5),
    }
}

/// 预测器
struct Predictor {
    history: VecDeque<SystemMetrics>,
    max_history: usize,
    threshold: f64,
}

impl Predictor {
    fn new() -> Self {
        Self {
            history: VecDeque::with_capacity(100),
            max_history: 100,
            threshold: 0.7,
        }
    }

    fn predict(&mut self, metrics: &SystemMetrics) -> Prediction {
        self.history.push_back(SystemMetrics {
            memory_fragmentation: metrics.memory_fragmentation,
            cpu_temperature: metrics.cpu_temperature,
            io_error_rate: metrics.io_error_rate,
            syscall_latency: metrics.syscall_latency,
            memory_pressure: metrics.memory_pressure,
            context_switches: metrics.context_switches,
            oom_score: metrics.oom_score,
        });

        if self.history.len() > self.max_history {
            self.history.pop_front();
        }

        // 计算风险因子
        let mut risk_factors = Vec::new();
        let mut risk = 0.0f64;

        // 内存碎片化
        if metrics.memory_fragmentation > 0.2 {
            risk += metrics.memory_fragmentation * 3.0;
            risk_factors.push("high memory fragmentation".to_string());
        }

        // CPU 温度
        if metrics.cpu_temperature > 75.0 {
            risk += (metrics.cpu_temperature - 75.0) / 25.0 * 2.0;
            risk_factors.push("high CPU temperature".to_string());
        }

        // IO 错误率
        if metrics.io_error_rate > 2.0 {
            risk += metrics.io_error_rate / 5.0 * 2.0;
            risk_factors.push("elevated IO errors".to_string());
        }

        // 系统调用延迟
        if metrics.syscall_latency > 5.0 {
            risk += (metrics.syscall_latency - 5.0) / 5.0 * 2.0;
            risk_factors.push("high syscall latency".to_string());
        }

        // 内存压力
        if metrics.memory_pressure > 0.5 {
            risk += metrics.memory_pressure * 2.0;
            risk_factors.push("high memory pressure".to_string());
        }

        // OOM 风险
        if metrics.oom_score > 0.3 {
            risk += metrics.oom_score * 3.0;
            risk_factors.push("elevated OOM score".to_string());
        }

        // 归一化到 0-10
        let risk_level = (risk.min(10.0) * 10.0).round() as u8;

        // 置信度
        let confidence = if self.history.len() < 10 {
            0.3 + self.history.len() as f64 * 0.05
        } else {
            0.8
        }
        .min(1.0);

        // 建议操作
        let action = if risk_level >= 8 {
            "Trigger proactive crash dump, initiate checkpoint"
        } else if risk_level >= 6 {
            "Increase monitoring frequency, prepare recovery"
        } else if risk_level >= 4 {
            "Log warning, alert administrator"
        } else {
            "Normal operation - continue monitoring"
        };

        // 预估崩溃时间
        let time_to_crash = if risk_level >= 8 {
            "Imminent (within 60 seconds)"
        } else if risk_level >= 6 {
            "Likely (within 5 minutes)"
        } else if risk_level >= 4 {
            "Possible (within 30 minutes)"
        } else {
            "Unlikely"
        };

        Prediction {
            risk_level,
            time_to_crash: time_to_crash.to_string(),
            action: action.to_string(),
            confidence,
            indicators: risk_factors,
        }
    }
}

fn rand_f64(min: f64, max: f64) -> f64 {
    // 简单伪随机 (实际应使用真实系统数据)
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .subsec_nanos() as f64;
    min + (max - min) * (nanos / 1_000_000_000.0)
}

fn rand_u64(min: u64, max: u64) -> u64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .subsec_nanos() as u64;
    min + (nanos % (max - min))
}