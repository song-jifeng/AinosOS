import com.ainos.sdk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlin.system.exitProcess

/**
 * Example application demonstrating the Ainos Kotlin SDK.
 *
 * Run with: gradle :examples:run
 *
 * This example shows:
 * 1. Connecting to the Ainos daemon
 * 2. Checking health and status
 * 3. Listing available models
 * 4. Non-streaming and streaming inference
 * 5. Context management
 * 6. Error handling
 *
 * Usage: java MainKt [host] [port] [token]
 *   host  - Daemon hostname (default: localhost)
 *   port  - Daemon port (default: 9500)
 *   token - Bearer token (optional)
 */
suspend fun main(args: Array<String>) {
    val host = args.getOrElse(0) { "localhost" }
    val port = args.getOrElse(1) { "9500" }.toIntOrNull() ?: 9500
    val token = args.getOrElse(2) { "" }

    println("=" .repeat(60))
    println("  Ainos Kotlin SDK Example")
    println("  Connecting to $host:$port")
    println("=" .repeat(60))

    // ---- Build Configuration ----
    val config = ClientConfig {
        host(host)
        port(port)
        if (token.isNotBlank()) {
            this.token(token)
            println("  Using authentication token: ${token.take(8)}...")
        }
        connectTimeoutMs(10_000)
        requestTimeoutMs(120_000)
    }

    // ---- Create Client ----
    val client = AinosClient(config)

    try {
        // ---- Step 1: Connect ----
        println("\n[1] Connecting to Ainos daemon...")
        client.connect()
        println("    Connected: ${client.isConnected}")

        // ---- Step 2: Health Check ----
        println("\n[2] Checking daemon health...")
        val health = client.health()
        println("    Status:    ${health.status}")
        println("    Version:   ${health.version ?: "unknown"}")
        println("    Uptime:    ${health.uptime ?: 0}s")
        println("    Healthy:   ${health.isHealthy}")

        // ---- Step 3: Server Status ----
        println("\n[3] Getting server status...")
        try {
            val status = client.status()
            println("    Version:     ${status.version}")
            println("    Uptime:      ${status.uptime}s")
            println("    Active mods: ${status.activeModels}")
            println("    Total mods:  ${status.totalModels}")
            status.memoryUsage?.let { mem ->
                println("    Memory:      ${mem.current / 1024 / 1024}MB / ${mem.limit / 1024 / 1024}MB")
            }
            status.gpuInfo?.let { gpu ->
                println("    GPU:         ${gpu.device ?: "unknown"} (${gpu.utilization ?: 0}%)")
            }
        } catch (e: AinosException) {
            println("    Status unavailable: ${e.message}")
        }

        // ---- Step 4: List Models ----
        println("\n[4] Listing available models...")
        try {
            val models = client.modelList()
            if (models.isEmpty()) {
                println("    No models registered.")
            } else {
                println("    ${models.size} model(s) available:")
                models.forEachIndexed { i, model ->
                    println("    ${i + 1}. ${model.name}")
                    println("       Path:   ${model.filePath ?: "not specified"}")
                    println("       Loaded: ${if (model.loaded) "yes" else "no"}")
                    model.quantization?.let { println("       Quant:  $it") }
                    model.backend?.let { println("       Backend: $it") }
                    model.parameterCount?.let { println("       Params: $it") }
                }
            }
        } catch (e: AinosException) {
            println("    Cannot list models: ${e.message}")
        }

        // ---- Step 5: Non-Streaming Inference ----
        println("\n[5] Non-streaming inference...")
        try {
            val params = InferParams(
                prompt = "What is the meaning of life?",
                maxTokens = 100,
                temperature = 0.7f
            )
            val result = client.infer(params)
            println("    Response: ${result.text}")
            println("    Tokens:   ${result.tokens ?: "unknown"}")
            println("    Speed:    ${result.tokensPerSecond ?: "?"} tok/s")
            result.finishReason?.let { println("    Reason:   $it") }
        } catch (e: AinosException) {
            println("    Inference failed: ${e.message}")
        }

        // ---- Step 6: Streaming Inference ----
        println("\n[6] Streaming inference (type 'quit' to exit)...")
        while (true) {
            print("\n    Enter prompt: ")
            val input = readLine() ?: break
            if (input.lowercase() == "quit" || input.lowercase() == "exit") break

            try {
                println("    Response: ")
                print("    ")
                val fullText = client.inferStream(input, InferParams(
                    prompt = input,
                    maxTokens = 256,
                    temperature = 0.8f
                )).printCollected()
                println("    (${fullText.length} chars)")
            } catch (e: AinosException) {
                println("\n    Error: ${e.message}")
            }
        }

        // ---- Step 7: Context Management ----
        println("\n[7] Testing context management...")
        try {
            val ctxId = client.contextStore(
                content = "User's name is Alice and she likes AI.",
                metadata = mapOf("type" to "user_info"),
                model = "default"
            )
            println("    Stored context ID: $ctxId")

            val retrieved = client.contextRetrieve(ctxId)
            println("    Retrieved: ${retrieved.content}")
            println("    Metadata:  ${retrieved.metadata}")
        } catch (e: AinosException) {
            println("    Context operation failed: ${e.message}")
        }

        // ---- Step 8: Model Management ----
        println("\n[8] Testing model management...")
        try {
            // Try to load a model
            val loadResult = client.modelLoad("default")
            println("    Loaded: ${loadResult.name} (${if (loadResult.loaded) "yes" else "no"})")

            // Unload the model
            val unloadResult = client.modelUnload("default")
            println("    Unloaded: ${unloadResult.name} (success: ${unloadResult.success})")
        } catch (e: AinosException) {
            println("    Model management: ${e.message}")
        }

        // ---- Step 9: Update Token ----
        println("\n[9] Updating authentication token...")
        client.authentication.setToken("new-token-here")
        println("    Token updated: ${client.authentication.isAuthenticated}")

        // ---- Summary ----
        println("\n" + "=" .repeat(60))
        println("  Example completed successfully!")
        println("=" .repeat(60))

    } catch (e: AinosException.ConnectionException) {
        System.err.println("\nFailed to connect to Ainos daemon at $host:$port.")
        System.err.println("Make sure the daemon is running and accessible.")
        System.err.println("Error: ${e.message}")
        exitProcess(1)
    } catch (e: Exception) {
        System.err.println("\nUnexpected error: ${e.message}")
        e.printStackTrace()
        exitProcess(1)
    } finally {
        // ---- Cleanup ----
        println("\nDisconnecting...")
        client.disconnect()
        println("Done.")
    }
}