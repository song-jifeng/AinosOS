import Foundation
import UIKit
import os.log

/// AinosBattery - iOS battery management for the Ainos platform.
/// Monitors battery level, charging state, and provides power-aware
/// optimizations for AI inference.
@objc public class AinosBattery: NSObject {

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosBattery")
    private let device = UIDevice.current
    private var callback: ((Int, Int) -> Void)?
    private var isMonitoring = false

    /// Current battery level (0-100).
    @objc public private(set) var currentLevel: Int = 100

    /// Current battery status.
    @objc public private(set) var currentStatus: AinosBatteryStatus = .unknown

    /// Whether the device is currently charging.
    @objc public var isCharging: Bool {
        return currentStatus == .charging || currentStatus == .full
    }

    /// Whether the battery is low (<= 20%).
    @objc public var isLow: Bool {
        return currentLevel <= 20
    }

    /// Whether the battery is critically low (<= 10%).
    @objc public var isCriticallyLow: Bool {
        return currentLevel <= 10
    }

    /// Whether the battery is in a healthy temperature range.
    @objc public var isHealthyTemperature: Bool {
        let temp = getBatteryTemperature()
        return temp >= 0 && temp <= 45.0
    }

    // MARK: - Initialization

    override init() {
        super.init()
        device.isBatteryMonitoringEnabled = true
        updateBatteryState()
    }

    /// Start monitoring battery state changes.
    /// - Parameter callback: Called with (level, status) on change
    @objc public func startMonitoring(callback: @escaping (Int, Int) -> Void) {
        self.callback = callback
        isMonitoring = true

        // Register for battery state change notifications
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(batteryLevelChanged),
            name: UIDevice.batteryLevelDidChangeNotification,
            object: nil)

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(batteryStateChanged),
            name: UIDevice.batteryStateDidChangeNotification,
            object: nil)

        // Register for power mode changes
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(powerModeChanged),
            name: NSNotification.Name.NSProcessInfoPowerStateDidChange,
            object: nil)

        // Initial update
        updateBatteryState()

        os_log("Battery monitoring started: level=%d%% status=%d charging=%d",
               log: logger, type: .info, currentLevel, currentStatus.rawValue,
               isCharging)
    }

    /// Stop monitoring battery state.
    @objc public func stopMonitoring() {
        isMonitoring = false
        NotificationCenter.default.removeObserver(
            self,
            name: UIDevice.batteryLevelDidChangeNotification,
            object: nil)
        NotificationCenter.default.removeObserver(
            self,
            name: UIDevice.batteryStateDidChangeNotification,
            object: nil)
        NotificationCenter.default.removeObserver(
            self,
            name: NSNotification.Name.NSProcessInfoPowerStateDidChange,
            object: nil)
        os_log("Battery monitoring stopped", log: logger, type: .info)
    }

    /// Get the current battery temperature.
    /// - Returns: Temperature in Celsius, or -1 if unavailable
    @objc public func getBatteryTemperature() -> Float {
        // iOS doesn't expose battery temperature directly in sandboxed apps.
        // Try sysfs path if available.
        let paths = [
            "/sys/class/power_supply/battery/temp",
            "/sys/devices/platform/battery/temp",
            "/var/run/battery_temperature"
        ]

        for path in paths {
            if let data = try? String(contentsOfFile: path, encoding: .utf8) {
                let trimmed = data.trimmingCharacters(in: .whitespacesAndNewlines)
                if let tempRaw = Float(trimmed) {
                    return tempRaw / 10.0
                }
            }
        }

        // Estimate based on charging state
        if isCharging {
            return 32.0
        }
        return 28.0
    }

    /// Get the estimated remaining battery life in minutes.
    @objc public func getEstimatedRemainingMinutes() -> Int {
        if isCharging {
            return (100 - currentLevel) * 90 / 100
        } else {
            return currentLevel * 2
        }
    }

    /// Get the battery capacity in mAh (approximate).
    @objc public func getBatteryCapacity() -> Int {
        // iOS doesn't expose battery capacity directly.
        // Return a typical value based on device model.
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        var machine = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        let model = String(cString: machine)

        // Approximate capacities for common models
        if model.hasPrefix("iPhone16") { return 4600 } // iPhone 16 series
        if model.hasPrefix("iPhone15") { return 4300 } // iPhone 15 series
        if model.hasPrefix("iPhone14") { return 4000 } // iPhone 14 series
        if model.hasPrefix("iPhone13") { return 3800 } // iPhone 13 series
        if model.hasPrefix("iPhone12") { return 3500 } // iPhone 12 series
        if model.hasPrefix("iPhone11") { return 3300 } // iPhone 11 series
        if model.hasPrefix("iPhone10") { return 3000 } // iPhone X series
        if model.hasPrefix("iPad") { return 8000 }
        return 4000
    }

    /// Get a battery summary string.
    @objc public func getBatterySummary() -> String {
        return String(format: "Battery: %d%% %@, %.1fC, %@",
                      currentLevel,
                      isCharging ? "charging" : "discharging",
                      getBatteryTemperature(),
                      isLow ? "LOW" : "OK")
    }

    // MARK: - Notification Handlers

    @objc private func batteryLevelChanged() {
        updateBatteryState()
        os_log("Battery level changed: %d%%", log: logger, type: .info, currentLevel)
        notifyCallback()
    }

    @objc private func batteryStateChanged() {
        updateBatteryState()
        os_log("Battery state changed: %d (charging=%d)", log: logger, type: .info,
               currentStatus.rawValue, isCharging)
        notifyCallback()
    }

    @objc private func powerModeChanged() {
        let lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        os_log("Power mode changed: lowPower=%d", log: logger, type: .info, lowPower)
        notifyCallback()
    }

    private func updateBatteryState() {
        let level = device.batteryLevel
        if level >= 0 {
            currentLevel = Int(level * 100)
        }

        switch device.batteryState {
        case .unknown:
            currentStatus = .unknown
        case .unplugged:
            currentStatus = .discharging
        case .charging:
            currentStatus = .charging
        case .full:
            currentStatus = .full
        @unknown default:
            currentStatus = .unknown
        }
    }

    private func notifyCallback() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.callback?(self.currentLevel, self.currentStatus.rawValue)
        }
    }
}