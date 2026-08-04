// Ainos OS - macOS Menu Bar Application
// ============================================================================
//
// AinosMenuBar is a SwiftUI menu bar app that provides system tray access
// to AinosOS services on macOS. It communicates with the Ainos daemon
// via XPC services.
//
// Features:
//   - Status icon in the menu bar with thermal state indicator
//   - Dashboard quick access (inference, model management, system stats)
//   - Model management (load/unload/list)
//   - Resource usage display (CPU temp, power mode, thread count)
//   - Auto-launch on login via ServiceManagement
//   - Quick action buttons for common tasks
//
// Requirements:
//   - macOS 11.0+ (Big Sur)
//   - Swift 5.0+
//   - SwiftUI framework
//   - ServiceManagement framework
//
// Build:
//   swiftc -o AinosMenuBar AinosMenuBar.swift \
//     -framework SwiftUI -framework Cocoa \
//     -framework ServiceManagement -framework UserNotifications

import Cocoa
import SwiftUI
import ServiceManagement
import UserNotifications
import Foundation

// ============================================================================
// Constants
// ============================================================================

private let kAinosDaemonLabel = "com.ainos.daemon"
private let kAinosXPCSerivce = "com.ainos.daemon.xpc"
private let kAinosDaemonPort: UInt16 = 9500
private let kAinosDaemonHost = "127.0.0.1"
private let kAinosThermalPolicyFile = "/var/run/ainos/thermal_policy"
private let kAinosIPCConnectionTimeout: TimeInterval = 5.0
private let kAinosStatusRefreshInterval: TimeInterval = 5.0
private let kAinosThermalRefreshInterval: TimeInterval = 2.0

// ============================================================================
// Thermal State
// ============================================================================

enum ThermalZone: String, Codable {
    case cool = "COOL"
    case warm = "WARM"
    case hot = "HOT"
    case critical = "CRITICAL"
    case unknown = "UNKNOWN"

    var color: NSColor {
        switch self {
        case .cool:     return .systemGreen
        case .warm:     return .systemYellow
        case .hot:      return .systemOrange
        case .critical: return .systemRed
        case .unknown:  return .gray
        }
    }

    var icon: String {
        switch self {
        case .cool:     return "❄️"
        case .warm:     return "🌡️"
        case .hot:      return "🔥"
        case .critical: return "☢️"
        case .unknown:  return "❓"
        }
    }
}

enum PowerMode: String, Codable {
    case max = "MAX"
    case balanced = "BALANCED"
    case efficient = "EFFICIENT"
    case emergency = "EMERGENCY"
    case unknown = "UNKNOWN"

    var description: String {
        switch self {
        case .max:       return "Maximum Performance"
        case .balanced:  return "Balanced"
        case .efficient: return "Power Efficient"
        case .emergency: return "Emergency Throttling"
        case .unknown:   return "Unknown"
        }
    }
}

enum PowerSource: String, Codable {
    case ac = "AC"
    case battery = "BATTERY"
    case ups = "UPS"
    case unknown = "UNKNOWN"
}

// ============================================================================
// Models
// ============================================================================

struct ThermalSnapshot: Codable {
    var cpuTempCelsius: Double = 40.0
    var gpuTempCelsius: Double = 0.0
    var zone: ThermalZone = .cool
    var powerMode: PowerMode = .max
    var recommendedThreads: Int = 4
    var sensorAvailable: Bool = false
    var throttleActive: Bool = false
    var powerSource: PowerSource = .unknown
    var batteryPercentage: Double = -1.0
    var batteryCycleCount: Int = -1

    enum CodingKeys: String, CodingKey {
        case cpuTempCelsius = "cpu_temp"
        case gpuTempCelsius = "gpu_temp"
        case zone = "zone"
        case powerMode = "mode"
        case recommendedThreads = "threads"
        case sensorAvailable = "sensor_available"
        case throttleActive = "throttle_active"
        case powerSource = "power_source"
        case batteryPercentage = "battery_pct"
        case batteryCycleCount = "battery_cycles"
    }
}

struct DaemonStatus: Codable {
    var uptime: UInt64 = 0
    var modelsLoaded: UInt32 = 0
    var totalRequests: UInt64 = 0
    var networkAvailable: Bool = false
    var activeSessions: UInt32 = 0
    var rateLimits: [RateLimitInfo]? = nil

    enum CodingKeys: String, CodingKey {
        case uptime = "uptime"
        case modelsLoaded = "models_loaded"
        case totalRequests = "total_requests"
        case networkAvailable = "network_available"
        case activeSessions = "active_sessions"
        case rateLimits = "rate_limits"
    }
}

struct RateLimitInfo: Codable {
    var category: String = ""
    var limit: UInt64 = 0
    var remaining: UInt64 = 0
    var resetSeconds: UInt64 = 0
}

struct ModelInfo: Codable, Identifiable {
    var id: String = ""
    var name: String = ""
    var path: String = ""
    var sizeMB: UInt64 = 0
    var loaded: Bool = false
    var architecture: String = ""

    enum CodingKeys: String, CodingKey {
        case id = "id"
        case name = "name"
        case path = "path"
        case sizeMB = "size_mb"
        case loaded = "loaded"
        case architecture = "architecture"
    }
}

// ============================================================================
// App Delegate
// ============================================================================

@main
class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {

    // MARK: - Properties

    private var statusItem: NSStatusItem!
    private var statusMenu: NSMenu!
    private var thermalStateMenuItem: NSMenuItem!
    private var daemonStatusMenuItem: NSMenuItem!
    private var modelManagementMenuItem: NSMenuItem!
    private var thermalTimer: Timer?
    private var statusTimer: Timer?
    private var currentThermal: ThermalSnapshot = ThermalSnapshot()
    private var currentStatus: DaemonStatus = DaemonStatus()
    private var models: [ModelInfo] = []

    // MARK: - Application Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Set up the menu bar item
        statusItem = NSStatusBar.system.statusItem(
            withLength: NSStatusItem.variableLength)

        // Build the menu
        buildMenu()

        // Register for user notifications
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }

        // Start monitoring timers
        startTimers()

        // Register for auto-launch
        registerForAutoLaunch()

        // Initial data fetch
        refreshAll()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopTimers()
    }

    // MARK: - Menu Building

    private func buildMenu() {
        statusMenu = NSMenu()

        // Header
        let headerItem = NSMenuItem(
            title: "AinosOS Daemon",
            action: nil,
            keyEquivalent: "")
        headerItem.attributedTitle = NSAttributedString(
            string: "AinosOS Daemon",
            attributes: [
                .font: NSFont.boldSystemFont(ofSize: 13),
                .foregroundColor: NSColor.labelColor
            ])
        statusMenu.addItem(headerItem)
        statusMenu.addItem(NSMenuItem.separator())

        // Thermal state
        thermalStateMenuItem = NSMenuItem(
            title: "Thermal: --",
            action: #selector(openDashboard),
            keyEquivalent: "t")
        thermalStateMenuItem.target = self
        thermalStateMenuItem.toolTip = "Click to open dashboard"
        statusMenu.addItem(thermalStateMenuItem)

        // Daemon status
        daemonStatusMenuItem = NSMenuItem(
            title: "Status: --",
            action: nil,
            keyEquivalent: "")
        statusMenu.addItem(daemonStatusMenuItem)

        // Model management
        modelManagementMenuItem = NSMenuItem(
            title: "Models: --",
            action: #selector(openModelManagement),
            keyEquivalent: "m")
        modelManagementMenuItem.target = self
        statusMenu.addItem(modelManagementMenuItem)

        statusMenu.addItem(NSMenuItem.separator())

        // Dashboard
        let dashboardItem = NSMenuItem(
            title: "Open Dashboard...",
            action: #selector(openDashboard),
            keyEquivalent: "d")
        dashboardItem.target = self
        statusMenu.addItem(dashboardItem)

        // Model Management
        let modelItem = NSMenuItem(
            title: "Model Management...",
            action: #selector(openModelManagement),
            keyEquivalent: "m")
        modelItem.target = self
        statusMenu.addItem(modelItem)

        statusMenu.addItem(NSMenuItem.separator())

        // Quick actions
        let quickActionsTitle = NSMenuItem(
            title: "Quick Actions",
            action: nil,
            keyEquivalent: "")
        quickActionsTitle.attributedTitle = NSAttributedString(
            string: "Quick Actions",
            attributes: [.font: NSFont.boldSystemFont(ofSize: 12)])
        statusMenu.addItem(quickActionsTitle)

        // Restart daemon
        let restartItem = NSMenuItem(
            title: "Restart Daemon",
            action: #selector(restartDaemon),
            keyEquivalent: "r")
        restartItem.target = self
        statusMenu.addItem(restartItem)

        // Reload config
        let reloadConfigItem = NSMenuItem(
            title: "Reload Configuration",
            action: #selector(reloadConfig),
            keyEquivalent: "l")
        reloadConfigItem.target = self
        statusMenu.addItem(reloadConfigItem)

        // Toggle auto-launch
        let autoLaunchItem = NSMenuItem(
            title: "Launch at Login",
            action: #selector(toggleAutoLaunch),
            keyEquivalent: "")
        autoLaunchItem.target = self
        autoLaunchItem.state = isAutoLaunchEnabled() ? .on : .off
        autoLaunchItem.tag = 100 // Tag for identifying this item
        statusMenu.addItem(autoLaunchItem)

        statusMenu.addItem(NSMenuItem.separator())

        // About
        let aboutItem = NSMenuItem(
            title: "About AinosOS",
            action: #selector(showAbout),
            keyEquivalent: "")
        aboutItem.target = self
        statusMenu.addItem(aboutItem)

        // Quit
        let quitItem = NSMenuItem(
            title: "Quit",
            action: #selector(quitApp),
            keyEquivalent: "q")
        quitItem.target = self
        statusMenu.addItem(quitItem)

        // Set the menu
        statusItem.menu = statusMenu

        // Update the status bar icon
        updateStatusBarIcon()
    }

    // MARK: - Timers

    private func startTimers() {
        // Thermal refresh (every 2 seconds)
        thermalTimer = Timer.scheduledTimer(
            timeInterval: kAinosThermalRefreshInterval,
            target: self,
            selector: #selector(refreshThermal),
            userInfo: nil,
            repeats: true)

        // Status refresh (every 5 seconds)
        statusTimer = Timer.scheduledTimer(
            timeInterval: kAinosStatusRefreshInterval,
            target: self,
            selector: #selector(refreshStatus),
            userInfo: nil,
            repeats: true)
    }

    private func stopTimers() {
        thermalTimer?.invalidate()
        thermalTimer = nil
        statusTimer?.invalidate()
        statusTimer = nil
    }

    // MARK: - Data Refresh

    @objc private func refreshAll() {
        refreshThermal()
        refreshStatus()
    }

    @objc private func refreshThermal() {
        DispatchQueue.global(qos: .background).async { [weak self] in
            guard let self = self else { return }

            // Read thermal policy file
            let snapshot = self.readThermalPolicy()
            self.currentThermal = snapshot

            DispatchQueue.main.async {
                self.updateThermalDisplay()
                self.updateStatusBarIcon()
            }
        }
    }

    @objc private func refreshStatus() {
        DispatchQueue.global(qos: .background).async { [weak self] in
            guard let self = self else { return }

            // Connect to daemon and query status
            let status = self.queryDaemonStatus()
            self.currentStatus = status

            let models = self.queryModelList()
            self.models = models

            DispatchQueue.main.async {
                self.updateStatusDisplay()
                self.updateModelDisplay()
            }
        }
    }

    // MARK: - Thermal Policy File Reading

    private func readThermalPolicy() -> ThermalSnapshot {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: kAinosThermalPolicyFile)),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return ThermalSnapshot()
        }

        var snapshot = ThermalSnapshot()

        if let cpuTemp = json["cpu_temp"] as? Double {
            snapshot.cpuTempCelsius = cpuTemp
        }
        if let gpuTemp = json["gpu_temp"] as? Double {
            snapshot.gpuTempCelsius = gpuTemp
        }
        if let zoneStr = json["zone"] as? String {
            snapshot.zone = ThermalZone(rawValue: zoneStr) ?? .unknown
        }
        if let modeStr = json["mode"] as? String {
            snapshot.powerMode = PowerMode(rawValue: modeStr) ?? .unknown
        }
        if let threads = json["threads"] as? Int {
            snapshot.recommendedThreads = threads
        }
        if let available = json["sensor_available"] as? Bool {
            snapshot.sensorAvailable = available
        }
        if let throttle = json["throttle_active"] as? Bool {
            snapshot.throttleActive = throttle
        }
        if let source = json["power_source"] as? String {
            snapshot.powerSource = PowerSource(rawValue: source) ?? .unknown
        }
        if let batteryPct = json["battery_pct"] as? Double {
            snapshot.batteryPercentage = batteryPct
        }
        if let cycles = json["battery_cycles"] as? Int {
            snapshot.batteryCycleCount = cycles
        }

        return snapshot
    }

    // MARK: - Daemon IPC Communication

    private func sendIPC(message: [String: Any]) -> [String: Any]? {
        var response: [String: Any]? = nil

        let semaphore = DispatchSemaphore(value: 0)

        DispatchQueue.global(qos: .utility).async {
            // Create TCP connection to daemon
            var addr = sockaddr_in()
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = CFSwapInt16HostToBig(kAinosDaemonPort)
            inet_pton(AF_INET, kAinosDaemonHost, &addr.sin_addr)

            let fd = socket(AF_INET, SOCK_STREAM, 0)
            guard fd >= 0 else { semaphore.signal(); return }

            // Set timeout
            var timeout = timeval(tv_sec: Int32(kAinosIPCConnectionTimeout), tv_usec: 0)
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))

            // Connect
            var connectResult: Int32
            withUnsafePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    connectResult = connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }

            guard connectResult == 0 else {
                close(fd)
                semaphore.signal()
                return
            }

            // Send JSON message
            if let jsonData = try? JSONSerialization.data(withJSONObject: message),
               let jsonStr = String(data: jsonData, encoding: .utf8) {
                var sendData = jsonStr + "\n"
                sendData.withUTF8 { ptr in
                    let _ = send(fd, ptr.baseAddress, ptr.count, 0)
                }
            }

            // Read response
            var buffer = [UInt8](repeating: 0, count: 65536)
            let n = read(fd, &buffer, buffer.count)
            if n > 0 {
                let data = Data(bytes: buffer, count: n)
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    response = json
                }
            }

            close(fd)
            semaphore.signal()
        }

        _ = semaphore.wait(timeout: .now() + kAinosIPCConnectionTimeout + 1.0)
        return response
    }

    private func queryDaemonStatus() -> DaemonStatus {
        let response = sendIPC(message: ["type": "Status"])
        guard let resp = response else { return DaemonStatus() }

        var status = DaemonStatus()

        if let uptime = resp["uptime"] as? UInt64 { status.uptime = uptime }
        if let models = resp["models_loaded"] as? UInt32 { status.modelsLoaded = models }
        if let requests = resp["total_requests"] as? UInt64 { status.totalRequests = requests }
        if let network = resp["network_available"] as? Bool { status.networkAvailable = network }
        if let sessions = resp["active_sessions"] as? UInt32 { status.activeSessions = sessions }

        return status
    }

    private func queryModelList() -> [ModelInfo] {
        let response = sendIPC(message: ["type": "ModelList"])
        guard let resp = response,
              let modelsData = resp["models"] as? [[String: Any]] else {
            return []
        }

        return modelsData.compactMap { dict in
            guard let id = dict["id"] as? String else { return nil }
            return ModelInfo(
                id: id,
                name: dict["name"] as? String ?? "",
                path: dict["path"] as? String ?? "",
                sizeMB: dict["size_mb"] as? UInt64 ?? 0,
                loaded: dict["loaded"] as? Bool ?? false,
                architecture: dict["architecture"] as? String ?? ""
            )
        }
    }

    private func sendModelLoad(path: String) -> Bool {
        let response = sendIPC(message: [
            "type": "ModelLoad",
            "path": path
        ])
        return response?["status"] as? String == "loaded"
    }

    private func sendModelUnload(modelId: String) -> Bool {
        let response = sendIPC(message: [
            "type": "ModelUnload",
            "model_id": modelId
        ])
        return response?["status"] as? String == "unloaded"
    }

    // MARK: - UI Updates

    private func updateStatusBarIcon() {
        let thermalIcon = currentThermal.zone.icon
        if let button = statusItem.button {
            button.title = " Ainos \(thermalIcon)"
            button.toolTip = "AinosOS: \(currentThermal.zone.rawValue) " +
                             "\(String(format: "%.1f", currentThermal.cpuTempCelsius))°C"

            // Set the button's image
            let iconSize = NSSize(width: 18, height: 18)
            let image = NSImage(size: iconSize)
            image.lockFocus()

            // Draw the thermal indicator
            let color = currentThermal.zone.color
            color.setFill()

            if currentThermal.zone == .critical || currentThermal.zone == .hot {
                // Draw a filled circle with attention
                let circle = NSBezierPath(ovalIn: NSRect(x: 0, y: 0, width: 16, height: 16))
                circle.fill()

                // White border
                NSColor.white.setStroke()
                circle.lineWidth = 1.0
                circle.stroke()
            }

            image.unlockFocus()
            // Note: For a cleaner look, we use text-based icon instead
            // The thermal icon emoji is shown in the title
        }
    }

    private func updateThermalDisplay() {
        let thermal = currentThermal
        let zoneIcon = thermal.zone.icon
        let tempStr = String(format: "%.1f°C", thermal.cpuTempCelsius)

        var title = "\(zoneIcon) Thermal: \(tempStr) | \(thermal.powerMode.rawValue)"
        if thermal.throttleActive {
            title += " (Throttling)"
        }
        if thermal.powerSource == .battery {
            title += " | Battery: \(String(format: "%.0f", thermal.batteryPercentage))%"
        }

        thermalStateMenuItem.title = title

        // Color the thermal state
        let attrString = NSMutableAttributedString(string: title)
        attrString.addAttribute(.foregroundColor,
                                value: thermal.zone.color,
                                range: NSRange(location: 0, length: title.count))
        thermalStateMenuItem.attributedTitle = attrString
    }

    private func updateStatusDisplay() {
        let status = currentStatus

        let uptimeStr = formatUptime(seconds: status.uptime)
        daemonStatusMenuItem.title = "Status: Uptime \(uptimeStr) | " +
                                     "\(status.modelsLoaded) models | " +
                                     "\(status.totalRequests) requests"
    }

    private func updateModelDisplay() {
        let loadedCount = models.filter { $0.loaded }.count
        modelManagementMenuItem.title = "Models: \(loadedCount) loaded / \(models.count) total"
    }

    private func formatUptime(seconds: UInt64) -> String {
        let days = seconds / 86400
        let hours = (seconds % 86400) / 3600
        let minutes = (seconds % 3600) / 60

        if days > 0 {
            return "\(days)d \(hours)h \(minutes)m"
        } else if hours > 0 {
            return "\(hours)h \(minutes)m"
        } else {
            return "\(minutes)m"
        }
    }

    // MARK: - Actions

    @objc private func openDashboard() {
        let dashboardVC = DashboardViewController(
            thermal: currentThermal,
            status: currentStatus,
            models: models)

        // Create a popover or window for the dashboard
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 500),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false)
        window.title = "AinosOS Dashboard"
        window.contentViewController = dashboardVC
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func openModelManagement() {
        let modelVC = ModelManagementViewController(models: models)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 400),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false)
        window.title = "AinosOS Model Management"
        window.contentViewController = modelVC
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func restartDaemon() {
        let alert = NSAlert()
        alert.messageText = "Restart Ainos Daemon?"
        alert.informativeText = "This will stop and restart the Ainos AI daemon service."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Restart")
        alert.addButton(withTitle: "Cancel")

        if alert.runModal() == .alertFirstButtonReturn {
            restartDaemonProcess()
        }
    }

    @objc private func reloadConfig() {
        // Reload configuration by sending a SIGHUP to the daemon
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["kill", "-HUP", kAinosDaemonLabel]
        task.launch()
        task.waitUntilExit()

        showNotification(title: "AinosOS", body: "Configuration reloaded")
    }

    @objc private func toggleAutoLaunch() {
        let isEnabled = isAutoLaunchEnabled()
        setAutoLaunchEnabled(!isEnabled)

        // Update the menu item state
        if let item = statusMenu.item(withTag: 100) {
            item.state = isEnabled ? .off : .on
        }

        let message = isEnabled ? "Auto-launch disabled" : "Auto-launch enabled"
        showNotification(title: "AinosOS", body: message)
    }

    @objc private func showAbout() {
        let alert = NSAlert()
        alert.messageText = "AinosOS Menu Bar"
        alert.informativeText = """
        Version: 1.0.0
        Platform: macOS
        Ainos AI System Daemon Controller

        AinosOS is an AI-native operating system
        that integrates AI capabilities at every level.
        """
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @objc private func quitApp() {
        stopTimers()
        NSApplication.shared.terminate(nil)
    }

    // MARK: - Daemon Control

    private func restartDaemonProcess() {
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["stop", kAinosDaemonLabel]
        task.launch()
        task.waitUntilExit()

        // Give it a moment, then start again
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            let startTask = Process()
            startTask.launchPath = "/bin/launchctl"
            startTask.arguments = ["start", kAinosDaemonLabel]
            startTask.launch()
            startTask.waitUntilExit()

            self.showNotification(title: "AinosOS", body: "Daemon restarted")
        }
    }

    // MARK: - Auto-Launch

    private func registerForAutoLaunch() {
        // Register for ServiceManagement auto-launch
        // This is handled by the SMAppService API (macOS 13+)
        if #available(macOS 13.0, *) {
            do {
                let appService = SMAppService.mainApp
                try appService.register()
            } catch {
                // Auto-launch registration is optional
                print("Failed to register auto-launch: \(error)")
            }
        } else {
            // Fallback for older macOS versions
            SMLoginItemSetEnabled("com.ainos.menubar" as CFString, true)
        }
    }

    private func isAutoLaunchEnabled() -> Bool {
        if #available(macOS 13.0, *) {
            return SMAppService.mainApp.status == .enabled
        } else {
            // Check via SMLoginItemSetEnabled
            return false
        }
    }

    private func setAutoLaunchEnabled(_ enabled: Bool) {
        if #available(macOS 13.0, *) {
            do {
                if enabled {
                    try SMAppService.mainApp.register()
                } else {
                    try SMAppService.mainApp.unregister()
                }
            } catch {
                print("Failed to set auto-launch: \(error)")
            }
        } else {
            SMLoginItemSetEnabled("com.ainos.menubar" as CFString, enabled)
        }
    }

    // MARK: - Notifications

    private func showNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = UNNotificationSound.default

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil)

        UNUserNotificationCenter.current().add(request)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    // MARK: - Status Bar Icon

    private func createStatusBarIcon() -> NSImage {
        let icon = NSImage(size: NSSize(width: 16, height: 16))
        icon.lockFocus()

        // Draw a simple "A" icon for Ainos
        let color = currentThermal.zone.color
        color.setFill()

        let rect = NSRect(x: 0, y: 0, width: 16, height: 16)
        let path = NSBezierPath(roundedRect: rect, xRadius: 3, yRadius: 3)
        path.fill()

        // Draw "A" letter
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.boldSystemFont(ofSize: 11),
            .foregroundColor: NSColor.white
        ]
        let letter = NSAttributedString(string: "A", attributes: attrs)
        letter.draw(at: NSPoint(x: 4, y: 2))

        icon.unlockFocus()
        return icon
    }
}

// ============================================================================
// Dashboard View Controller
// ============================================================================

class DashboardViewController: NSViewController {

    private let thermal: ThermalSnapshot
    private let status: DaemonStatus
    private let models: [ModelInfo]

    init(thermal: ThermalSnapshot, status: DaemonStatus, models: [ModelInfo]) {
        self.thermal = thermal
        self.status = status
        self.models = models
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 400, height: 500))
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        setupUI()
    }

    private func setupUI() {
        let stackView = NSStackView()
        stackView.orientation = .vertical
        stackView.alignment = .leading
        stackView.spacing = 12
        stackView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stackView)

        NSLayoutConstraint.activate([
            stackView.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            stackView.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            stackView.topAnchor.constraint(equalTo: view.topAnchor, constant: 20),
        ])

        // Title
        let titleLabel = NSTextField(labelWithString: "AinosOS Dashboard")
        titleLabel.font = .boldSystemFont(ofSize: 18)
        stackView.addArrangedSubview(titleLabel)

        stackView.addArrangedSubview(createSeparator())

        // Thermal section
        let thermalLabel = NSTextField(labelWithString: "Thermal State")
        thermalLabel.font = .boldSystemFont(ofSize: 14)
        stackView.addArrangedSubview(thermalLabel)

        let tempStr = String(format: "CPU Temperature: %.1f°C", thermal.cpuTempCelsius)
        let tempLabel = NSTextField(labelWithString: tempStr)
        stackView.addArrangedSubview(tempLabel)

        let zoneLabel = NSTextField(labelWithString: "Zone: \(thermal.zone.rawValue) \(thermal.zone.icon)")
        stackView.addArrangedSubview(zoneLabel)

        let modeLabel = NSTextField(labelWithString: "Mode: \(thermal.powerMode.rawValue) - \(thermal.powerMode.description)")
        stackView.addArrangedSubview(modeLabel)

        let threadLabel = NSTextField(labelWithString: "Recommended Threads: \(thermal.recommendedThreads)")
        stackView.addArrangedSubview(threadLabel)

        let throttleLabel = NSTextField(labelWithString: "Throttling: \(thermal.throttleActive ? "YES" : "NO")")
        throttleLabel.textColor = thermal.throttleActive ? .systemRed : .systemGreen
        stackView.addArrangedSubview(throttleLabel)

        stackView.addArrangedSubview(createSeparator())

        // Power section
        let powerLabel = NSTextField(labelWithString: "Power")
        powerLabel.font = .boldSystemFont(ofSize: 14)
        stackView.addArrangedSubview(powerLabel)

        let sourceLabel = NSTextField(labelWithString: "Source: \(thermal.powerSource.rawValue)")
        stackView.addArrangedSubview(sourceLabel)

        if thermal.powerSource == .battery {
            let batteryLabel = NSTextField(labelWithString: "Battery: \(String(format: "%.0f", thermal.batteryPercentage))%")
            stackView.addArrangedSubview(batteryLabel)
        }

        stackView.addArrangedSubview(createSeparator())

        // Daemon section
        let daemonLabel = NSTextField(labelWithString: "Daemon Status")
        daemonLabel.font = .boldSystemFont(ofSize: 14)
        stackView.addArrangedSubview(daemonLabel)

        let uptimeLabel = NSTextField(labelWithString: "Uptime: \(formatDuration(status.uptime))")
        stackView.addArrangedSubview(uptimeLabel)

        let modelsLabel = NSTextField(labelWithString: "Models Loaded: \(status.modelsLoaded)")
        stackView.addArrangedSubview(modelsLabel)

        let reqLabel = NSTextField(labelWithString: "Total Requests: \(status.totalRequests)")
        stackView.addArrangedSubview(reqLabel)

        let sessLabel = NSTextField(labelWithString: "Active Sessions: \(status.activeSessions)")
        stackView.addArrangedSubview(sessLabel)

        let networkLabel = NSTextField(labelWithString: "Network: \(status.networkAvailable ? "Available" : "Offline")")
        networkLabel.textColor = status.networkAvailable ? .systemGreen : .systemOrange
        stackView.addArrangedSubview(networkLabel)
    }

    private func createSeparator() -> NSBox {
        let separator = NSBox()
        separator.boxType = .separator
        separator.translatesAutoresizingMaskIntoConstraints = false
        separator.heightAnchor.constraint(equalToConstant: 1).isActive = true
        return separator
    }

    private func formatDuration(_ seconds: UInt64) -> String {
        let days = seconds / 86400
        let hours = (seconds % 86400) / 3600
        let minutes = (seconds % 3600) / 60
        let secs = seconds % 60

        if days > 0 {
            return "\(days)d \(hours)h \(minutes)m \(secs)s"
        } else if hours > 0 {
            return "\(hours)h \(minutes)m \(secs)s"
        } else if minutes > 0 {
            return "\(minutes)m \(secs)s"
        } else {
            return "\(secs)s"
        }
    }
}

// ============================================================================
// Model Management View Controller
// ============================================================================

class ModelManagementViewController: NSViewController, NSTableViewDataSource, NSTableViewDelegate {

    private var models: [ModelInfo] = []
    private let tableView = NSTableView()
    private let loadButton = NSButton(title: "Load Model", target: nil, action: nil)
    private let unloadButton = NSButton(title: "Unload Model", target: nil, action: nil)
    private let refreshButton = NSButton(title: "Refresh", target: nil, action: nil)

    init(models: [ModelInfo]) {
        self.models = models
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 500, height: 400))
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        setupUI()
    }

    private func setupUI() {
        // Title
        let titleLabel = NSTextField(labelWithString: "Model Management")
        titleLabel.font = .boldSystemFont(ofSize: 16)
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(titleLabel)

        // Table view
        let scrollView = NSScrollView()
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.hasVerticalScroller = true
        scrollView.documentView = tableView
        view.addSubview(scrollView)

        // Table columns
        let nameColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("name"))
        nameColumn.title = "Model Name"
        nameColumn.width = 150
        tableView.addTableColumn(nameColumn)

        let sizeColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("size"))
        sizeColumn.title = "Size (MB)"
        sizeColumn.width = 80
        tableView.addTableColumn(sizeColumn)

        let statusColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("status"))
        statusColumn.title = "Status"
        statusColumn.width = 80
        tableView.addTableColumn(statusColumn)

        let archColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("arch"))
        archColumn.title = "Architecture"
        archColumn.width = 100
        tableView.addTableColumn(archColumn)

        tableView.dataSource = self
        tableView.delegate = self
        tableView.reloadData()

        // Buttons
        let buttonStack = NSStackView()
        buttonStack.orientation = .horizontal
        buttonStack.spacing = 8
        buttonStack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(buttonStack)

        loadButton.target = self
        loadButton.action = #selector(loadModel)
        buttonStack.addArrangedSubview(loadButton)

        unloadButton.target = self
        unloadButton.action = #selector(unloadModel)
        buttonStack.addArrangedSubview(unloadButton)

        refreshButton.target = self
        refreshButton.action = #selector(refreshModels)
        buttonStack.addArrangedSubview(refreshButton)

        // Layout
        NSLayoutConstraint.activate([
            titleLabel.topAnchor.constraint(equalTo: view.topAnchor, constant: 16),
            titleLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),

            scrollView.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 12),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
            scrollView.bottomAnchor.constraint(equalTo: buttonStack.topAnchor, constant: -12),

            buttonStack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            buttonStack.bottomAnchor.constraint(equalTo: view.bottomAnchor, constant: -16),
        ])
    }

    // MARK: - Table View Data Source

    func numberOfRows(in tableView: NSTableView) -> Int {
        return models.count
    }

    func tableView(_ tableView: NSTableView, objectValueFor tableColumn: NSTableColumn?, row: Int) -> Any? {
        guard row < models.count else { return nil }
        let model = models[row]

        switch tableColumn?.identifier.rawValue {
        case "name":   return model.name
        case "size":   return "\(model.sizeMB)"
        case "status": return model.loaded ? "Loaded" : "Unloaded"
        case "arch":   return model.architecture
        default:       return ""
        }
    }

    func tableView(_ tableView: NSTableView, willDisplayCell cell: Any, for tableColumn: NSTableColumn?, row: Int) {
        guard row < models.count,
              let cell = cell as? NSTextFieldCell else { return }

        let model = models[row]
        if tableColumn?.identifier.rawValue == "status" {
            cell.textColor = model.loaded ? .systemGreen : .secondaryLabelColor
        }
    }

    // MARK: - Actions

    @objc private func loadModel() {
        let dialog = NSOpenPanel()
        dialog.title = "Select a Model File"
        dialog.allowedFileTypes = ["gguf", "ggml", "onnx", "bin"]
        dialog.allowsMultipleSelection = false

        if dialog.runModal() == .OK, let url = dialog.url {
            let appDelegate = NSApplication.shared.delegate as? AppDelegate
            _ = appDelegate?.sendModelLoad(path: url.path)
            refreshModels()
        }
    }

    @objc private func unloadModel() {
        let selectedRow = tableView.selectedRow
        guard selectedRow >= 0 && selectedRow < models.count else { return }

        let model = models[selectedRow]
        let appDelegate = NSApplication.shared.delegate as? AppDelegate
        _ = appDelegate?.sendModelUnload(modelId: model.id)
        refreshModels()
    }

    @objc private func refreshModels() {
        let appDelegate = NSApplication.shared.delegate as? AppDelegate
        // Re-fetch model list
        DispatchQueue.global().async { [weak self] in
            let newModels = appDelegate?.queryModelList() ?? []
            DispatchQueue.main.async {
                self?.models = newModels
                self?.tableView.reloadData()
            }
        }
    }
}