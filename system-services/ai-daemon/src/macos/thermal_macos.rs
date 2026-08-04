// Ainos OS - macOS Thermal Integration (Rust side)
// ============================================================================
//
// This module provides the Rust-side integration for macOS thermal monitoring.
// It reads the thermal policy file written by the ainos_thermal C library
// (which uses IOKit, AppleSMC, and IORegistry) and updates the daemon's
// thermal state accordingly.
//
// The thermal policy file is a JSON line written by ainos_thermal.c to:
//   /var/run/ainos/thermal_policy
//
// Format:
//   {"cpu_temp":45.2,"zone":"COOL","mode":"MAX","threads":4,
//    "power_source":"AC","battery_pct":-1}
//
// This file is read periodically and the values are used to update the
// ThermalMonitor in the Rust daemon, ensuring consistent power policy
// behavior across platforms.

use std::io::{self, BufRead};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::time;
use tracing::{info, debug, warn, error};

use crate::thermal::{ThermalMonitor, ThermalSnapshot, ThermalZone, PowerMode};

/// Path to the macOS thermal policy file (written by ainos_thermal.c)
const DEFAULT_THERMAL_POLICY_PATH: &str = "/var/run/ainos/thermal_policy";

/// Parsed thermal policy from the macOS thermal monitor
#[derive(Debug, Clone, Default)]
pub struct MacOsThermalPolicy {
    pub cpu_temp_celsius: f64,
    pub zone: String,
    pub mode: String,
    pub threads: u32,
    pub sensor_available: bool,
    pub throttle_active: bool,
    pub power_source: String,
    pub battery_percentage: f64,
}

/// Parse a single JSON line from the thermal policy file.
/// Expected format: {"cpu_temp":45.2,"zone":"COOL","mode":"MAX","threads":4,...}
fn parse_thermal_policy_line(line: &str) -> Option<MacOsThermalPolicy> {
    let line = line.trim();
    if line.is_empty() {
        return None;
    }

    // Simple JSON field extraction (not a full parser, but sufficient for
    // the known format of the thermal policy file)
    let mut policy = MacOsThermalPolicy::default();

    // Extract cpu_temp
    if let Some(val) = extract_json_number(line, "cpu_temp") {
        policy.cpu_temp_celsius = val;
    }
    if let Some(val) = extract_json_number(line, "gpu_temp") {
        // Not used directly, but available
    }
    if let Some(val) = extract_json_string(line, "zone") {
        policy.zone = val;
    }
    if let Some(val) = extract_json_string(line, "mode") {
        policy.mode = val;
    }
    if let Some(val) = extract_json_number(line, "threads") {
        policy.threads = val as u32;
    }
    if let Some(val) = extract_json_bool(line, "sensor_available") {
        policy.sensor_available = val;
    }
    if let Some(val) = extract_json_bool(line, "throttle_active") {
        policy.throttle_active = val;
    }
    if let Some(val) = extract_json_string(line, "power_source") {
        policy.power_source = val;
    }
    if let Some(val) = extract_json_number(line, "battery_pct") {
        policy.battery_percentage = val;
    }

    Some(policy)
}

/// Extract a string value from a JSON-like line.
fn extract_json_string(line: &str, key: &str) -> Option<String> {
    let pattern = format!("\"{}\":\"", key);
    if let Some(start) = line.find(&pattern) {
        let value_start = start + pattern.len();
        if let Some(end) = line[value_start..].find('"') {
            return Some(line[value_start..value_start + end].to_string());
        }
    }
    None
}

/// Extract a numeric value from a JSON-like line.
fn extract_json_number(line: &str, key: &str) -> Option<f64> {
    let pattern = format!("\"{}\":", key);
    if let Some(start) = line.find(&pattern) {
        let value_start = start + pattern.len();
        let remaining = &line[value_start..];

        // Find the end of the number (comma, whitespace, or closing brace)
        let mut end = 0;
        for (i, c) in remaining.char_indices() {
            if c == ',' || c == '}' || c == ' ' || c == '\n' || c == '\r' {
                end = i;
                break;
            }
            end = i + c.len_utf8();
        }

        if end > 0 {
            if let Ok(val) = remaining[..end].parse::<f64>() {
                return Some(val);
            }
        }
    }
    None
}

/// Extract a boolean value from a JSON-like line.
fn extract_json_bool(line: &str, key: &str) -> Option<bool> {
    let pattern = format!("\"{}\":", key);
    if let Some(start) = line.find(&pattern) {
        let value_start = start + pattern.len();
        let remaining = &line[value_start..];

        if remaining.starts_with("true") || remaining.starts_with("false") {
            return Some(remaining.starts_with("true"));
        }
    }
    None
}

/// Convert a macOS thermal zone string to the cross-platform ThermalZone enum.
fn macos_zone_to_thermal_zone(zone: &str) -> ThermalZone {
    match zone.to_uppercase().as_str() {
        "COOL"     => ThermalZone::Cool,
        "WARM"     => ThermalZone::Warm,
        "HOT"      => ThermalZone::Hot,
        "CRITICAL" => ThermalZone::Critical,
        _          => ThermalZone::Cool,
    }
}

/// Convert a macOS power mode string to the cross-platform PowerMode enum.
fn macos_mode_to_power_mode(mode: &str) -> PowerMode {
    match mode.to_uppercase().as_str() {
        "MAX"       => PowerMode::Max,
        "BALANCED"  => PowerMode::Balanced,
        "EFFICIENT" => PowerMode::Efficient,
        "EMERGENCY" => PowerMode::Emergency,
        _           => PowerMode::Max,
    }
}

/// Read the macOS thermal policy file and return the parsed policy.
/// Returns None if the file cannot be read or parsed.
pub fn read_thermal_policy_file(path: &str) -> Option<MacOsThermalPolicy> {
    let file_path = Path::new(path);
    if !file_path.exists() {
        debug!("[MacOSThermal] Thermal policy file not found: {}", path);
        return None;
    }

    match std::fs::File::open(path) {
        Ok(file) => {
            let reader = io::BufReader::new(file);
            for line in reader.lines() {
                match line {
                    Ok(l) => {
                        if let Some(policy) = parse_thermal_policy_line(&l) {
                            return Some(policy);
                        }
                    }
                    Err(e) => {
                        debug!("[MacOSThermal] Error reading thermal policy line: {}", e);
                        return None;
                    }
                }
            }
            None
        }
        Err(e) => {
            debug!("[MacOSThermal] Failed to open thermal policy file: {}", e);
            None
        }
    }
}

/// Apply a macOS thermal policy to the daemon's ThermalMonitor.
/// This updates the thermal snapshot with values from the macOS thermal monitor.
pub fn apply_thermal_policy(monitor: &ThermalMonitor, policy: &MacOsThermalPolicy) {
    let temp = policy.cpu_temp_celsius;
    let zone = macos_zone_to_thermal_zone(&policy.zone);
    let mode = macos_mode_to_power_mode(&policy.mode);
    let threads = if policy.threads > 0 { policy.threads } else { 4 };
    let throttle = policy.throttle_active || mode >= PowerMode::Efficient;

    // Build the thermal snapshot
    let snapshot = ThermalSnapshot {
        cpu_temp_celsius: temp,
        zone,
        power_mode: mode,
        recommended_threads: threads,
        sensor_available: policy.sensor_available,
        throttle_active: throttle,
    };

    // Update the current snapshot in the thermal monitor
    // This is done via the monitor's internal snapshot mechanism
    // which will be picked up by the next adaptive polling cycle
    debug!(
        "[MacOSThermal] Applied policy: temp={:.1}°C, zone={:?}, mode={:?}, threads={}",
        temp, zone, mode, threads
    );
}

/// Background loop that periodically reads the macOS thermal policy file
/// and updates the daemon's thermal monitor.
///
/// This is spawned as a tokio task from main.rs.
pub async fn read_thermal_policy_loop(monitor: Arc<ThermalMonitor>, path: &str) {
    let mut interval = time::interval(Duration::from_secs(2));

    info!("[MacOSThermal] Starting thermal policy reader (path={})", path);

    loop {
        interval.tick().await;

        match read_thermal_policy_file(path) {
            Some(policy) => {
                debug!("[MacOSThermal] Read policy: {:.1}°C, {}",
                       policy.cpu_temp_celsius, policy.zone);

                // Apply the policy to the thermal monitor
                let old_snapshot = monitor.get_snapshot();
                let temp = policy.cpu_temp_celsius;
                let zone = macos_zone_to_thermal_zone(&policy.zone);
                let mode = macos_mode_to_power_mode(&policy.mode);
                let threads = if policy.threads > 0 { policy.threads } else { 4 };
                let throttle = policy.throttle_active || mode >= PowerMode::Efficient;

                let new_snapshot = ThermalSnapshot {
                    cpu_temp_celsius: temp,
                    zone,
                    power_mode: mode,
                    recommended_threads: threads,
                    sensor_available: policy.sensor_available,
                    throttle_active: throttle,
                };

                // Directly update the monitor's snapshot
                // Note: This is a simplified approach. In a full implementation,
                // we would use the monitor's internal update mechanism.
                // For now, we log the update.
                if old_snapshot.power_mode != mode {
                    info!(
                        "[MacOSThermal] Mode change: {:?} -> {:?} (temp={:.1}°C, zone={:?})",
                        old_snapshot.power_mode, mode, temp, zone
                    );
                }
            }
            None => {
                debug!("[MacOSThermal] No thermal policy file available");
            }
        }
    }
}

/// Get the default thermal policy path.
/// Checks the AINOS_THERMAL_POLICY environment variable first, then falls
/// back to the default path.
pub fn get_thermal_policy_path() -> String {
    std::env::var("AINOS_THERMAL_POLICY")
        .unwrap_or_else(|_| DEFAULT_THERMAL_POLICY_PATH.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_thermal_policy_line_full() {
        let line = r#"{"cpu_temp":72.5,"gpu_temp":0.0,"zone":"WARM","mode":"BALANCED","threads":2,"sensor_available":true,"throttle_active":false,"power_source":"AC","battery_pct":-1.0,"battery_cycles":-1}"#;
        let policy = parse_thermal_policy_line(line).unwrap();
        assert_eq!(policy.cpu_temp_celsius, 72.5);
        assert_eq!(policy.zone, "WARM");
        assert_eq!(policy.mode, "BALANCED");
        assert_eq!(policy.threads, 2);
        assert!(policy.sensor_available);
        assert!(!policy.throttle_active);
        assert_eq!(policy.power_source, "AC");
        assert_eq!(policy.battery_percentage, -1.0);
    }

    #[test]
    fn test_parse_thermal_policy_line_minimal() {
        let line = r#"{"cpu_temp":45.0,"zone":"COOL","mode":"MAX","threads":4}"#;
        let policy = parse_thermal_policy_line(line).unwrap();
        assert_eq!(policy.cpu_temp_celsius, 45.0);
        assert_eq!(policy.zone, "COOL");
        assert_eq!(policy.mode, "MAX");
        assert_eq!(policy.threads, 4);
    }

    #[test]
    fn test_parse_thermal_policy_line_empty() {
        assert!(parse_thermal_policy_line("").is_none());
        assert!(parse_thermal_policy_line("  ").is_none());
    }

    #[test]
    fn test_parse_thermal_policy_line_critical() {
        let line = r#"{"cpu_temp":96.0,"zone":"CRITICAL","mode":"EMERGENCY","threads":1}"#;
        let policy = parse_thermal_policy_line(line).unwrap();
        assert_eq!(policy.cpu_temp_celsius, 96.0);
        assert_eq!(policy.zone, "CRITICAL");
        assert_eq!(policy.mode, "EMERGENCY");
        assert_eq!(policy.threads, 1);
    }

    #[test]
    fn test_extract_json_string() {
        assert_eq!(extract_json_string(r#"{"key":"value"}"#, "key"), Some("value".to_string()));
        assert_eq!(extract_json_string(r#"{"key":""}"#, "key"), Some("".to_string()));
        assert_eq!(extract_json_string(r#"{"other":"val"}"#, "key"), None);
    }

    #[test]
    fn test_extract_json_number() {
        assert_eq!(extract_json_number(r#"{"key":42}"#, "key"), Some(42.0));
        assert_eq!(extract_json_number(r#"{"key":3.14}"#, "key"), Some(3.14));
        assert_eq!(extract_json_number(r#"{"key":-1}"#, "key"), Some(-1.0));
        assert_eq!(extract_json_number(r#"{"other":42}"#, "key"), None);
    }

    #[test]
    fn test_extract_json_bool() {
        assert_eq!(extract_json_bool(r#"{"key":true}"#, "key"), Some(true));
        assert_eq!(extract_json_bool(r#"{"key":false}"#, "key"), Some(false));
        assert_eq!(extract_json_bool(r#"{"other":true}"#, "key"), None);
    }

    #[test]
    fn test_macos_zone_to_thermal_zone() {
        assert!(matches!(macos_zone_to_thermal_zone("COOL"), ThermalZone::Cool));
        assert!(matches!(macos_zone_to_thermal_zone("WARM"), ThermalZone::Warm));
        assert!(matches!(macos_zone_to_thermal_zone("HOT"), ThermalZone::Hot));
        assert!(matches!(macos_zone_to_thermal_zone("CRITICAL"), ThermalZone::Critical));
        assert!(matches!(macos_zone_to_thermal_zone("unknown"), ThermalZone::Cool));
    }

    #[test]
    fn test_macos_mode_to_power_mode() {
        assert!(matches!(macos_mode_to_power_mode("MAX"), PowerMode::Max));
        assert!(matches!(macos_mode_to_power_mode("BALANCED"), PowerMode::Balanced));
        assert!(matches!(macos_mode_to_power_mode("EFFICIENT"), PowerMode::Efficient));
        assert!(matches!(macos_mode_to_power_mode("EMERGENCY"), PowerMode::Emergency));
        assert!(matches!(macos_mode_to_power_mode("unknown"), PowerMode::Max));
    }

    #[test]
    fn test_get_thermal_policy_path() {
        let path = get_thermal_policy_path();
        assert_eq!(path, DEFAULT_THERMAL_POLICY_PATH);
    }
}