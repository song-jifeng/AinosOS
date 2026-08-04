//===----------------------------------------------------------------------===//
//
// This source file is part of the Ainos SDK for Swift open source project
//
// Copyright (c) 2024 Ainos AI and the Ainos SDK project authors
// Licensed under Apache License v2.0
//
// See LICENSE.txt for license information
//
// SPDX-License-Identifier: Apache-2.0
//
//===----------------------------------------------------------------------===//

import Foundation
import AinosSDK

// MARK: - Basic Example

/// This example demonstrates the basic usage of the Ainos SDK.
///
/// It shows how to:
/// 1. Configure and connect to the Ainos daemon
/// 2. Perform non-streaming inference
/// 3. Perform streaming inference
/// 4. List, load, and unload models
/// 5. Check daemon health and status
/// 6. Store and retrieve context
///
/// Usage:
/// ```bash
/// swift run AinosSDKExample --token "your-token"
/// ```

// MARK: - Configuration

/// Parse command-line arguments
let arguments = ProcessInfo.processInfo.arguments
let tokenIndex = arguments.firstIndex(of: "--token")
let token = tokenIndex.map { arguments[$0 + 1] }

let hostIndex = arguments.firstIndex(of: "--host")
let host = hostIndex.map { arguments[$0 + 1] } ?? "127.0.0.1"

let portIndex = arguments.firstIndex(of: "--port")
let port = portIndex.flatMap { Int(arguments[$0 + 1]) } ?? 9500

// MARK: - Create Client

let config = AinosClientConfig(
    host: host,
    port: port,
    token: token,
    connectionTimeout: 10,
    readTimeout: 60,
    verbose: true
)

let client = AinosClient(config: config)

// MARK: - Run Example

Task {
    await runExample()
}

/// Runs the complete example.
func runExample() async {
    print("Ainos SDK Example")
    print("=================")
    print()

    do {
        // 1. Connect
        print("1. Connecting to Ainos daemon...")
        try await client.connect()
        print("   Connected to daemon v\(client.daemonVersion ?? "?")")
        print("   Session: \(client.sessionId ?? "?")")
        print()

        // 2. Check health
        print("2. Health check...")
        let health = try await client.health()
        print("   Healthy: \(health.healthy)")
        if let uptime = health.uptimeSeconds {
            print("   Uptime: \(uptime) seconds")
        }
        print()

        // 3. Get daemon status
        print("3. Daemon status...")
        let status = try await client.status()
        print("   State: \(status.state)")
        print("   Loaded models: \(status.loadedModels.count)")
        if let mem = status.systemMemory {
            print("   Memory: \(mem.usedBytes / 1_000_000)MB / \(mem.totalBytes / 1_000_000)MB")
        }
        print()

        // 4. List available models
        print("4. Listing models...")
        let modelList = try await client.modelList()
        print("   Available models (\(modelList.total)):")
        for model in modelList.models {
            let loaded = model.isLoaded ? " [loaded]" : ""
            print("     - \(model.id) (\(model.name ?? "?")\(loaded))")
        }
        print()

        // 5. Load a model
        if let firstModel = modelList.models.first {
            print("5. Loading model '\(firstModel.id)'...")
            let loadResult = try await client.modelLoad(
                model: firstModel.id,
                config: ModelLoadConfig(
                    gpuLayers: 0,
                    contextSize: 2048,
                    threads: 4
                )
            )
            print("   Load result: \(loadResult.message ?? "OK")")
            print()

            // 6. Non-streaming inference
            print("6. Non-streaming inference...")
            let response = try await client.infer(
                model: firstModel.id,
                prompt: "What is the capital of France?",
                config: InferenceConfig(
                    temperature: 0.7,
                    maxTokens: 100
                )
            )
            print("   Response: \(response.text)")
            if let usage = response.usage {
                print("   Tokens: \(usage.promptTokens) prompt + \(usage.completionTokens) completion = \(usage.totalTokens) total")
            }
            print()

            // 7. Chat-style inference
            print("7. Chat-style inference...")
            let messages = [
                Message(role: .system, content: "You are a helpful assistant."),
                Message(role: .user, content: "What is 2+2?")
            ]
            let chatResponse = try await client.chat(
                model: firstModel.id,
                messages: messages,
                config: InferenceConfig(temperature: 0.3, maxTokens: 50)
            )
            print("   Response: \(chatResponse.text)")
            print()

            // 8. Streaming inference
            print("8. Streaming inference...")
            let stream = try await client.inferStream(
                model: firstModel.id,
                prompt: "Count from 1 to 5.",
                config: InferenceConfig(maxTokens: 50)
            )
            print("   Stream: ", terminator: "")
            for try await event in stream {
                switch event.type {
                case .token:
                    print(event.delta ?? "", terminator: "")
                case .done:
                    print()
                    if let usage = event.usage {
                        print("   Stream tokens: \(usage.totalTokens)")
                    }
                case .error:
                    print(" [Error: \(event.delta ?? "?")]")
                default:
                    break
                }
            }
            print()

            // 9. Context store
            print("9. Context store...")
            let storeResult = try await client.contextStore(
                key: "example-key",
                value: ["timestamp": AnyCodable(Date().timeIntervalSince1970)],
                ttlSeconds: 3600
            )
            print("   Stored: \(storeResult.success)")

            // 10. Context retrieve
            print("10. Context retrieve...")
            let retrieveResult = try await client.contextRetrieve(key: "example-key")
            print("    Retrieved: \(retrieveResult.success)")
            if let value = retrieveResult.value {
                print("    Value: \(value)")
            }
            print()

            // 11. Unload the model
            print("11. Unloading model '\(firstModel.id)'...")
            let unloadResult = try await client.modelUnload(model: firstModel.id)
            print("    Unload result: \(unloadResult.message ?? "OK")")
            print()
        }

        // 12. Disconnect
        print("12. Disconnecting...")
        await client.disconnect()
        print("    Disconnected.")

        print()
        print("Example completed successfully!")

    } catch let error as AinosError {
        print("Error: [\(error.code.rawValue)] \(error.description)")
        if error.isRetryable {
            print("This error is retryable.")
        }
    } catch {
        print("Unexpected error: \(error.localizedDescription)")
    }
}

// Keep the main thread alive
dispatchMain()