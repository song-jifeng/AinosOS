import Foundation
import CoreML
import Accelerate
import os.log

/// AinosCoreML - CoreML integration for on-device AI inference.
/// Manages model compilation, loading, and execution using Apple's CoreML framework.
@objc public class AinosCoreML: NSObject {

    // MARK: - Properties

    private let logger = OSLog(subsystem: "com.ainos.platform", category: "AinosCoreML")
    private var loadedModels: [String: MLModel] = [:]
    private var compiledModelURLs: [String: URL] = [:]
    private let computeUnits: MLComputeUnits
    private let queue = DispatchQueue(label: "com.ainos.coreml", qos: .userInitiated,
                                       attributes: .concurrent)

    /// Whether CoreML is available on this device.
    @objc public private(set) var isAvailable: Bool = false

    /// Number of loaded models.
    @objc public var loadedModelCount: Int {
        return loadedModels.count
    }

    // MARK: - Initialization

    override init() {
        // Check CoreML availability - available on iOS 11+
        if #available(iOS 12.0, *) {
            // Use ANE if available (A12+)
            if MLModelDescription.supportsComputeDevice(.ane) {
                computeUnits = .all
            } else {
                computeUnits = .cpuAndGPU
            }
            isAvailable = true
        } else if #available(iOS 11.0, *) {
            computeUnits = .cpuAndGPU
            isAvailable = true
        } else {
            computeUnits = .cpuOnly
            isAvailable = false
        }

        super.init()
        os_log("CoreML initialized: available=%d computeUnits=%d",
               log: logger, type: .info, isAvailable, computeUnits.rawValue)
    }

    /// Initialize the CoreML manager.
    @objc public func initialize() {
        os_log("CoreML manager ready: %@", log: logger, type: .info,
               isAvailable ? "available" : "not available")
    }

    /// Release all loaded models.
    @objc public func release() {
        queue.async(flags: .barrier) { [weak self] in
            guard let self = self else { return }
            self.loadedModels.removeAll()
            self.compiledModelURLs.removeAll()
            os_log("CoreML models released", log: self.logger, type: .info)
        }
    }

    // MARK: - Model Management

    /// Load a CoreML model from a URL.
    /// - Parameter url: File URL to the .mlmodelc or .mlpackage
    /// - Returns: true if loading succeeded
    @objc public func loadModel(url: URL) -> Bool {
        guard isAvailable else {
            os_log("CoreML not available", log: logger, type: .error)
            return false
        }

        let modelId = url.lastPathComponent

        // Check if already loaded
        if loadedModels[modelId] != nil {
            os_log("Model already loaded: %@", log: logger, type: .info, modelId)
            return true
        }

        do {
            let config = MLModelConfiguration()
            config.computeUnits = computeUnits

            // Set preferred device if ANE is available
            if #available(iOS 16.0, *) {
                if MLModelDescription.supportsComputeDevice(.ane) {
                    config.preferredComputeDevice = .ane
                }
            }

            // Compile model if it's a .mlmodel file
            var modelURL = url
            if url.pathExtension == "mlmodel" {
                let compiledURL = try MLModel.compileModel(at: url)
                modelURL = compiledURL
                compiledModelURLs[modelId] = compiledURL
            }

            // Load model
            let model = try MLModel(contentsOf: modelURL, configuration: config)
            loadedModels[modelId] = model

            os_log("Model loaded: %@ (%@)", log: logger, type: .info,
                   modelId, model.modelDescription.metadata[.description] ?? "")

            // Log input/output info
            for input in model.modelDescription.inputDescriptionsByName {
                os_log("  Input: %@ (%@)", log: logger, type: .debug,
                       input.key, input.value.dataType)
            }
            for output in model.modelDescription.outputDescriptionsByName {
                os_log("  Output: %@ (%@)", log: logger, type: .debug,
                       output.key, output.value.dataType)
            }

            return true

        } catch {
            os_log("Failed to load model %@: %@", log: logger, type: .error,
                   modelId, error.localizedDescription)
            return false
        }
    }

    /// Unload a model.
    @objc public func unloadModel(modelId: String) {
        queue.async(flags: .barrier) { [weak self] in
            guard let self = self else { return }
            self.loadedModels.removeValue(forKey: modelId)
            if let compiledURL = self.compiledModelURLs.removeValue(forKey: modelId) {
                try? FileManager.default.removeItem(at: compiledURL)
            }
            os_log("Model unloaded: %@", log: self.logger, type: .info, modelId)
        }
    }

    /// Check if a model is loaded.
    @objc public func isModelLoaded(modelId: String) -> Bool {
        return loadedModels[modelId] != nil
    }

    // MARK: - Inference

    /// Run inference on a loaded model.
    /// - Parameters:
    ///   - modelId: Model identifier
    ///   - inputData: Input data as bytes
    ///   - completion: Callback with status and output data
    @objc public func runInference(modelId: String, inputData: Data,
                                    completion: @escaping (Int, Data?) -> Void) {
        guard let model = loadedModels[modelId] else {
            os_log("Model not loaded: %@", log: logger, type: .error, modelId)
            completion(AinosStatusModelNotFound.rawValue, nil)
            return
        }

        queue.async { [weak self] in
            guard let self = self else { return }

            let startTime = CACurrentMediaTime()

            do {
                // Build input features from model description
                var inputFeatures: [String: Any] = [:]
                var inputIndex = 0

                for input in model.modelDescription.inputDescriptionsByName {
                    let inputName = input.key
                    let inputDescription = input.value

                    switch inputDescription.dataType {
                    case .multiArray:
                        // Convert input data to MLMultiArray
                        let shape = inputDescription.multiArrayConstraint?.shape ?? [1]
                        let multiArray = try MLMultiArray(
                            shape: shape,
                            dataType: .float32)
                        let count = inputData.count / MemoryLayout<Float32>.size
                        let ptr = multiArray.dataPointer.bindMemory(to: Float32.self,
                                                                     capacity: count)
                        inputData.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
                            if let base = bytes.baseAddress {
                                memcpy(ptr, base, min(inputData.count,
                                                      count * MemoryLayout<Float32>.size))
                            }
                        }
                        inputFeatures[inputName] = multiArray

                    case .image:
                        // Convert input data to CGImage
                        if let image = UIImage(data: inputData)?.cgImage {
                            inputFeatures[inputName] = image
                        }

                    case .double:
                        inputData.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
                            if let base = bytes.baseAddress {
                                let value = base.bindMemory(to: Double.self, capacity: 1).pointee
                                inputFeatures[inputName] = value
                            }
                        }

                    case .int64:
                        inputData.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
                            if let base = bytes.baseAddress {
                                let value = base.bindMemory(to: Int64.self, capacity: 1).pointee
                                inputFeatures[inputName] = value
                            }
                        }

                    case .string:
                        if let str = String(data: inputData, encoding: .utf8) {
                            inputFeatures[inputName] = str
                        }

                    default:
                        os_log("Unsupported input type: %@", log: self.logger,
                               type: .error, String(describing: inputDescription.dataType))
                    }

                    inputIndex += 1
                }

                // Create feature provider
                let featureProvider = try MLDictionaryFeatureProvider(
                    dictionary: inputFeatures)

                // Run prediction
                let output = try model.prediction(from: featureProvider)

                // Extract output data
                var outputData = Data()

                for outputFeature in output.featureNames {
                    guard let featureValue = output.featureValue(for: featureName) else {
                        continue
                    }

                    switch featureValue.type {
                    case .multiArray:
                        if let multiArray = featureValue.multiArrayValue {
                            let count = multiArray.count
                            let ptr = multiArray.dataPointer.bindMemory(to: Float32.self,
                                                                         capacity: count)
                            outputData.append(UnsafeBufferPointer(start: ptr, count: count))
                        }

                    case .image:
                        if let image = featureValue.imageBufferValue {
                            // Convert CVPixelBuffer to Data
                            let ciImage = CIImage(cvPixelBuffer: image)
                            let context = CIContext()
                            if let cgImage = context.createCGImage(ciImage, from: ciImage.extent),
                               let data = UIImage(cgImage: cgImage).pngData() {
                                outputData = data
                            }
                        }

                    case .double:
                        var value = featureValue.doubleValue
                        outputData.append(UnsafeBufferPointer(start: &value, count: 1))

                    case .int64:
                        var value = featureValue.int64Value
                        outputData.append(UnsafeBufferPointer(start: &value, count: 1))

                    case .string:
                        if let str = featureValue.stringValue {
                            outputData.append(str.data(using: .utf8) ?? Data())
                        }

                    default:
                        break
                    }
                }

                let inferenceTime = (CACurrentMediaTime() - startTime) * 1000
                os_log("Inference complete: %@ time=%.2fms output=%d bytes",
                       log: self.logger, type: .info, modelId, inferenceTime,
                       outputData.count)

                completion(AinosStatusOk.rawValue, outputData)

            } catch {
                let inferenceTime = (CACurrentMediaTime() - startTime) * 1000
                os_log("Inference failed: %@ time=%.2fms error=%@",
                       log: self.logger, type: .error, modelId, inferenceTime,
                       error.localizedDescription)
                completion(AinosStatusInferenceFailed.rawValue, nil)
            }
        }
    }

    /// Get model metadata.
    @objc public func getModelMetadata(modelId: String) -> [String: Any]? {
        guard let model = loadedModels[modelId] else { return nil }

        var metadata: [String: Any] = [:]
        let desc = model.modelDescription

        metadata["modelId"] = modelId
        metadata["description"] = desc.metadata[.description] ?? ""
        metadata["version"] = desc.metadata[.versionString] ?? ""
        metadata["author"] = desc.metadata[.author] ?? ""
        metadata["license"] = desc.metadata[.license] ?? ""

        var inputNames: [String] = []
        for input in desc.inputDescriptionsByName {
            inputNames.append(input.key)
        }
        metadata["inputNames"] = inputNames

        var outputNames: [String] = []
        for output in desc.outputDescriptionsByName {
            outputNames.append(output.key)
        }
        metadata["outputNames"] = outputNames

        metadata["computeUnits"] = computeUnits.rawValue

        if #available(iOS 16.0, *) {
            metadata["supportsANE"] = MLModelDescription.supportsComputeDevice(.ane)
        }

        return metadata
    }
}