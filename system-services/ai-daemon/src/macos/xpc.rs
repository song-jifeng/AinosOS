// Ainos OS - macOS XPC Transport Bridge (Rust side)
// ============================================================================
//
// This module provides the Rust-side interface for the macOS XPC transport.
// It communicates with the ainos_xpc C service via the file-based policy
// file and can also be used to register XPC service names that the daemon
// is listening on.
//
// Architecture:
//   The actual XPC service is implemented in C (ainos_xpc.c) and runs as
//   a separate launchd job. This module provides the Rust daemon with
//   the ability to:
//     1. Advertise XPC service availability
//     2. Handle XPC service registration
//     3. Provide status information for the XPC bridge
//
// Flow:
//   macOS app -> XPC message -> ainos_xpc (C) -> TCP :9500 -> Rust daemon
//   Rust daemon -> TCP response -> ainos_xpc (C) -> XPC reply -> macOS app

use std::collections::HashMap;
use std::sync::Mutex;
use tracing::{info, debug, error};

/// XPC service descriptor
#[derive(Debug, Clone)]
pub struct XpcService {
    /// XPC service name (e.g., "com.ainos.daemon.xpc")
    pub name: String,
    /// Whether the XPC service is currently registered
    pub registered: bool,
    /// Number of active XPC connections
    pub active_connections: u32,
    /// Timestamp when the service was registered
    pub registered_at: std::time::Instant,
}

/// XPC transport manager
pub struct XpcTransport {
    services: Mutex<HashMap<String, XpcService>>,
    xpc_available: bool,
}

impl XpcTransport {
    /// Create a new XPC transport manager.
    /// Detects whether the XPC service is available on this system.
    pub fn new() -> Self {
        let xpc_available = cfg!(target_os = "macos");

        let transport = XpcTransport {
            services: Mutex::new(HashMap::new()),
            xpc_available,
        };

        // Register the default XPC service
        if xpc_available {
            transport.register_service("com.ainos.daemon.xpc");
        }

        transport
    }

    /// Register an XPC service name.
    pub fn register_service(&self, name: &str) {
        let mut services = self.services.lock().unwrap();
        services.insert(name.to_string(), XpcService {
            name: name.to_string(),
            registered: true,
            active_connections: 0,
            registered_at: std::time::Instant::now(),
        });
        info!("XPC service registered: {}", name);
    }

    /// Unregister an XPC service name.
    pub fn unregister_service(&self, name: &str) {
        let mut services = self.services.lock().unwrap();
        services.remove(name);
        info!("XPC service unregistered: {}", name);
    }

    /// Check if an XPC service is registered.
    pub fn is_registered(&self, name: &str) -> bool {
        let services = self.services.lock().unwrap();
        services.get(name).map(|s| s.registered).unwrap_or(false)
    }

    /// Get the list of registered XPC services.
    pub fn list_services(&self) -> Vec<XpcService> {
        let services = self.services.lock().unwrap();
        services.values().cloned().collect()
    }

    /// Increment the active connection count for a service.
    pub fn increment_connections(&self, name: &str) {
        let mut services = self.services.lock().unwrap();
        if let Some(svc) = services.get_mut(name) {
            svc.active_connections += 1;
        }
    }

    /// Decrement the active connection count for a service.
    pub fn decrement_connections(&self, name: &str) {
        let mut services = self.services.lock().unwrap();
        if let Some(svc) = services.get_mut(name) {
            svc.active_connections = svc.active_connections.saturating_sub(1);
        }
    }

    /// Check whether XPC is available on this platform.
    pub fn is_available(&self) -> bool {
        self.xpc_available
    }
}

impl Default for XpcTransport {
    fn default() -> Self {
        Self::new()
    }
}

/// Check if the XPC transport should be used based on environment.
/// Returns true if the AINOS_MACOS_XPC environment variable is set to "1".
pub fn should_use_xpc() -> bool {
    std::env::var("AINOS_MACOS_XPC").as_deref() == Ok("1")
}

/// Check if launchd socket activation should be used.
/// Returns true if the AINOS_USE_LAUNCHD_SOCKETS environment variable is set.
pub fn should_use_launchd_sockets() -> bool {
    std::env::var("AINOS_USE_LAUNCHD_SOCKETS").as_deref() == Ok("1")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_xpc_transport_new() {
        let transport = XpcTransport::new();
        // XPC should be available on macOS only
        assert_eq!(transport.is_available(), cfg!(target_os = "macos"));
    }

    #[test]
    fn test_register_service() {
        let transport = XpcTransport::new();
        transport.register_service("com.ainos.test");
        assert!(transport.is_registered("com.ainos.test"));
    }

    #[test]
    fn test_unregister_service() {
        let transport = XpcTransport::new();
        transport.register_service("com.ainos.test");
        assert!(transport.is_registered("com.ainos.test"));
        transport.unregister_service("com.ainos.test");
        assert!(!transport.is_registered("com.ainos.test"));
    }

    #[test]
    fn test_list_services() {
        let transport = XpcTransport::new();
        transport.register_service("com.ainos.test1");
        transport.register_service("com.ainos.test2");
        let services = transport.list_services();
        assert_eq!(services.len(), 3); // 2 test + 1 default
    }

    #[test]
    fn test_increment_decrement() {
        let transport = XpcTransport::new();
        transport.increment_connections("com.ainos.daemon.xpc");
        let services = transport.list_services();
        let svc = services.iter().find(|s| s.name == "com.ainos.daemon.xpc").unwrap();
        assert_eq!(svc.active_connections, 1);

        transport.decrement_connections("com.ainos.daemon.xpc");
        let services = transport.list_services();
        let svc = services.iter().find(|s| s.name == "com.ainos.daemon.xpc").unwrap();
        assert_eq!(svc.active_connections, 0);
    }

    #[test]
    fn test_should_use_xpc() {
        // Without env var set, should return false
        assert!(!should_use_xpc());
    }
}