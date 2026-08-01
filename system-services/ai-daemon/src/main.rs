// Ainos OS - AI 系统守护进程 (ai-daemon)
// Core AI service manager for Ainos OS.
// Responsibilities:
//   1. Model lifecycle management (load/unload/cache)
//   2. Request routing (local GGML <-> cloud API)
//   3. Context management (session persistence)
//   4. Resource monitoring and throttling
//   5. IPC via TCP (cross-platform) / Unix Domain Socket (Linux)
//   6. Thermal-aware power policy scheduling

mod config;
mod ipc;
mod models;
mod runtime;
mod context;
mod thermal;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::sync::RwLock;
use clap::Parser;
use tracing::{info, warn, error};

/// Ainos OS AI Daemon
#[derive(Parser, Debug)]
#[command(name = "ai-daemon", version)]
struct Args {
    /// Path to config file
    #[arg(short, long, default_value = "/etc/ainos/ai-daemon.conf")]
    config: String,

    /// Verbose mode
    #[arg(short, long, default_value = "false")]
    verbose: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            if std::env::var("RUST_LOG").is_ok() {
                tracing_subscriber::EnvFilter::from_default_env()
            } else {
                tracing_subscriber::EnvFilter::new("info,ainos=debug")
            }
        )
        .init();

    let args = Args::parse();

    info!("Ainos AI Daemon starting...");
    info!("Config: {}", args.config);

    // Load configuration
    let cfg = config::load_config(&args.config).await
        .unwrap_or_else(|e| {
            warn!("Failed to load config ({}), using defaults", e);
            config::DaemonConfig::default()
        });

    info!("Model directory: {}", cfg.models_dir);
    info!("Default model: {}", cfg.default_model);
    info!("Local inference: {}", if cfg.enable_local { "enabled" } else { "disabled" });
    info!("Cloud fallback: {}", if cfg.enable_cloud { "enabled" } else { "disabled" });

    // Initialize shared state
    let state = Arc::new(RwLock::new(AppState::new(cfg)));

    // 启动 IPC 监听器
    let ipc_addr = if cfg!(windows) {
        "127.0.0.1:9500"
    } else {
        "/var/run/ainos/ai-daemon.sock"
    };
    info!("Starting IPC listener on {}", ipc_addr);
    let ipc_handle = tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr));

    // 启动温度监控 (独立于 state，不持有锁)
    info!("Starting thermal monitor");
    let thermal_handle = tokio::spawn(async move {
        let monitor = thermal::ThermalMonitor::new();
        monitor.start().await;
    });

    // Start health check / monitoring
    let _monitor_handle = tokio::spawn(monitor_loop(state.clone()));

    // Wait for shutdown signal
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("Shutdown signal received");
        }
        _ = ipc_handle => {
            error!("IPC server stopped unexpectedly");
        }
        _ = thermal_handle => {
            error!("Thermal monitor stopped unexpectedly");
        }
    }

    info!("Ainos AI Daemon shutting down...");
    Ok(())
}

/// Application state shared across all components
#[derive(Debug)]
pub struct AppState {
    pub config: config::DaemonConfig,
    pub models: models::ModelRegistry,
    pub runtime: runtime::RuntimeManager,
    pub context: context::ContextManager,
    pub stats: DaemonStats,
}

impl AppState {
    pub fn new(config: config::DaemonConfig) -> Self {
        Self {
            models: models::ModelRegistry::new(),
            runtime: runtime::RuntimeManager::new(),
            context: context::ContextManager::new(),
            stats: DaemonStats::default(),
            config,
        }
    }
}

/// Daemon statistics (使用原子操作，无需锁)
#[derive(Debug)]
pub struct DaemonStats {
    pub total_requests: AtomicU64,
    pub local_inferences: AtomicU64,
    pub cloud_inferences: AtomicU64,
    pub errors: AtomicU64,
    pub uptime: std::time::Instant,
}

impl Default for DaemonStats {
    fn default() -> Self {
        Self {
            total_requests: AtomicU64::new(0),
            local_inferences: AtomicU64::new(0),
            cloud_inferences: AtomicU64::new(0),
            errors: AtomicU64::new(0),
            uptime: std::time::Instant::now(),
        }
    }
}

/// Periodic monitoring loop
async fn monitor_loop(state: Arc<RwLock<AppState>>) {
    let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(60));
    loop {
        interval.tick().await;
        let s = state.read().await;
        info!(
            "Stats: {} total, {} local, {} cloud, {} errors",
            s.stats.total_requests.load(Ordering::Relaxed),
            s.stats.local_inferences.load(Ordering::Relaxed),
            s.stats.cloud_inferences.load(Ordering::Relaxed),
            s.stats.errors.load(Ordering::Relaxed),
        );
    }
}