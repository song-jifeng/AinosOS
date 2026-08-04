import Foundation
import UIKit
import BackgroundTasks
import os.log

/// AinosBackground - iOS background task management for the Ainos platform.
/// Handles registration, scheduling, and execution of background tasks
/// including model downloads, inference, and daemon communication.
@objc public class AinosBackground: NSObject {

    // MARK: - Constants

    private static let taskPrefix = "com.ainos.background."

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosBackground")
    private var registeredTasks: [String: BGTaskRequest] = [:]
    private var taskHandlers: [String: (String) -> Void] = [:]
    private var activeTasks: Set<String> = []

    /// Whether background tasks are supported on this device.
    @objc public var isSupported: Bool {
        if #available(iOS 13.0, *) {
            return true
        }
        return false
    }

    /// Number of registered tasks.
    @objc public var registeredTaskCount: Int {
        return registeredTasks.count
    }

    /// Number of active tasks.
    @objc public var activeTaskCount: Int {
        return activeTasks.count
    }

    // MARK: - Initialization

    override init() {
        super.init()
        os_log("Background task manager initialized", log: logger, type: .info)
    }

    /// Register all standard Ainos background tasks.
    @objc public func registerTasks() {
        if #available(iOS 13.0, *) {
            // Register task identifiers
            let taskIds = [
                "model_download",
                "inference",
                "daemon_sync",
                "maintenance",
                "update_check"
            ]

            for taskId in taskIds {
                let fullId = Self.taskPrefix + taskId
                BGTaskScheduler.shared.register(forTaskWithIdentifier: fullId, using: nil) {
                    [weak self] task in
                    self?.handleTask(task)
                }
                os_log("Registered background task: %@", log: logger, type: .info, fullId)
            }

            os_log("All background tasks registered", log: logger, type: .info)
        }
    }

    /// Unregister all tasks.
    @objc public func unregisterAllTasks() {
        registeredTasks.removeAll()
        taskHandlers.removeAll()
        activeTasks.removeAll()
        os_log("All background tasks unregistered", log: logger, type: .info)
    }

    // MARK: - Task Registration

    /// Register a background task.
    /// - Parameters:
    ///   - taskId: Task identifier
    ///   - taskName: Display name for the task
    ///   - interval: Minimum interval between executions
    /// - Returns: Status code
    @objc public func registerTask(taskId: String, taskName: String,
                                    interval: TimeInterval) -> Int {
        if #available(iOS 13.0, *) {
            let fullId = Self.taskPrefix + taskId

            // Check if already registered
            if registeredTasks[fullId] != nil {
                return AinosStatusAlreadyInitialized.rawValue
            }

            let request = BGProcessingTaskRequest(identifier: fullId)
            request.requiresNetworkConnectivity = true
            request.requiresExternalPower = false
            request.earliestBeginDate = Date(timeIntervalSinceNow: interval)

            registeredTasks[fullId] = request

            os_log("Task registered: %@ (%@) interval=%.0fs",
                   log: logger, type: .info, fullId, taskName, interval)

            return AinosStatusOk.rawValue
        }
        return AinosStatusNotSupported.rawValue
    }

    /// Start a background task.
    /// - Parameter taskId: Task identifier
    /// - Returns: Status code
    @objc public func startTask(taskId: String) -> Int {
        if #available(iOS 13.0, *) {
            let fullId = Self.taskPrefix + taskId
            guard let request = registeredTasks[fullId] else {
                return AinosStatusGeneral.rawValue
            }

            do {
                try BGTaskScheduler.shared.submit(request)
                activeTasks.insert(taskId)
                os_log("Task started: %@", log: logger, type: .info, fullId)
                return AinosStatusOk.rawValue
            } catch {
                os_log("Failed to start task %@: %@", log: logger, type: .error,
                       fullId, error.localizedDescription)
                return AinosStatusGeneral.rawValue
            }
        }
        return AinosStatusNotSupported.rawValue
    }

    /// Stop a background task.
    /// - Parameter taskId: Task identifier
    /// - Returns: Status code
    @objc public func stopTask(taskId: String) -> Int {
        let fullId = Self.taskPrefix + taskId
        activeTasks.remove(taskId)
        os_log("Task stopped: %@", log: logger, type: .info, fullId)
        return AinosStatusOk.rawValue
    }

    /// Submit a background task for scheduling.
    /// - Parameter taskId: Task identifier
    @objc public func submitTask(taskId: String) {
        if #available(iOS 13.0, *) {
            let fullId = Self.taskPrefix + taskId
            guard let request = registeredTasks[fullId] else {
                os_log("Task not found: %@", log: logger, type: .error, fullId)
                return
            }

            do {
                try BGTaskScheduler.shared.submit(request)
                os_log("Task submitted: %@", log: logger, type: .info, fullId)
            } catch {
                os_log("Failed to submit task %@: %@", log: logger, type: .error,
                       fullId, error.localizedDescription)
            }
        }
    }

    /// Cancel all pending background tasks.
    @objc public func cancelAllTasks() {
        if #available(iOS 13.0, *) {
            BGTaskScheduler.shared.cancelAllTaskRequests()
            activeTasks.removeAll()
            os_log("All background tasks cancelled", log: logger, type: .info)
        }
    }

    /// Get the list of pending task identifiers.
    @objc public func getPendingTasks() -> [String] {
        return Array(registeredTasks.keys)
    }

    // MARK: - Task Handling

    @available(iOS 13.0, *)
    private func handleTask(_ task: BGTask) {
        let taskId = task.identifier.replacingOccurrences(of: Self.taskPrefix, with: "")
        activeTasks.insert(taskId)

        os_log("Background task executing: %@", log: logger, type: .info, task.identifier)

        // Create expiration handler
        task.expirationHandler = { [weak self] in
            os_log("Background task expired: %@", log: self?.logger ?? .default,
                   type: .warning, task.identifier)
            self?.activeTasks.remove(taskId)
            task.setTaskCompleted(success: false)
        }

        // Execute the task
        switch taskId {
        case "model_download":
            handleModelDownload(task: task)
        case "inference":
            handleInference(task: task)
        case "daemon_sync":
            handleDaemonSync(task: task)
        case "maintenance":
            handleMaintenance(task: task)
        case "update_check":
            handleUpdateCheck(task: task)
        default:
            os_log("Unknown background task: %@", log: logger, type: .error, taskId)
            task.setTaskCompleted(success: false)
        }

        // Resubmit the task for future execution
        resubmitTask(taskId: taskId)
    }

    @available(iOS 13.0, *)
    private func handleModelDownload(task: BGTask) {
        os_log("Executing model download task", log: logger, type: .info)
        // In production, check for pending model downloads and resume them
        task.setTaskCompleted(success: true)
    }

    @available(iOS 13.0, *)
    private func handleInference(task: BGTask) {
        os_log("Executing background inference task", log: logger, type: .info)
        // In production, trigger model warmup or pre-computation
        task.setTaskCompleted(success: true)
    }

    @available(iOS 13.0, *)
    private func handleDaemonSync(task: BGTask) {
        os_log("Executing daemon sync task", log: logger, type: .info)
        // In production, sync state with AinosOS daemon
        task.setTaskCompleted(success: true)
    }

    @available(iOS 13.0, *)
    private func handleMaintenance(task: BGTask) {
        os_log("Executing maintenance task", log: logger, type: .info)
        // In production, clear cache, prune old models, etc.
        task.setTaskCompleted(success: true)
    }

    @available(iOS 13.0, *)
    private func handleUpdateCheck(task: BGTask) {
        os_log("Executing update check task", log: logger, type: .info)
        // In production, check for model updates
        task.setTaskCompleted(success: true)
    }

    private func resubmitTask(taskId: String) {
        if #available(iOS 13.0, *) {
            let fullId = Self.taskPrefix + taskId
            guard let request = registeredTasks[fullId] else { return }

            // Resubmit with updated interval
            request.earliestBeginDate = Date(timeIntervalSinceNow: 3600) // 1 hour

            do {
                try BGTaskScheduler.shared.submit(request)
            } catch {
                os_log("Failed to resubmit task %@: %@", log: logger, type: .error,
                       fullId, error.localizedDescription)
            }
        }
    }
}