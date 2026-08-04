// Ainos OS - macOS Module
// ============================================================================
//
// This module groups macOS-specific functionality for the AI daemon.
// It is only compiled when targeting macOS (target_os = "macos").

pub mod launchd;
pub mod thermal_macos;
pub mod xpc;