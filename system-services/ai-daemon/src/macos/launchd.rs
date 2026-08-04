// Ainos OS - macOS launchd Socket Activation
// ============================================================================
//
// This module provides utilities for launchd socket activation on macOS.
// launchd can pass pre-bound socket file descriptors to the daemon process,
// eliminating the need for the daemon to bind to ports itself.
//
// This is configured in the launchd plist's Sockets dictionary:
//   <key>Sockets</key>
//   <dict>
//       <key>Listener</key>
//       <dict>
//           <key>SockServiceName</key>
//           <string>ainos</string>
//           <key>SockType</key>
//           <string>stream</string>
//           <key>SockFamily</key>
//           <string>IPv4</string>
//           <key>SockNodeName</key>
//           <string>127.0.0.1</string>
//           <key>SockPort</key>
//           <integer>9500</integer>
//       </dict>
//   </dict>
//
// launchd passes the socket FDs using environment variables:
//   LISTEN_FDS  = number of FDs (starts at FD 3)
//   LISTEN_PID  = PID of the process (must match our PID)
//
// Convention:
//   FD 3 = first socket in the Sockets dict
//   FD 4 = second socket, etc.

use std::os::unix::io::RawFd;
use tracing::{info, warn, debug};

/// The first FD that launchd passes (standard convention).
const SD_LISTEN_FDS_START: RawFd = 3;

/// Check if launchd socket activation is available.
/// Returns true if the LISTEN_FDS and LISTEN_PID environment variables
/// are set correctly for this process.
pub fn is_launchd_socket_available() -> bool {
    let listen_pid: u32 = match std::env::var("LISTEN_PID") {
        Ok(val) => val.parse().unwrap_or(0),
        Err(_) => return false,
    };

    let listen_fds: u32 = match std::env::var("LISTEN_FDS") {
        Ok(val) => val.parse().unwrap_or(0),
        Err(_) => return false,
    };

    let my_pid = std::process::id();
    let available = listen_pid == my_pid && listen_fds > 0;

    debug!(
        "launchd socket check: LISTEN_PID={}, our PID={}, LISTEN_FDS={} -> {}",
        listen_pid, my_pid, listen_fds,
        if available { "available" } else { "not available" }
    );

    available
}

/// Get the number of file descriptors passed by launchd.
pub fn get_listen_fds_count() -> u32 {
    std::env::var("LISTEN_FDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0)
}

/// Get the PID that launchd expects.
pub fn get_expected_pid() -> u32 {
    std::env::var("LISTEN_PID")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0)
}

/// Check if a specific socket index is available.
/// Index 0 corresponds to the first socket in the Sockets dict.
pub fn is_socket_available(index: u32) -> bool {
    let fds = get_listen_fds_count();
    index < fds
}

/// Get the file descriptor number for a given socket index.
/// Index 0 -> FD 3, index 1 -> FD 4, etc.
pub fn get_socket_fd(index: u32) -> Option<RawFd> {
    if is_socket_available(index) {
        Some(SD_LISTEN_FDS_START + index as RawFd)
    } else {
        None
    }
}

/// Create a TCP listener from a launchd-passed socket FD.
/// # Safety
/// The FD must be a valid TCP socket that was passed by launchd.
/// The caller must not close the FD directly (launchd manages it).
pub unsafe fn create_tcp_listener_from_launchd_fd(
    fd: RawFd,
) -> std::io::Result<std::net::TcpListener> {
    use std::os::unix::io::FromRawFd;

    let listener = std::net::TcpListener::from_raw_fd(fd);
    listener.set_nonblocking(true)?;
    Ok(listener)
}

/// Information about a launchd socket.
#[derive(Debug, Clone)]
pub struct LaunchdSocketInfo {
    /// Socket name from the plist Sockets dict (e.g., "Listener")
    pub name: String,
    /// Index in the Sockets dict (0-based)
    pub index: u32,
    /// File descriptor number
    pub fd: RawFd,
    /// Whether the socket is TCP or UDP
    pub is_stream: bool,
}

/// Enumerate all launchd sockets.
pub fn enumerate_sockets() -> Vec<LaunchdSocketInfo> {
    let count = get_listen_fds_count();
    let mut sockets = Vec::with_capacity(count as usize);

    for i in 0..count {
        let fd = SD_LISTEN_FDS_START + i as RawFd;
        sockets.push(LaunchdSocketInfo {
            name: format!("socket-{}", i),
            index: i,
            fd,
            is_stream: true, // Default to stream; real detection would need getsockopt
        });
    }

    sockets
}

/// Print launchd socket activation status for debugging.
pub fn print_socket_status() {
    if is_launchd_socket_available() {
        let count = get_listen_fds_count();
        info!("launchd socket activation: {} socket(s) available", count);
        for socket in enumerate_sockets() {
            info!("  Socket '{}': FD={}, index={}", socket.name, socket.fd, socket.index);
        }
    } else {
        warn!("launchd socket activation: not available");
        info!("  LISTEN_PID: {:?}", std::env::var("LISTEN_PID").ok());
        info!("  LISTEN_FDS: {:?}", std::env::var("LISTEN_FDS").ok());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_launchd_socket_available() {
        // Without the environment variables set, this should return false
        assert!(!is_launchd_socket_available());
    }

    #[test]
    fn test_get_listen_fds_count() {
        // Without the environment variable, should return 0
        assert_eq!(get_listen_fds_count(), 0);
    }

    #[test]
    fn test_is_socket_available() {
        // Without any FDs, no socket should be available
        assert!(!is_socket_available(0));
        assert!(!is_socket_available(1));
    }

    #[test]
    fn test_get_socket_fd() {
        // Without any FDs, should return None
        assert!(get_socket_fd(0).is_none());
    }

    #[test]
    fn test_enumerate_sockets() {
        // Without any FDs, should return empty list
        let sockets = enumerate_sockets();
        assert!(sockets.is_empty());
    }

    #[test]
    fn test_sd_listen_fds_start() {
        // Verify the constant
        assert_eq!(SD_LISTEN_FDS_START, 3);
    }
}