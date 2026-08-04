import Foundation
import UIKit
import os.log

/// AinosThermal - iOS thermal management for the Ainos platform.
/// Monitors device temperature using ProcessInfo.thermalState and sysfs readings,
/// and provides thermal-aware throttling for AI inference.
@objc public class AinosThermal: NSObject {

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosThermal")
    private let monitorQueue = DispatchQueue(label: "com.ainos.thermal.monitor", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var callback: ((Int, Int) -> Void)?
    private var monitorInterval: TimeInterval = 5.0

    /// Current thermal status.
    @objc public private(set) var currentStatus: AinosThermalStatus = .normal

    /// Current CPU temperature in Celsius.
    @objc public private(set) var cpuTemperature: Float = 0.0

    /// Current battery temperature in Celsius.
    @objc public private(set) var batteryTemperature: Float = 0.0

    /// Whether thermal monitoring is active.
    @objc public private(set) var isMonitoring: Bool = false

    /// Throttle level based on thermal conditions.
    @objc public var throttleLevel: Int {
        switch currentStatus {
        case .normal: return 0
        case .warm: return 1
        case .hot: return 2
        case .critical: return 3
        case .emergency: return 4
        default: return 0
        }
    }

    // MARK: - Initialization

    override init() {
        super.init()
        readThermalState()
    }

    /// Start thermal monitoring.
    /// - Parameter callback: Called when thermal status changes
    @objc public func startMonitoring(callback: @escaping (Int, Int) -> Void) {
        self.callback = callback
        isMonitoring = true

        // Register for thermal state change notifications
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleThermalStateChange),
            name: ProcessInfo.thermalStateDidChangeNotification,
            object: nil)

        // Start periodic monitoring
        timer = DispatchSource.makeTimerSource(queue: monitorQueue)
        timer?.schedule(deadline: .now(), repeating: monitorInterval, leeway: .seconds(1))
        timer?.setEventHandler { [weak self] in
            self?.readThermalState()
        }
        timer?.resume()

        os_log("Thermal monitoring started (interval=%.1fs)", log: logger, type: .info,
               monitorInterval)
    }

    /// Stop thermal monitoring.
    @objc public func stopMonitoring() {
        isMonitoring = false
        timer?.cancel()
        timer = nil
        NotificationCenter.default.removeObserver(
            self,
            name: ProcessInfo.thermalStateDidChangeNotification,
            object: nil)
        os_log("Thermal monitoring stopped", log: logger, type: .info)
    }

    // MARK: - Thermal Reading

    @objc private func handleThermalStateChange() {
        readThermalState()
    }

    private func readThermalState() {
        let oldStatus = currentStatus

        // Read from ProcessInfo (iOS 11+)
        let thermalState = ProcessInfo.processInfo.thermalState
        let newStatus = mapThermalState(thermalState)

        // Try to read actual temperature from sysfs (iOS kernel)
        cpuTemperature = readCPUTemperature() ?? estimateCPUTemperature(from: thermalState)
        batteryTemperature = readBatteryTemperature() ?? 0.0

        currentStatus = newStatus

        // Fire callback if status changed
        if oldStatus != newStatus {
            os_log("Thermal status changed: %@ -> %@ (CPU=%.1fC Battery=%.1fC)",
                   log: logger, type: .info,
                   statusString(oldStatus), statusString(newStatus),
                   cpuTemperature, batteryTemperature)

            DispatchQueue.main.async { [weak self] in
                self?.callback?(oldStatus.rawValue, newStatus.rawValue)
            }
        }

        // Log warning at high temperatures
        if newStatus.rawValue >= AinosThermalStatus.hot.rawValue {
            os_log("Thermal warning: %@ CPU=%.1fC",
                   log: logger, type: .error,
                   statusString(newStatus), cpuTemperature)
        }
    }

    private func mapThermalState(_ state: ProcessInfo.ThermalState) -> AinosThermalStatus {
        switch state {
        case .nominal:
            return .normal
        case .fair:
            return .warm
        case .serious:
            return .hot
        case .critical:
            return .critical
        @unknown default:
            return .unknown
        }
    }

    private func readCPUTemperature() -> Float? {
        // iOS doesn't expose direct sysfs temperature reading in sandboxed apps.
        // We attempt to read from thermal zones if available (jailbreak or internal).
        let thermalPaths = [
            "/sys/devices/system/cpu/cpu0/temperature",
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/devices/virtual/thermal/thermal_zone0/temp",
            "/var/run/thermal/temperature"
        ]

        for path in thermalPaths {
            if let data = try? String(contentsOfFile: path, encoding: .utf8) {
                let trimmed = data.trimmingCharacters(in: .whitespacesAndNewlines)
                if let tempRaw = Float(trimmed) {
                    // Values may be in millidegrees or decikelvin
                    if tempRaw > 1000 { return tempRaw / 1000.0 }
                    if tempRaw > 100 { return tempRaw / 10.0 }
                    return tempRaw
                }
            }
        }

        return nil
    }

    private func readBatteryTemperature() -> Float? {
        let batteryPaths = [
            "/sys/class/power_supply/battery/temp",
            "/sys/devices/platform/battery/temp",
            "/var/run/battery/temperature"
        ]

        for path in batteryPaths {
            if let data = try? String(contentsOfFile: path, encoding: .utf8) {
                let trimmed = data.trimmingCharacters(in: .whitespacesAndNewlines)
                if let tempRaw = Float(trimmed) {
                    // Values may be in tenths of Celsius
                    return tempRaw / 10.0
                }
            }
        }

        return nil
    }

    private func estimateCPUTemperature(from state: ProcessInfo.ThermalState) -> Float {
        // Estimate temperature based on thermal state when direct reading is unavailable
        switch state {
        case .nominal: return 35.0
        case .fair: return 50.0
        case .serious: return 65.0
        case .critical: return 80.0
        @unknown default: return 35.0
        }
    }

    // MARK: - Helpers

    /// Get a human-readable status string.
    @objc public func statusString(_ status: AinosThermalStatus) -> String {
        switch status {
        case .normal: return "Normal"
        case .warm: return "Warm"
        case .hot: return "Hot"
        case .critical: return "Critical"
        case .emergency: return "Emergency"
        default: return "Unknown"
        }
    }

    /// Get a summary string.
    @objc public func getThermalSummary() -> String {
        return String(format: "Thermal: %@ CPU=%.1fC Battery=%.1fC Throttle=%d",
                      statusString(currentStatus), cpuTemperature, batteryTemperature,
                      throttleLevel)
    }
}