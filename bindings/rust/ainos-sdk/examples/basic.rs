//! Basic usage examples for the Ainos SDK.
//!
//! This file demonstrates all major features of the SDK, including:
//! - Basic inference
//! - Streaming inference
//! - Model management (list, load, unload)
//! - Context operations
//! - Status queries
//! - Error handling
//! - Connection management
//!
//! Run with: `cargo run --example basic`

use ainos_sdk::error::{Result, Retryable};
use ainos_sdk::prelude::*;
use std::time::Duration;

// ---------------------------------------------------------------------------
// Helper: create a client
// ---------------------------------------------------------------------------

/// Create a client connected to the daemon.
///
/// Reads the `AINOS_HOST`, `AINOS_PORT`, and `AINOS_TOKEN` environment
/// variables, falling back to sensible defaults.
async fn create_client() -> Result<AinosClient> {
    let host = std::env::var("AINOS_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port: u16 = std::env::var("AINOS_PORT")
        .unwrap_or_else(|_| "9500".to_string())
        .parse()
        .expect("AINOS_PORT must be a number");
    let token = std::env::var("AINOS_TOKEN").ok();

    let mut builder = AinosClient::builder()
        .host(host)
        .port(port)
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(Duration::from_secs(120));

    if let Some(t) = token {
        builder = builder.auth_token(t);
    }

    let client = builder.build();
    client.connect().await?;
    Ok(client)
}

// ---------------------------------------------------------------------------
// Example 1: Basic inference
// ---------------------------------------------------------------------------

/// Send a simple inference request and print the response.
async fn example_basic_inference(client: &AinosClient) -> Result<()> {
    println!("\n=== Basic Inference ===");

    let req = InferenceRequest::builder()
        .prompt("What is the meaning of life?")
        .model("default")
        .temperature(0.7)
        .max_tokens(200)
        .build();

    let resp = client.infer(&req).await?;

    println!("Prompt: {}", req.prompt);
    println!("Response: {}", resp.output);
    println!("Tokens generated: {}", resp.tokens_generated);
    println!("Inference time: {} ms", resp.inference_ms);
    println!("Source: {}", resp.source);

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 2: Streaming inference
// ---------------------------------------------------------------------------

/// Perform streaming inference, printing tokens as they arrive.
async fn example_streaming_inference(client: &AinosClient) -> Result<()> {
    println!("\n=== Streaming Inference ===");

    let req = InferenceRequest::builder()
        .prompt("Tell me a short story about a robot.")
        .model("default")
        .temperature(0.8)
        .max_tokens(500)
        .build();

    let mut stream = client.infer_stream(&req).await?;

    println!("Streaming response:");
    use futures::StreamExt;
    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(chunk) => {
                print!("{}", chunk.chunk);
                if chunk.done {
                    println!("\n[Stream complete]");
                    break;
                }
            }
            Err(e) => {
                eprintln!("\nStream error: {}", e);
                return Err(e);
            }
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 3: Streaming with collect_string
// ---------------------------------------------------------------------------

/// Use the convenience method to collect a stream into a single string.
async fn example_stream_collect(client: &AinosClient) -> Result<()> {
    println!("\n=== Stream Collect ===");

    let req = InferenceRequest::builder()
        .prompt("Say hello in 3 different languages.")
        .model("default")
        .max_tokens(200)
        .build();

    let mut stream = client.infer_stream(&req).await?;
    let text = stream.collect_string().await?;

    println!("Collected text: {}", text);
    Ok(())
}

// ---------------------------------------------------------------------------
// Example 4: Model management
// ---------------------------------------------------------------------------

/// List loaded models, then load and unload a model.
async fn example_model_management(client: &AinosClient) -> Result<()> {
    println!("\n=== Model Management ===");

    // List models
    println!("Listing models...");
    match client.model_list().await {
        Ok(models) => {
            if models.is_empty() {
                println!("  No models registered.");
            } else {
                for model in &models {
                    println!(
                        "  - {} ({}): {} MB, loaded: {}",
                        model.id, model.name, model.size_mb, model.loaded
                    );
                }
            }
        }
        Err(e) => {
            println!("  Failed to list models: {}", e);
        }
    }

    // Load a model (if path is provided via env)
    if let Ok(model_path) = std::env::var("AINOS_MODEL_PATH") {
        println!("Loading model from: {}", model_path);

        let opts = ModelLoadOptions::builder()
            .path(&model_path)
            .model_type("ggml")
            .gpu_layers(32)
            .context_size(4096)
            .use_mmap(true)
            .build();

        match client.model_load(&model_path, &opts).await {
            Ok(info) => {
                println!("  Model loaded: {} ({})", info.id, info.name);
            }
            Err(e) => {
                println!("  Failed to load model: {}", e);
            }
        }
    } else {
        println!("  Set AINOS_MODEL_PATH to test model loading.");
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 5: Context operations
// ---------------------------------------------------------------------------

/// Store and retrieve context entries.
async fn example_context_operations(client: &AinosClient) -> Result<()> {
    println!("\n=== Context Operations ===");

    let session_id = "example-session";
    let key = "my-key";
    let value = b"Hello from Rust SDK!";

    // Store
    println!("Storing context: {}:{} = {:?}", session_id, key, value);
    client
        .context_store(session_id, key, value, 3600)
        .await?;
    println!("  Stored successfully.");

    // Retrieve
    println!("Retrieving context...");
    match client.context_retrieve(session_id, key).await? {
        Some(data) => {
            let text = String::from_utf8_lossy(&data);
            println!("  Retrieved: {}", text);
        }
        None => {
            println!("  Key not found.");
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 6: Status and health
// ---------------------------------------------------------------------------

/// Query daemon status and health.
async fn example_status(client: &AinosClient) -> Result<()> {
    println!("\n=== Status & Health ===");

    // System status
    let status = client.status().await?;
    println!("System Status:");
    println!("  Uptime: {} seconds", status.uptime);
    println!("  Models loaded: {}", status.models_loaded);
    println!("  Total requests: {}", status.total_requests);
    println!("  Network available: {}", status.network_available);
    println!("  Active sessions: {}", status.active_sessions);

    if let Some(ref limits) = status.rate_limits {
        println!("  Rate Limits:");
        for limit in limits {
            println!(
                "    {}: {}/{} (reset in {}s)",
                limit.category, limit.remaining, limit.limit, limit.reset_seconds
            );
        }
    }

    // Health check
    let health = client.health().await?;
    println!("Health: {}", if health.healthy { "OK" } else { "DEGRADED" });
    println!("  Message: {}", health.message);
    println!("  Database: {}", health.database);
    println!("  Engine: {}", health.engine);
    println!("  Network: {}", health.network);

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 7: Rate limit status
// ---------------------------------------------------------------------------

/// Query rate limit information.
async fn example_rate_limits(client: &AinosClient) -> Result<()> {
    println!("\n=== Rate Limit Status ===");

    match client.rate_limit_status().await {
        Ok(status) => {
            for limit in &status.limits {
                println!(
                    "  {}: {}/{} remaining (resets in {}s)",
                    limit.category, limit.remaining, limit.limit, limit.reset_seconds
                );
            }
        }
        Err(e) => {
            println!("  Failed to query rate limits: {}", e);
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 8: Batch inference
// ---------------------------------------------------------------------------

/// Send multiple inference requests.
async fn example_batch_inference(client: &AinosClient) -> Result<()> {
    println!("\n=== Batch Inference ===");

    let prompts = vec![
        "What is 2+2?",
        "What is the capital of France?",
        "What color is the sky?",
    ];

    let reqs: Vec<InferenceRequest> = prompts
        .into_iter()
        .map(|p| InferenceRequest::builder().prompt(p).max_tokens(100).build())
        .collect();

    let responses = client.batch_infer(&reqs).await?;

    for (i, resp) in responses.iter().enumerate() {
        println!("  [{}] {}...", i + 1, &resp.output[..resp.output.len().min(80)]);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 9: Error handling
// ---------------------------------------------------------------------------

/// Demonstrates various error handling patterns.
async fn example_error_handling(client: &AinosClient) -> Result<()> {
    println!("\n=== Error Handling ===");

    // Try to unload a non-existent model
    match client.model_unload("nonexistent_model_xyz").await {
        Ok(()) => println!("  Unloaded successfully (unexpected)"),
        Err(e) => {
            println!("  Expected error: {}", e);
            match e.retry_kind() {
                ainos_sdk::RetryKind::Fatal => {
                    println!("    -> Fatal error, not retrying");
                }
                ainos_sdk::RetryKind::Transient => {
                    println!("    -> Transient error, can retry");
                }
                ainos_sdk::RetryKind::Throttled => {
                    println!("    -> Throttled, retry after backoff");
                }
            }
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Example 10: Connection management
// ---------------------------------------------------------------------------

/// Demonstrates explicit connection lifecycle management.
#[allow(dead_code)]
async fn example_connection_management() -> Result<()> {
    println!("\n=== Connection Management ===");

    let client = create_client().await?;
    println!("Connected to {}", client.config().host);

    // Check connection status
    println!("Is connected: {}", client.is_connected().await);
    println!("Is authenticated: {}", client.is_authenticated().await);

    // Disconnect
    client.disconnect().await?;
    println!("Disconnected");

    // Reconnect
    client.reconnect().await?;
    println!("Reconnected");

    Ok(())
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<()> {
    println!("Ainos SDK Examples");
    println!("==================");

    // Create client
    let client = create_client().await?;

    // Run examples
    example_basic_inference(&client).await?;
    example_streaming_inference(&client).await?;
    example_stream_collect(&client).await?;
    example_model_management(&client).await?;
    example_context_operations(&client).await?;
    example_status(&client).await?;
    example_rate_limits(&client).await?;
    example_batch_inference(&client).await?;
    example_error_handling(&client).await?;

    // Clean up
    client.disconnect().await?;
    println!("\nAll examples completed.");

    Ok(())
}

// ---------------------------------------------------------------------------
// Error handling for main
// ---------------------------------------------------------------------------

/// Run the connection management example independently.
#[allow(dead_code)]
async fn run_connection_example() {
    match example_connection_management().await {
        Ok(()) => println!("Connection example completed."),
        Err(e) => eprintln!("Connection example failed: {}", e),
    }
}