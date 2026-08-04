import Foundation
import CoreML
import Metal
import MetalPerformanceShaders
import os.log

/// AinosNeuralEngine - Apple Neural Engine (ANE) integration.
/// Provides access to the ANE for accelerated neural network inference
/// on A12+ devices.
@objc public class AinosNeuralEngine: NSObject {

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosNeuralEngine")
    private var metalDevice: MTLDevice?
    private var commandQueue: MTLCommandQueue?
    private var isANEQueryComplete = false

    /// Whether the ANE is available on this device.
    @objc public private(set) var isAvailable: Bool = false

    /// ANE capabilities description.
    @objc public var capabilities: String {
        var caps: [String] = []
        if isAvailable { caps.append("ANE") }
        if metalDevice != nil { caps.append("GPU") }
        return caps.joined(separator: ", ")
    }

    /// ANE compute device if available.
    @available(iOS 16.0, *)
    var aneDevice: MLComputeDevice? {
        return MLModelDescription.supportedComputeDevices.first { $0.ane != nil }
    }

    // MARK: - Initialization

    override init() {
        super.init()
        detectANE()
    }

    /// Initialize the ANE manager.
    @objc public func initialize() {
        detectANE()
        setupMetal()

        os_log("Neural Engine initialized: available=%d metal=%@ capabilities=%@",
               log: logger, type: .info, isAvailable,
               metalDevice != nil ? "yes" : "no", capabilities)
    }

    /// Release ANE resources.
    @objc public func release() {
        commandQueue = nil
        metalDevice = nil
        isAvailable = false
        os_log("Neural Engine released", log: logger, type: .info)
    }

    // MARK: - ANE Detection

    private func detectANE() {
        if #available(iOS 16.0, *) {
            isAvailable = MLModelDescription.supportsComputeDevice(.ane)
            if isAvailable {
                os_log("ANE detected via MLModelDescription", log: logger, type: .info)
                return
            }
        }

        // Fallback detection: check for ANE via device model
        isAvailable = detectANEByDeviceModel()
    }

    private func detectANEByDeviceModel() -> Bool {
        // ANE is available on A12+ devices (iPhone XS, XR, and later)
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        var machine = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        let model = String(cString: machine)

        // A12+ devices have ANE
        let aneModels: [String] = [
            "iPhone11,", "iPhone12,", "iPhone13,", "iPhone14,",
            "iPhone15,", "iPhone16,",
            "iPad8,", "iPad11,", "iPad12,", "iPad13,", "iPad14,",
            "iPad15,", "iPad16,",
            "iPod9,1"
        ]

        for prefix in aneModels {
            if model.hasPrefix(prefix) {
                os_log("ANE detected via device model: %@", log: logger, type: .info, model)
                return true
            }
        }

        // Check for Apple Silicon Macs
        let appleSiliconModels: [String] = ["Mac14,", "Mac15,", "Mac13,"]
        for prefix in appleSiliconModels {
            if model.hasPrefix(prefix) {
                os_log("ANE detected on Apple Silicon: %@", log: logger, type: .info, model)
                return true
            }
        }

        // Check for A12+ via sysctl
        var cpuSubtype: UInt32 = 0
        var cpuSubtypeSize = MemoryLayout<UInt32>.size
        sysctlbyname("hw.cpusubtype", &cpuSubtype, &cpuSubtypeSize, nil, 0)

        // CPU subtype values for A12+ (ARM64E)
        if cpuSubtype == 2 { // CPU_SUBTYPE_ARM64E
            os_log("ANE detected via CPU subtype: %d", log: logger, type: .info, cpuSubtype)
            return true
        }

        return false
    }

    private func setupMetal() {
        metalDevice = MTLCreateSystemDefaultDevice()
        if let device = metalDevice {
            commandQueue = device.makeCommandQueue()
            os_log("Metal device: %@", log: logger, type: .info, device.name)
        }
    }

    /// Check if the device has a GPU that can be used alongside ANE.
    @objc public func hasGPU() -> Bool {
        return metalDevice != nil
    }

    /// Get the Metal device name.
    @objc public func getGPUName() -> String {
        return metalDevice?.name ?? "No GPU"
    }

    /// Get the maximum buffer length for ANE.
    @objc public func getMaxBufferLength() -> Int {
        // ANE typically supports up to 16MB per buffer
        return 16 * 1024 * 1024
    }

    /// Get a recommended model size for ANE.
    @objc public func getRecommendedModelSize() -> Int {
        if isAvailable {
            return 500_000_000 // 500MB for ANE models
        }
        return 100_000_000 // 100MB for CPU-only
    }

    /// Check if a specific model architecture is ANE-compatible.
    @objc public func isModelANECompatible(modelInfo: [String: Any]) -> Bool {
        guard isAvailable else { return false }

        // ANE works best with specific operation types
        if let format = modelInfo["format"] as? Int {
            // CoreML format is required for ANE
            if format == AinosModelFormat.coreML.rawValue {
                return true
            }
        }

        // Check for supported operations
        if let operations = modelInfo["operations"] as? [String] {
            let supportedOps = Set([
                "convolution", "fullyConnected", "batchnorm",
                "relu", "sigmoid", "tanh", "softmax",
                "averagePool", "maxPool", "reshape",
                "concat", "add", "mul", "transpose"
            ])
            let ops = Set(operations)
            return ops.isSubset(of: supportedOps)
        }

        return false
    }

    /// Get performance estimate for ANE vs CPU.
    /// - Returns: Speedup factor (1.0 = same, >1 = faster on ANE)
    @objc public func getANESpeedup() -> Float {
        guard isAvailable else { return 1.0 }

        // ANE typically provides 2-10x speedup over CPU
        // This is a rough estimate
        if let device = metalDevice {
            if device.supportsFamily(.apple9) {
                return 8.0 // A17+ series
            }
            if device.supportsFamily(.apple8) {
                return 6.0 // A16 series
            }
            if device.supportsFamily(.apple7) {
                return 5.0 // A15 series
            }
            if device.supportsFamily(.apple6) {
                return 4.0 // A14 series
            }
            if device.supportsFamily(.apple5) {
                return 3.0 // A13 series
            }
            if device.supportsFamily(.apple4) {
                return 2.5 // A12 series
            }
            if device.supportsFamily(.apple3) {
                return 2.0 // A11 series
            }
        }
        return 2.0
    }

    /// Get the ANE compute device (iOS 16+).
    @available(iOS 16.0, *)
    @objc public func getANEDevice() -> MLComputeDevice? {
        return aneDevice
    }

    /// Run a simple Metal compute shader to verify GPU/ANE pipeline.
    @objc public func runTestCompute() -> Bool {
        guard let device = metalDevice, let queue = commandQueue else {
            return false
        }

        do {
            // Create a simple test kernel
            let kernelSource = """
                kernel void testKernel(
                    device float *input [[buffer(0)]],
                    device float *output [[buffer(1)]],
                    constant uint &count [[buffer(2)]],
                    uint id [[thread_position_in_grid]])
                {
                    if (id < count) {
                        output[id] = input[id] * 2.0;
                    }
                }
                """

            let library = try device.makeLibrary(source: kernelSource, options: nil)
            let function = library.makeFunction(name: "testKernel")
            guard let pipelineState = try? device.makeComputePipelineState(function: function!) else {
                return false
            }

            let count = 1024
            let inputBuffer = device.makeBuffer(
                length: count * MemoryLayout<Float>.size,
                options: .storageModeShared)
            let outputBuffer = device.makeBuffer(
                length: count * MemoryLayout<Float>.size,
                options: .storageModeShared)

            guard let input = inputBuffer, let output = outputBuffer else {
                return false
            }

            // Fill input with test data
            let inputPtr = input.contents().bindMemory(to: Float.self, capacity: count)
            for i in 0..<count {
                inputPtr[i] = Float(i)
            }

            guard let commandBuffer = queue.makeCommandBuffer(),
                  let encoder = commandBuffer.makeComputeCommandEncoder() else {
                return false
            }

            encoder.setComputePipelineState(pipelineState)
            encoder.setBuffer(input, offset: 0, index: 0)
            encoder.setBuffer(output, offset: 0, index: 1)

            var countValue = UInt32(count)
            encoder.setBytes(&countValue, length: MemoryLayout<UInt32>.size, index: 2)

            let threadGroupSize = MTLSize(width: min(256, count), height: 1, depth: 1)
            let gridSize = MTLSize(width: count, height: 1, depth: 1)
            encoder.dispatchThreads(gridSize, threadsPerThreadgroup: threadGroupSize)
            encoder.endEncoding()

            commandBuffer.commit()
            commandBuffer.waitUntilCompleted()

            // Verify output
            let outputPtr = output.contents().bindMemory(to: Float.self, capacity: count)
            var success = true
            for i in 0..<count {
                if outputPtr[i] != Float(i) * 2.0 {
                    success = false
                    break
                }
            }

            os_log("Metal compute test: %@", log: logger, type: .info,
                   success ? "passed" : "failed")
            return success

        } catch {
            os_log("Metal compute test failed: %@", log: logger, type: .error,
                   error.localizedDescription)
            return false
        }
    }
}