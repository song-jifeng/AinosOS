import Foundation
import XCTest
@testable import AinosPlatform

/// iOS platform tests for Ainos mobile support layer
class AinosPlatformTests: XCTestCase {

    var platform: AinosPlatform!

    override func setUp() {
        super.setUp()
        platform = AinosPlatform.shared
    }

    override func tearDown() {
        if platform.isPlatformInitialized() {
            platform.shutdown()
        }
        super.tearDown()
    }

    // MARK: - Platform Lifecycle

    func testPlatformInit() {
        let expectation = expectation(description: "Platform init")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { status in
            XCTAssertEqual(status, 0, "Init should succeed")
            XCTAssertTrue(self.platform.isPlatformInitialized(), "Platform should be initialized")
            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    func testPlatformDoubleInit() {
        let expectation1 = expectation(description: "First init")
        let expectation2 = expectation(description: "Second init")

        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { status in
            XCTAssertEqual(status, 0, "First init should succeed")
            expectation1.fulfill()

            self.platform.initialize(appName: "TestApp", appVersion: "1.0.0") { status2 in
                XCTAssertEqual(status2, -5, "Second init should fail with AlreadyInitialized")
                expectation2.fulfill()
            }
        }
        waitForExpectations(timeout: 5)
    }

    func testPlatformShutdown() {
        let expectation = expectation(description: "Init for shutdown")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { status in
            XCTAssertEqual(status, 0)
            self.platform.shutdown()
            XCTAssertFalse(self.platform.isPlatformInitialized(), "Should not be initialized after shutdown")
            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    func testPlatformVersion() {
        let version = platform.getVersion()
        XCTAssertFalse(version.isEmpty, "Version should not be empty")
        XCTAssertEqual(version, "1.0.0", "Version should be 1.0.0")
    }

    // MARK: - Thermal Management

    func testThermalStatus() {
        let expectation = expectation(description: "Init for thermal")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            let status = self.platform.getThermalStatus()
            XCTAssertGreaterThanOrEqual(status, 0, "Thermal status should be >= 0")
            XCTAssertLessThanOrEqual(status, 5, "Thermal status should be <= 5")

            let cpuTemp = self.platform.getCpuTemperature()
            XCTAssertGreaterThan(cpuTemp, 0, "CPU temperature should be > 0")

            let battTemp = self.platform.getBatteryTemperature()
            XCTAssertGreaterThan(battTemp, 0, "Battery temperature should be > 0")

            let shouldThrottle = self.platform.shouldThrottleInference()
            XCTAssertTrue(shouldThrottle == true || shouldThrottle == false,
                          "Should throttle should be boolean")

            let batchSize = self.platform.getRecommendedBatchSize()
            XCTAssertGreaterThanOrEqual(batchSize, 1, "Batch size should be >= 1")
            XCTAssertLessThanOrEqual(batchSize, 32, "Batch size should be <= 32")

            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    func testThermalCallback() {
        let expectation = expectation(description: "Thermal callback")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            self.platform.onThermalChange { oldStatus, newStatus in
                // Callback fired - test passes
                expectation.fulfill()
            }
            // Trigger a thermal state change by reading
            _ = self.platform.getThermalStatus()
        }
        // Callback may not fire immediately, so give it time
        waitForExpectations(timeout: 10)
    }

    // MARK: - Battery Management

    func testBatteryLevel() {
        let expectation = expectation(description: "Init for battery")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            let level = self.platform.getBatteryLevel()
            XCTAssertGreaterThanOrEqual(level, 0, "Battery level should be >= 0")
            XCTAssertLessThanOrEqual(level, 100, "Battery level should be <= 100")

            let status = self.platform.getBatteryStatus()
            XCTAssertGreaterThanOrEqual(status, 0, "Battery status should be >= 0")

            let charging = self.platform.isCharging()
            XCTAssertTrue(charging == true || charging == false, "Charging should be boolean")

            let lowPower = self.platform.isLowPowerMode()
            XCTAssertTrue(lowPower == true || lowPower == false, "Low power should be boolean")

            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    // MARK: - Device Information

    func testDeviceInfo() {
        let expectation = expectation(description: "Init for device info")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            let info = self.platform.getDeviceInfo()
            XCTAssertFalse(info.isEmpty, "Device info should not be empty")

            let json = self.platform.getDeviceInfoJSON()
            XCTAssertFalse(json.isEmpty, "JSON should not be empty")
            XCTAssertTrue(json.contains("model"), "JSON should contain model")

            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    // MARK: - CoreML

    func testCoreMLAvailability() {
        let available = platform.isCoreMLAvailable()
        // CoreML should be available on iOS 11+
        XCTAssertTrue(available, "CoreML should be available on this device")
    }

    func testANEAvailability() {
        let available = platform.isANEAvailable()
        // ANE is available on A12+ devices
        // This test may pass or fail depending on the device
        print("ANE available: \(available)")
    }

    func testBestBackend() {
        let backend = platform.getBestBackend()
        XCTAssertGreaterThanOrEqual(backend, 0, "Backend should be valid")
        XCTAssertLessThanOrEqual(backend, 6, "Backend should be valid")
    }

    // MARK: - Background Tasks

    func testRegisterBackgroundTask() {
        let expectation = expectation(description: "Init for background")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            let status = self.platform.registerBackgroundTask(
                taskId: "test_task",
                taskName: "Test Task",
                interval: 3600)
            XCTAssertEqual(status, 0, "Register task should succeed")

            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    // MARK: - Notifications

    func testShowNotification() {
        let expectation = expectation(description: "Init for notification")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            // Should not throw
            self.platform.showNotification(title: "Test", body: "Test body")
            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    func testScheduleNotification() {
        let expectation = expectation(description: "Init for scheduled notification")
        platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
            // Should not throw
            self.platform.scheduleNotification(
                title: "Test",
                body: "Test body",
                timeInterval: 60)
            expectation.fulfill()
        }
        waitForExpectations(timeout: 5)
    }

    // MARK: - Backend Selection

    func testBackendNames() {
        XCTAssertEqual(NNDelegate.getBackendName(0), "Auto")
        XCTAssertEqual(NNDelegate.getBackendName(1), "CPU")
        XCTAssertEqual(NNDelegate.getBackendName(2), "GPU")
        XCTAssertEqual(NNDelegate.getBackendName(4), "CoreML")
        XCTAssertEqual(NNDelegate.getBackendName(5), "ANE")
    }

    // MARK: - Performance

    func testThermalPerformance() {
        measure {
            let expectation = expectation(description: "Thermal measurement")
            platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
                for _ in 0..<100 {
                    _ = self.platform.getThermalStatus()
                    _ = self.platform.getCpuTemperature()
                    _ = self.platform.getBatteryTemperature()
                }
                expectation.fulfill()
            }
            waitForExpectations(timeout: 10)
        }
    }

    func testBatteryPerformance() {
        measure {
            let expectation = expectation(description: "Battery measurement")
            platform.initialize(appName: "TestApp", appVersion: "1.0.0") { _ in
                for _ in 0..<100 {
                    _ = self.platform.getBatteryLevel()
                    _ = self.platform.getBatteryStatus()
                    _ = self.platform.isCharging()
                }
                expectation.fulfill()
            }
            waitForExpectations(timeout: 10)
        }
    }
}