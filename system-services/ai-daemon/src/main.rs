// Ainos OS - AI 系统守护进程 (ai-daemon)
// Core AI service manager for Ainos OS.
// Responsibilities:
//   1. Model lifecycle management (load/unload/cache)
//   2. Request routing (local GGML <-> cloud API)
//   3. Context management (session persistence)
//   4. Resource monitoring and throttling
//   5. IPC via TCP (cross-platform) / Unix Domain Socket (Linux) / Named Pipe (Windows)
//   6. Thermal-aware power policy scheduling
//   7. Semantic caching of inference results
//   8. Windows Service mode (Windows)

mod auth;
mod cache;
mod config;
mod context;
mod ipc;
mod models;
mod ratelimit;
mod runtime;
#[cfg(test)]
mod tests;
mod thermal;
mod tls;

// Windows-specific modules
#[cfg(windows)]
mod ipc_windows;

// macOS-specific modules
#[cfg(target_os = "macos")]
mod macos {
    // XPC service transport bridge
    pub mod xpc;
    // macOS thermal integration (reads from IOKit thermal policy file)
    pub mod thermal_macos;
    // launchd socket activation
    pub mod launchd;
}

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

    /// Windows: Run as a Windows service (called by SCM)
    #[cfg(windows)]
    #[arg(long, default_value = "false")]
    service: bool,

    /// Windows: Install the Windows service
    #[cfg(windows)]
    #[arg(long, default_value = "false")]
    install_service: bool,

    /// Windows: Uninstall the Windows service
    #[cfg(windows)]
    #[arg(long, default_value = "false")]
    uninstall_service: bool,

    /// macOS: Use launchd socket activation (pass file descriptor via env)
    #[cfg(target_os = "macos")]
    #[arg(long, default_value = "false")]
    launchd_sockets: bool,

    /// macOS: Use XPC transport instead of TCP
    #[cfg(target_os = "macos")]
    #[arg(long, default_value = "false")]
    xpc: bool,

    /// macOS: Path to thermal policy file from IOKit thermal monitor
    #[cfg(target_os = "macos")]
    #[arg(long, default_value = "/var/run/ainos/thermal_policy")]
    thermal_policy: String,
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

    #[cfg(target_os = "macos")]
    {
        info!("macOS platform detected");
        if args.launchd_sockets {
            info!("launchd socket activation enabled");
        }
        if args.xpc {
            info!("XPC transport enabled");
        }
        info!("Thermal policy file: {}", args.thermal_policy);
    }

    #[cfg(windows)]
    {
        info!("Windows platform detected");
        if args.install_service {
            return install_windows_service();
        }
        if args.uninstall_service {
            return uninstall_windows_service();
        }
        if args.service {
            return run_as_windows_service().await;
        }
        // Initialize Windows event log
        if let Err(e) = ipc_windows::register_event_source() {
            warn!("Failed to register event source: {}", e);
        }
        info!("Windows event log initialized");
        ipc_windows::report_info(1000, "Ainos AI Daemon starting on Windows");
    }

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
    info!("Context directory: {}", cfg.context_dir);

    // Initialize shared state
    let state = Arc::new(RwLock::new(AppState::new(cfg)));

    // 启动 IPC 监听器
    // macOS: use XPC transport if --xpc flag is set, otherwise use TCP
    // macOS also supports launchd socket activation (passes fd via env)
    // Windows: prefer named pipe, fall back to TCP if pipe creation fails
    let ipc_addr = if cfg!(target_os = "macos") {
        if args.xpc {
            "xpc://com.ainos.daemon.xpc"
        } else if args.launchd_sockets {
            "launchd://Listener"
        } else {
            "127.0.0.1:9500"
        }
    } else if cfg!(windows) {
        "127.0.0.1:9500"
    } else {
        "/var/run/ainos/ai-daemon.sock"
    };

    #[cfg(windows)]
    let ipc_handle = {
        // Try named pipe first (Windows-native IPC)
        info!("Starting Windows named pipe server on \\\\.\\pipe\\ainos-daemon");
        match ipc_windows::AsyncPipeServer::new(state.clone(), true) {
            Ok(server) => {
                let server_handle = tokio::spawn(server.serve());
                // Also start a TCP fallback on 9500 for compatibility
                let tcp_handle = tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr));
                // We track both handles
                tokio::spawn(async move {
                    tokio::select! {
                        _ = server_handle => {},
                        _ = tcp_handle => {},
                    }
                })
            }
            Err(e) => {
                error!("Failed to create named pipe server: {}. Falling back to TCP.", e);
                info!("Starting IPC TCP listener on {}", ipc_addr);
                tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr))
            }
        }
    };

    #[cfg(not(windows))]
    let ipc_handle = {
        info!("Starting IPC listener on {}", ipc_addr);
        tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr))
    };

    // 启动温度监控 (自适应轮询 + 事件驱动)
    // macOS: also reads from the IOKit thermal policy file
    info!("Starting thermal monitor with adaptive polling");
    let thermal_monitor = Arc::new(thermal::ThermalMonitor::new());

    // macOS-specific: attach the thermal policy file reader
    #[cfg(target_os = "macos")]
    {
        let thermal_path = args.thermal_policy.clone();
        let mon = thermal_monitor.clone();
        // Spawn a background task to read the macOS thermal policy file
        tokio::spawn(async move {
            macos::thermal_macos::read_thermal_policy_loop(mon, &thermal_path).await;
        });
    }

    let thermal_handle = tokio::spawn(thermal_monitor.clone().start());

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

    #[cfg(windows)]
    {
        ipc_windows::report_info(1001, "Ainos AI Daemon shutting down");
    }

    Ok(())
}

/// Install the Windows service.
#[cfg(windows)]
fn install_windows_service() -> anyhow::Result<()> {
    info!("Installing Windows service...");

    // Try the service wrapper executable first
    let service_exe = std::env::current_exe()?
        .parent()
        .map(|p| p.join("ainos_service.exe"))
        .unwrap_or_else(|| std::path::PathBuf::from("ainos_service.exe"));

    if service_exe.exists() {
        let output = std::process::Command::new(&service_exe)
            .arg("--install")
            .output()?;

        if output.status.success() {
            info!("Service installed via wrapper");
            println!("Ainos OS AI Daemon service installed successfully.");
            println!("Start: sc start AinosAIDaemon");
            return Ok(());
        }
        let stderr = String::from_utf8_lossy(&output.stderr);
        warn!("Service wrapper failed: {}. Trying direct install.", stderr);
    }

    // Install directly via SCM (sc.exe)
    let exe_path = std::env::current_exe()?;
    let exe_str = exe_path.to_string_lossy();
    let config_path = exe_path.parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("configs").join("ai-daemon.toml"))
        .filter(|p| p.exists())
        .unwrap_or_else(|| std::path::PathBuf::from("C:\\Program Files\\AinosOS\\configs\\ai-daemon.toml"));
    let config_str = config_path.to_string_lossy();

    let bin_path = format!("\"{}\" --service -c \"{}\"", exe_str, config_str);

    let status = std::process::Command::new("sc")
        .args(&["create", "AinosAIDaemon",
            "binPath=", &bin_path,
            "displayName=", "Ainos OS AI Daemon",
            "type=", "own",
            "start=", "auto",
            "error=", "normal"])
        .status()?;

    if status.success() {
        let _ = std::process::Command::new("sc")
            .args(&["description", "AinosAIDaemon",
                "Core AI service manager for Ainos OS. Provides model lifecycle management, inference routing, context management, and system resource monitoring."])
            .status()?;

        let _ = std::process::Command::new("sc")
            .args(&["failure", "AinosAIDaemon",
                "reset=", "86400",
                "actions=", "restart/30000/restart/60000/restart/120000"])
            .status()?;

        info!("Service installed via sc.exe");
        println!("Ainos OS AI Daemon service installed successfully.");
        println!("Start: sc start AinosAIDaemon");
    } else {
        error!("Failed to install service via sc.exe");
        println!("Failed to install service. Run as Administrator.");
        return Err(anyhow::anyhow!("Failed to install service"));
    }

    Ok(())
}

/// Uninstall the Windows service.
#[cfg(windows)]
fn uninstall_windows_service() -> anyhow::Result<()> {
    info!("Uninstalling Windows service...");

    // Try the service wrapper executable first
    let service_exe = std::env::current_exe()?
        .parent()
        .map(|p| p.join("ainos_service.exe"))
        .unwrap_or_else(|| std::path::PathBuf::from("ainos_service.exe"));

    if service_exe.exists() {
        let output = std::process::Command::new(&service_exe)
            .arg("--uninstall")
            .output()?;

        if output.status.success() {
            info!("Service uninstalled via wrapper");
            println!("Ainos OS AI Daemon service uninstalled successfully.");
            return Ok(());
        }
        warn!("Service wrapper uninstall failed, trying direct uninstall");
    }

    // Direct uninstall via sc.exe
    let _ = std::process::Command::new("sc")
        .args(&["stop", "AinosAIDaemon"])
        .status()?;

    std::thread::sleep(std::time::Duration::from_secs(2));

    let _ = std::process::Command::new("sc")
        .args(&["delete", "AinosAIDaemon"])
        .status()?;

    info!("Service uninstalled");
    println!("Ainos OS AI Daemon service uninstalled.");
    Ok(())
}

/// Run as a Windows service (called by the SCM).
///
/// This registers the service control handler and enters the service main loop.
/// The service manages the daemon process and responds to SCM control requests.
#[cfg(windows)]
async fn run_as_windows_service() -> anyhow::Result<()> {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr;

    info!("Running as Windows service...");

    // The recommended approach is to use ainos_service.exe as the service wrapper.
    // However, we also support running the daemon directly as a service.
    // In this mode, we register with the SCM and run until shutdown.

    let service_name: Vec<u16> = OsStr::new("AinosAIDaemon")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    // Fill the SERVICE_TABLE_ENTRY
    let mut service_table = [
        winapi::um::winsvc::SERVICE_TABLE_ENTRYW {
            lpServiceName: service_name.as_ptr() as *mut u16,
            lpServiceProc: Some(service_main),
        },
        winapi::um::winsvc::SERVICE_TABLE_ENTRYW {
            lpServiceName: ptr::null_mut(),
            lpServiceProc: None,
        },
    ];

    let result = unsafe {
        winapi::um::winsvc::StartServiceCtrlDispatcherW(service_table.as_mut_ptr())
    };

    if result == 0 {
        let err = unsafe { winapi::um::errhandlingapi::GetLastError() };
        error!("StartServiceCtrlDispatcherW failed: {}", err);
        // If not running as a service, just run normally
        info!("Not running as a service (SCM not detected). Running in normal mode.");
    }

    Ok(())
}

/// Service main entry point (called by the SCM).
#[cfg(windows)]
extern "system" fn service_main(argc: u32, argv: *mut *mut u16) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr;

    unsafe {
        // Register the service control handler
        let mut status = winapi::um::winsvc::SERVICE_STATUS {
            dwServiceType: winapi::um::winsvc::SERVICE_WIN32_OWN_PROCESS,
            dwCurrentState: winapi::um::winsvc::SERVICE_START_PENDING,
            dwControlsAccepted: 0,
            dwWin32ExitCode: 0,
            dwServiceSpecificExitCode: 0,
            dwCheckPoint: 0,
            dwWaitHint: 30000,
        };

        let status_handle = winapi::um::winsvc::RegisterServiceCtrlHandlerExW(
            OsStr::new("AinosAIDaemon").encode_wide().chain(std::iter::once(0))
                .collect::<Vec<u16>>().as_ptr() as *mut u16,
            Some(service_ctrl_handler_ex),
            ptr::null_mut(),
        );

        if status_handle == 0 as *mut std::ffi::c_void {
            return;
        }

        // Report SERVICE_RUNNING
        status.dwCurrentState = winapi::um::winsvc::SERVICE_RUNNING;
        status.dwControlsAccepted = winapi::um::winsvc::SERVICE_ACCEPT_STOP
            | winapi::um::winsvc::SERVICE_ACCEPT_SHUTDOWN
            | winapi::um::winsvc::SERVICE_ACCEPT_PAUSE_CONTINUE;
        status.dwCheckPoint = 0;
        status.dwWaitHint = 0;

        winapi::um::winsvc::SetServiceStatus(status_handle, &mut status);

        // Service is now running
        // The actual daemon logic runs in the tokio runtime
        // For now, we just keep the service alive until stop is signaled
        // In a full implementation, this would integrate with the tokio runtime

        // Wait for stop signal by polling
        loop {
            std::thread::sleep(std::time::Duration::from_secs(1));
            // Check if service should stop
            // This is handled by the service control handler
            // For now, we just keep running
        }
    }
}

/// Service control handler (ex version).
#[cfg(windows)]
extern "system" fn service_ctrl_handler_ex(
    control_code: u32,
    event_type: u32,
    event_data: *mut std::ffi::c_void,
    context: *mut std::ffi::c_void,
) -> u32 {
    use std::ptr;

    unsafe {
        match control_code {
            winapi::um::winsvc::SERVICE_CONTROL_STOP
            | winapi::um::winsvc::SERVICE_CONTROL_SHUTDOWN => {
                info!("Service stop/shutdown requested");
                // Signal the daemon to stop
                // In a full implementation, this would trigger graceful shutdown
                winapi::um::winbase::EVENTLOG_INFORMATION_TYPE;
                winapi::um::winsvc::SERVICE_STOPPED;
                // Return NO_ERROR to acknowledge
                return winapi::um::winerror::NO_ERROR;
            }
            winapi::um::winsvc::SERVICE_CONTROL_PAUSE => {
                info!("Service pause requested");
                return winapi::um::winerror::NO_ERROR;
            }
            winapi::um::winsvc::SERVICE_CONTROL_CONTINUE => {
                info!("Service continue requested");
                return winapi::um::winerror::NO_ERROR;
            }
            winapi::um::winsvc::SERVICE_CONTROL_INTERROGATE => {
                return winapi::um::winerror::NO_ERROR;
            }
            _ => {
                return winapi::um::winerror::ERROR_CALL_NOT_IMPLEMENTED;
            }
        }
    }
}

/// Application state shared across all components
#[derive(Debug)]
pub struct AppState {
    pub config: config::DaemonConfig,
    pub models: models::ModelRegistry,
    pub runtime: runtime::RuntimeManager,
    pub context: context::ContextManager,
    pub cache: cache::SemanticCache,
    pub stats: DaemonStats,
    pub session_manager: std::sync::Arc<crate::auth::SessionManager>,
    pub rate_limiter: std::sync::Arc<crate::ratelimit::RateLimiter>,
}

impl AppState {
    pub fn new(config: config::DaemonConfig) -> Self {
        let audit = std::sync::Arc::new(crate::auth::AuditLogger::from_config(&config.auth));
        let session_manager = std::sync::Arc::new(crate::auth::SessionManager::new(&config.auth, audit));
        let rate_limiter = std::sync::Arc::new(crate::ratelimit::RateLimiter::new(&config.ratelimit));
        Self {
            models: models::ModelRegistry::new(),
            runtime: runtime::RuntimeManager::new(),
            context: context::ContextManager::new(),
            cache: cache::SemanticCache::new(),
            stats: DaemonStats::default(),
            config,
            session_manager,
            rate_limiter,
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
            "Stats: {} total, {} local, {} cloud, {} errors, cache_hit_rate={:.1}%",
            s.stats.total_requests.load(Ordering::Relaxed),
            s.stats.local_inferences.load(Ordering::Relaxed),
            s.stats.cloud_inferences.load(Ordering::Relaxed),
            s.stats.errors.load(Ordering::Relaxed),
            s.cache.hit_rate() * 100.0,
        );
    }
}