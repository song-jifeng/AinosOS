// swift-tools-version: 5.9
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

import PackageDescription
import CompilerPluginSupport

let package = Package(
    name: "AinosSDK",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
        .tvOS(.v16),
        .watchOS(.v9),
        .visionOS(.v1)
    ],
    products: [
        .library(
            name: "AinosSDK",
            targets: ["AinosSDK"]
        ),
        .executable(
            name: "AinosSDKExample",
            targets: ["AinosSDKExample"]
        )
    ],
    dependencies: [
        // No external dependencies required — uses Foundation's built-in
        // networking and Swift concurrency primitives.
    ],
    targets: [
        .target(
            name: "AinosSDK",
            dependencies: [],
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency"),
                .unsafeFlags(["-Xfrontend", "-warn-long-function-bodies=100"])
            ]
        ),
        .testTarget(
            name: "AinosSDKTests",
            dependencies: ["AinosSDK"],
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency")
            ]
        ),
        .executableTarget(
            name: "AinosSDKExample",
            dependencies: ["AinosSDK"],
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency")
            ]
        )
    ]
)