import Foundation
import UIKit
import BackgroundTasks
import CoreML
import Metal
import MetalPerformanceShaders
import os.log

/// AinosPlatform - Main iOS platform support layer for the Ainos AI system.
/// Provides thermal management, battery monitoring, CoreML/ANE integration,
/// background tasks, and daemon communication.
@objc public class AinosPlatform: NSObject {

    // MARK: - Singleton

    /// Shared platform instance
    @objc public static let shared = AinosPlatform()

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosPlatform")
    private let thermalManager = AinosThermal()
    private let batteryManager = AinosBattery()
    private let backgroundManager = AinosBackground()
    private let coreMLManager = AinosCoreML()
    private let neuralEngine = AinosNeuralEngine()

    private var isInitialized = false
    private var daemonConnected = false
    private var daemonHost: String = "127.0.0.1"
    private var daemonPort: UInt16 = 8732
    private var daemonSocket: Int32 = -1
    private var appName: String = "Ainos"
    private var appVersion: String = "1.0.0"
    private var messageSequence: UInt64 = 0
    private var foregroundTask: UIBackgroundTaskIdentifier = .invalid
    private var connectionCallback: ((Bool) -> Void)?
    private var thermalCallback: ((Int, Int) -> Void)?
    private var batteryCallback: ((Int, Int) -> Void)?

    private let queue = DispatchQueue(label: "com.ainos.platform", qos: .userInitiated)
    private let daemonQueue = DispatchQueue(label: "com.ainos.daemon", qos: .default)
    private let thermalQueue = DispatchQueue(label: "com.ainos.thermal", qos: .utility)
    private let inferenceQueue = DispatchQueue(label: "com.ainos.inference", qos: .userInitiated,
                                                attributes: .concurrent)

    // MARK: - Initialization

    private override init() {
        super.init()
        os_log("AinosPlatform instance created", log: logger, type: .info)
    }

    // MARK: - Platform Lifecycle

    /// Initialize the Ainos iOS platform.
    /// - Parameters:
    ///   - appName: Application name
    ///   - appVersion: Application version
    ///   - completion: Completion handler with status
    @objc public func initialize(appName: String, appVersion: String,
                                  completion: @escaping (Int) -> Void) {
        queue.async { [weak self] in
            guard let self = self else { return }

            if self.isInitialized {
                os_log("Platform already initialized", log: self.logger, type: .error)
                completion(AinosStatusAlreadyInitialized.rawValue)
                return
            }

            os_log("Initializing AinosPlatform v%@ for %@",
                   log: self.logger, type: .info, appVersion, appName)

            self.appName = appName
            self.appVersion = appVersion

            // Initialize thermal monitoring
            self.thermalManager.startMonitoring { [weak self] oldStatus, newStatus in
                self?.handleThermalChange(oldStatus: oldStatus, newStatus: newStatus)
            }

            // Initialize battery monitoring
            self.batteryManager.startMonitoring { [weak self] level, status in
                self?.handleBatteryChange(level: level, status: status)
            }

            // Initialize CoreML
            self.coreMLManager.initialize()
            self.neuralEngine.initialize()

            // Initialize background tasks
            self.backgroundManager.registerTasks()

            // Register for notifications
            self.registerForNotifications()

            self.isInitialized = true
            os_log("AinosPlatform initialized successfully", log: self.logger, type: .info)
            completion(AinosStatusOk.rawValue)
        }
    }

    /// Shutdown the platform.
    @objc public func shutdown() {
        queue.async { [weak self] in
            guard let self = self else { return }

            os_log("Shutting down AinosPlatform", log: self.logger, type: .info)

            self.disconnectDaemon()
            self.thermalManager.stopMonitoring()
            self.batteryManager.stopMonitoring()
            self.backgroundManager.unregisterAllTasks()
            self.coreMLManager.release()
            self.neuralEngine.release()

            self.isInitialized = false
            os_log("AinosPlatform shutdown complete", log: self.logger, type: .info)
        }
    }

    /// Check if the platform is initialized.
    @objc public func isPlatformInitialized() -> Bool {
        return isInitialized
    }

    /// Get the platform version.
    @objc public func getVersion() -> String {
        return "1.0.0"
    }

    // MARK: - Thermal Management

    /// Get the current thermal status.
    @objc public func getThermalStatus() -> Int {
        return thermalManager.currentStatus.rawValue
    }

    /// Get the current CPU temperature.
    @objc public func getCpuTemperature() -> Float {
        return thermalManager.cpuTemperature
    }

    /// Get the current battery temperature.
    @objc public func getBatteryTemperature() -> Float {
        return thermalManager.batteryTemperature
    }

    /// Register a thermal change callback.
    @objc public func onThermalChange(callback: @escaping (Int, Int) -> Void) {
        thermalCallback = callback
    }

    /// Check if inference should be throttled.
    @objc public func shouldThrottleInference() -> Bool {
        return thermalManager.currentStatus.rawValue >= AinosThermalStatus.hot.rawValue
    }

    /// Get recommended batch size based on thermal conditions.
    @objc public func getRecommendedBatchSize() -> Int {
        switch thermalManager.currentStatus {
        case .normal: return 8
        case .warm: return 4
        case .hot: return 2
        case .critical, .emergency: return 1
        default: return 4
        }
    }

    // MARK: - Battery Management

    /// Get the current battery level.
    @objc public func getBatteryLevel() -> Int {
        return batteryManager.currentLevel
    }

    /// Get the current battery status.
    @objc public func getBatteryStatus() -> Int {
        return batteryManager.currentStatus.rawValue
    }

    /// Check if the device is charging.
    @objc public func isCharging() -> Bool {
        return batteryManager.isCharging
    }

    /// Check if low power mode is active.
    @objc public func isLowPowerMode() -> Bool {
        return ProcessInfo.processInfo.isLowPowerModeEnabled
    }

    /// Register a battery change callback.
    @objc public func onBatteryChange(callback: @escaping (Int, Int) -> Void) {
        batteryCallback = callback
    }

    // MARK: - Daemon Communication

    /// Connect to the AinosOS daemon.
    @objc public func connectDaemon(host: String, port: UInt16,
                                     timeout: UInt32,
                                     completion: @escaping (Int) -> Void) {
        daemonQueue.async { [weak self] in
            guard let self = self else { return }

            if self.daemonConnected {
                completion(AinosStatusAlreadyInitialized.rawValue)
                return
            }

            os_log("Connecting to daemon at %@:%d", log: self.logger, type: .info,
                   host, port)

            self.daemonHost = host
            self.daemonPort = port

            // Create TCP socket
            let sock = socket(AF_INET, SOCK_STREAM, 0)
            guard sock >= 0 else {
                os_log("Failed to create socket", log: self.logger, type: .error)
                completion(AinosStatusDaemonUnreachable.rawValue)
                return
            }

            // Set socket timeout
            var tv = timeval(tv_sec: Int(timeout / 1000), tv_usec: 0)
            setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
            setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))

            // Connect
            var addr = sockaddr_in()
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = CFSwapInt16HostToBig(port)
            inet_pton(AF_INET, host, &addr.sin_addr)

            let connectResult = withUnsafePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }

            guard connectResult == 0 else {
                os_log("Failed to connect to daemon: %d", log: self.logger,
                       type: .error, errno)
                close(sock)
                completion(AinosStatusDaemonUnreachable.rawValue)
                return
            }

            self.daemonSocket = sock
            self.daemonConnected = true

            // Start listening for messages
            self.startDaemonListener()

            // Send registration
            self.sendRegister()

            os_log("Connected to daemon at %@:%d", log: self.logger, type: .info,
                   host, port)

            self.connectionCallback?(true)
            completion(AinosStatusOk.rawValue)
        }
    }

    /// Disconnect from the daemon.
    @objc public func disconnectDaemon() {
        daemonQueue.async { [weak self] in
            guard let self = self else { return }

            if self.daemonSocket >= 0 {
                close(self.daemonSocket)
                self.daemonSocket = -1
            }
            self.daemonConnected = false
            self.connectionCallback?(false)
            os_log("Disconnected from daemon", log: self.logger, type: .info)
        }
    }

    /// Check if connected to the daemon.
    @objc public func isDaemonConnected() -> Bool {
        return daemonConnected
    }

    /// Register a connection callback.
    @objc public func onDaemonConnectionChange(callback: @escaping (Bool) -> Void) {
        connectionCallback = callback
    }

    /// Send a command to the daemon.
    @objc public func sendDaemonCommand(command: UInt16, payload: Data,
                                         completion: @escaping (Int, Data?) -> Void) {
        daemonQueue.async { [weak self] in
            guard let self = self else { return }

            guard self.daemonConnected, self.daemonSocket >= 0 else {
                completion(AinosStatusDaemonUnreachable.rawValue, nil)
                return
            }

            let sequence = UInt32(self.messageSequence & 0xFFFFFFFF)
            self.messageSequence += 1
            let timestamp = UInt64(Date().timeIntervalSince1970 * 1000)

            // Build message header (command:2, flags:2, sequence:4, timestamp:8, payload_size:4)
            var header = Data()
            withUnsafeBytes(of: CFSwapInt16HostToBig(command)) { header.append($0.bindMemory(to: UInt8.self)) }
            var flags: UInt16 = 0
            withUnsafeBytes(of: CFSwapInt16HostToBig(flags)) { header.append($0.bindMemory(to: UInt8.self)) }
            withUnsafeBytes(of: CFSwapInt32HostToBig(sequence)) { header.append($0.bindMemory(to: UInt8.self)) }
            withUnsafeBytes(of: CFSwapInt64HostToBig(timestamp)) { header.append($0.bindMemory(to: UInt8.self)) }
            let payloadSize = UInt32(payload.count)
            withUnsafeBytes(of: CFSwapInt32HostToBig(payloadSize)) { header.append($0.bindMemory(to: UInt8.self)) }

            var message = header
            message.append(payload)

            // Send message
            var sent = 0
            var dataToSend = message
            while sent < dataToSend.count {
                let bytes = dataToSend.withUnsafeBytes {
                    write(self.daemonSocket, $0.baseAddress!, dataToSend.count - sent)
                }
                guard bytes > 0 else {
                    os_log("Failed to send daemon message", log: self.logger, type: .error)
                    completion(AinosStatusDaemonDisconnected.rawValue, nil)
                    return
                }
                sent += bytes
                dataToSend = dataToSend.advanced(by: bytes)
            }

            // Read response
            var responseHeader = Data(count: 12)
            var totalRead = 0
            while totalRead < 12 {
                let bytes = responseHeader.withUnsafeMutableBytes {
                    read(self.daemonSocket, $0.baseAddress! + totalRead, 12 - totalRead)
                }
                guard bytes > 0 else {
                    completion(AinosStatusDaemonDisconnected.rawValue, nil)
                    return
                }
                totalRead += bytes
            }

            // Parse response header
            let responseCommand = UInt16(responseHeader[0]) << 8 | UInt16(responseHeader[1])
            let responsePayloadSize = UInt32(responseHeader[8]) << 24 |
                                      UInt32(responseHeader[9]) << 16 |
                                      UInt32(responseHeader[10]) << 8 |
                                      UInt32(responseHeader[11])

            // Read response payload
            var responsePayload = Data(count: Int(responsePayloadSize))
            totalRead = 0
            while totalRead < responsePayloadSize {
                let bytes = responsePayload.withUnsafeMutableBytes {
                    read(self.daemonSocket, $0.baseAddress! + totalRead,
                         Int(responsePayloadSize) - totalRead)
                }
                guard bytes > 0 else {
                    completion(AinosStatusDaemonDisconnected.rawValue, nil)
                    return
                }
                totalRead += bytes
            }

            os_log("Daemon response: command=0x%04x size=%d",
                   log: self.logger, type: .debug, responseCommand, responsePayload.count)
            completion(AinosStatusOk.rawValue, responsePayload)
        }
    }

    // MARK: - Background Tasks

    /// Register a background task.
    @objc public func registerBackgroundTask(taskId: String, taskName: String,
                                              interval: TimeInterval) -> Int {
        return backgroundManager.registerTask(taskId: taskId, taskName: taskName,
                                               interval: interval)
    }

    /// Start a background task.
    @objc public func startBackgroundTask(taskId: String) -> Int {
        return backgroundManager.startTask(taskId: taskId)
    }

    /// Stop a background task.
    @objc public func stopBackgroundTask(taskId: String) -> Int {
        return backgroundManager.stopTask(taskId: taskId)
    }

    /// Submit a background task.
    @objc public func submitBackgroundTask(taskId: String) {
        backgroundManager.submitTask(taskId: taskId)
    }

    // MARK: - CoreML / ANE Inference

    /// Check if CoreML is available.
    @objc public func isCoreMLAvailable() -> Bool {
        return coreMLManager.isAvailable
    }

    /// Check if ANE is available.
    @objc public func isANEAvailable() -> Bool {
        return neuralEngine.isAvailable
    }

    /// Get the best available inference backend.
    @objc public func getBestBackend() -> Int {
        if neuralEngine.isAvailable {
            return AinosInferenceBackend.ane.rawValue
        }
        if coreMLManager.isAvailable {
            return AinosInferenceBackend.coreML.rawValue
        }
        return AinosInferenceBackend.cpu.rawValue
    }

    /// Load a CoreML model.
    @objc public func loadCoreMLModel(modelUrl: URL) -> Bool {
        return coreMLManager.loadModel(url: modelUrl)
    }

    /// Run inference using CoreML.
    @objc public func runCoreMLInference(modelId: String, inputData: Data,
                                          completion: @escaping (Int, Data?) -> Void) {
        inferenceQueue.async { [weak self] in
            guard let self = self else { return }

            // Check thermal conditions
            if self.shouldThrottleInference() {
                os_log("Inference throttled: thermal=%d", log: self.logger,
                       type: .error, self.getThermalStatus())
                completion(AinosStatusThermalThrottled.rawValue, nil)
                return
            }

            // Check battery
            if self.getBatteryLevel() <= 10 && !self.isCharging() {
                os_log("Inference blocked: battery low", log: self.logger, type: .error)
                completion(AinosStatusBatteryLow.rawValue, nil)
                return
            }

            self.coreMLManager.runInference(modelId: modelId, inputData: inputData) {
                status, outputData in
                completion(status, outputData)
            }
        }
    }

    // MARK: - Device Information

    /// Get device information as a dictionary.
    @objc public func getDeviceInfo() -> [String: Any] {
        let device = UIDevice.current
        let processInfo = ProcessInfo.processInfo

        var info: [String: Any] = [:]
        info["model"] = device.model
        info["systemName"] = device.systemName
        info["systemVersion"] = device.systemVersion
        info["name"] = device.name
        info["identifier"] = UIDevice.current.identifierForVendor?.uuidString ?? "unknown"
        info["isLowPowerMode"] = processInfo.isLowPowerModeEnabled
        info["processorCount"] = processInfo.processorCount
        info["activeProcessorCount"] = processInfo.activeProcessorCount
        info["physicalMemory"] = processInfo.physicalMemory
        info["thermalState"] = processInfo.thermalState.rawValue
        info["hasANE"] = neuralEngine.isAvailable
        info["hasCoreML"] = coreMLManager.isAvailable
        info["screenWidth"] = UIScreen.main.bounds.width
        info["screenHeight"] = UIScreen.main.bounds.height
        info["screenScale"] = UIScreen.main.scale
        info["batteryLevel"] = getBatteryLevel()
        info["batteryStatus"] = getBatteryStatus()
        info["isCharging"] = isCharging()
        info["thermalStatus"] = getThermalStatus()
        info["platformVersion"] = getVersion()
        info["appName"] = appName
        info["appVersion"] = appVersion

        return info
    }

    /// Get device info as JSON string.
    @objc public func getDeviceInfoJSON() -> String {
        let info = getDeviceInfo()
        if let jsonData = try? JSONSerialization.data(withJSONObject: info, options: []),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            return jsonString
        }
        return "{}"
    }

    // MARK: - Notifications

    /// Show a local notification.
    @objc public func showNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil)

        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                os_log("Failed to show notification: %@", log: self.logger,
                       type: .error, error.localizedDescription)
            }
        }
    }

    /// Schedule a notification for future delivery.
    @objc public func scheduleNotification(title: String, body: String,
                                            timeInterval: TimeInterval) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let trigger = UNTimeIntervalNotificationTrigger(
            timeInterval: timeInterval,
            repeats: false)

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: trigger)

        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                os_log("Failed to schedule notification: %@", log: self.logger,
                       type: .error, error.localizedDescription)
            }
        }
    }

    // MARK: - Private Methods

    private func registerForNotifications() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) {
            granted, error in
            if granted {
                os_log("Notification permission granted", log: self.logger, type: .info)
            } else if let error = error {
                os_log("Notification permission denied: %@", log: self.logger,
                       type: .error, error.localizedDescription)
            }
        }
    }

    private func startDaemonListener() {
        daemonQueue.async { [weak self] in
            guard let self = self else { return }

            var buffer = [UInt8](repeating: 0, count: 4096)

            while self.daemonConnected && self.daemonSocket >= 0 {
                let bytesRead = read(self.daemonSocket, &buffer, buffer.count)
                guard bytesRead > 0 else {
                    os_log("Daemon socket closed", log: self.logger, type: .warning)
                    self.disconnectDaemon()
                    return
                }

                // Process messages
                self.processDaemonMessage(Data(bytes: buffer, count: bytesRead))
            }
        }
    }

    private func processDaemonMessage(_ data: Data) {
        guard data.count >= 12 else { return }

        let command = UInt16(data[0]) << 8 | UInt16(data[1])
        let payloadSize = Int(UInt32(data[8]) << 24 |
                              UInt32(data[9]) << 16 |
                              UInt32(data[10]) << 8 |
                              UInt32(data[11]))

        os_log("Daemon message: command=0x%04x size=%d",
               log: logger, type: .debug, command, payloadSize)

        switch command {
        case 0x0001: // Heartbeat
            break
        case 0x0040: // Push notification
            if payloadSize > 0 && data.count >= 12 + payloadSize {
                let payload = data.subdata(in: 12..<(12 + payloadSize))
                if let message = String(data: payload, encoding: .utf8) {
                    showNotification(title: "Ainos", body: message)
                }
            }
        default:
            break
        }
    }

    private func sendRegister() {
        let deviceInfo = getDeviceInfoJSON()
        if let data = deviceInfo.data(using: .utf8) {
            sendDaemonCommand(command: 0x0003, payload: data) { _, _ in }
        }
    }

    private func handleThermalChange(oldStatus: Int, newStatus: Int) {
        thermalCallback?(oldStatus, newStatus)
    }

    private func handleBatteryChange(level: Int, status: Int) {
        batteryCallback?(level, status)
    }
}