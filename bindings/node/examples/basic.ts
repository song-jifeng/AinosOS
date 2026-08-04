/**
 * Ainos SDK — Basic usage examples.
 *
 * Run with: `npx ts-node examples/basic.ts`
 *
 * These examples demonstrate:
 * - Basic inference
 * - Streaming inference
 * - Model management
 * - Context store
 * - Error handling
 * - Authentication
 * - Batch inference
 * - Health checks
 */

import {
  AinosClient,
  createClient,
  ConnectionError,
  AuthError,
  InferenceError,
  TimeoutError,
  RateLimitError,
  DaemonError,
  accumulateStream,
} from '../src';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// These can be overridden with environment variables
const HOST = process.env.AINOS_HOST || '127.0.0.1';
const PORT = parseInt(process.env.AINOS_PORT || '9500', 10);
const AUTH_TOKEN = process.env.AINOS_TOKEN || '';

// ============================================================================
// Example 1: Basic Inference
// ============================================================================

async function exampleBasicInference(): Promise<void> {
  console.log('\n=== Example 1: Basic Inference ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
    connectTimeout: 5000,
    readTimeout: 30000,
  });

  try {
    await client.connect();
    console.log('Connected to Ainos daemon');

    const response = await client.infer({
      prompt: 'What is Ainos OS?',
      model: 'default',
      temperature: 0.7,
      maxTokens: 256,
    });

    console.log('Response:', response.output);
    console.log(`Tokens: ${response.tokensGenerated}, Time: ${response.inferenceMs}ms, Source: ${response.source}`);
  } catch (err) {
    console.error('Inference error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 2: Streaming Inference
// ============================================================================

async function exampleStreamingInference(): Promise<void> {
  console.log('\n=== Example 2: Streaming Inference ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();
    console.log('Connected, starting streaming inference...\n');

    const stream = client.inferStream({
      prompt: 'Write a short poem about artificial intelligence.',
      model: 'default',
      temperature: 0.8,
      maxTokens: 500,
    });

    // Accumulate for display
    let fullText = '';

    stream.on('data', (chunk: string) => {
      process.stdout.write(chunk);
      fullText += chunk;
    });

    stream.on('progress', (tokens: number, elapsed: number) => {
      // Progress updates
    });

    stream.on('end', () => {
      console.log('\n\n--- Stream complete ---');
      console.log(`Total length: ${fullText.length} chars`);
    });

    stream.on('error', (err: Error) => {
      console.error('\nStream error:', err);
    });

    // Wait for stream to complete
    await stream.waitForEnd();
  } catch (err) {
    console.error('Streaming error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 3: Accumulate Stream to String
// ============================================================================

async function exampleAccumulateStream(): Promise<void> {
  console.log('\n=== Example 3: Accumulate Stream to String ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    const stream = client.inferStream({
      prompt: 'Explain machine learning in one paragraph.',
      maxTokens: 200,
    });

    const fullText = await accumulateStream(stream);
    console.log('Full output:', fullText);
    console.log(`Length: ${fullText.length} chars`);
  } catch (err) {
    console.error('Error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 4: Model Management
// ============================================================================

async function exampleModelManagement(): Promise<void> {
  console.log('\n=== Example 4: Model Management ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    // List models
    const models = await client.modelList();
    console.log(`Available models (${models.length}):`);
    for (const model of models) {
      const status = model.loaded ? 'loaded' : 'unloaded';
      console.log(`  - ${model.id} (${model.name}) [${status}] ${model.sizeMb}MB`);
    }

    // Load a model (if a path is provided)
    const modelPath = process.env.AINOS_MODEL_PATH;
    if (modelPath) {
      console.log(`\nLoading model from: ${modelPath}`);
      const loadResult = await client.modelLoad(modelPath);
      console.log(`Load result: ${loadResult.status} — ${loadResult.message}`);

      if (loadResult.modelInfo) {
        console.log(`Model ID: ${loadResult.modelInfo.id}`);
        console.log(`Architecture: ${loadResult.modelInfo.architecture}`);
      }

      // Unload the model
      if (loadResult.modelId) {
        console.log(`\nUnloading model: ${loadResult.modelId}`);
        await client.modelUnload(loadResult.modelId);
        console.log('Model unloaded successfully');
      }
    }
  } catch (err) {
    console.error('Model management error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 5: System Status
// ============================================================================

async function exampleSystemStatus(): Promise<void> {
  console.log('\n=== Example 5: System Status ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    const status = await client.status();
    console.log('Daemon Status:');
    console.log(`  Uptime: ${status.uptime}s`);
    console.log(`  Models loaded: ${status.modelsLoaded}`);
    console.log(`  Total requests: ${status.totalRequests}`);
    console.log(`  Network available: ${status.networkAvailable}`);
    if (status.activeSessions !== undefined) {
      console.log(`  Active sessions: ${status.activeSessions}`);
    }
    if (status.rateLimits) {
      console.log('  Rate limits:');
      for (const rl of status.rateLimits) {
        console.log(`    ${rl.category}: ${rl.remaining}/${rl.limit} (resets in ${rl.resetSeconds}s)`);
      }
    }

    // Health check
    const health = await client.health();
    console.log(`\nHealth: ${health.ok ? 'OK' : 'FAIL'}`);
    if (health.uptime !== undefined) {
      console.log(`Daemon uptime: ${health.uptime}s`);
    }
  } catch (err) {
    console.error('Status error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 6: Context Store
// ============================================================================

async function exampleContextStore(): Promise<void> {
  console.log('\n=== Example 6: Context Store ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    const sessionId = 'example-session';
    const key = 'user-preferences';
    const value = JSON.stringify({ theme: 'dark', language: 'en' });

    // Store
    await client.contextStore(sessionId, key, value);
    console.log(`Stored context: ${key}`);

    // Retrieve
    const retrieved = await client.contextRetrieve(sessionId, key);
    if (retrieved) {
      console.log(`Retrieved: ${retrieved.toString('utf-8')}`);
    } else {
      console.log('Key not found');
    }

    // Retrieve non-existent
    const missing = await client.contextRetrieve(sessionId, 'nonexistent-key');
    console.log(`Non-existent key: ${missing === null ? 'null (correct)' : 'unexpected'}`);
  } catch (err) {
    console.error('Context store error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 7: Batch Inference
// ============================================================================

async function exampleBatchInference(): Promise<void> {
  console.log('\n=== Example 7: Batch Inference ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    const prompts = [
      'What is the capital of France?',
      'What is 2 + 2?',
      'Who wrote Romeo and Juliet?',
    ];

    const requests = prompts.map((prompt) => ({
      prompt,
      maxTokens: 50,
    }));

    const responses = await client.batchInfer(requests);
    console.log(`Processed ${responses.length} requests:`);
    for (let i = 0; i < responses.length; i++) {
      console.log(`  [${i}] ${prompts[i]}`);
      console.log(`      -> ${responses[i].output.slice(0, 100)}...`);
    }
  } catch (err) {
    console.error('Batch inference error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 8: Rate Limit Status
// ============================================================================

async function exampleRateLimitStatus(): Promise<void> {
  console.log('\n=== Example 8: Rate Limit Status ===');

  const client = new AinosClient({
    host: HOST,
    port: PORT,
    authToken: AUTH_TOKEN,
  });

  try {
    await client.connect();

    const rateLimit = await client.rateLimitStatus();
    console.log('Rate limit status:');
    for (const limit of rateLimit.limits) {
      console.log(`  ${limit.category}: ${limit.remaining}/${limit.limit} remaining (resets in ${limit.resetSeconds}s)`);
    }
  } catch (err) {
    console.error('Rate limit error:', err);
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 9: Error Handling
// ============================================================================

async function exampleErrorHandling(): Promise<void> {
  console.log('\n=== Example 9: Error Handling ===');

  // Try connecting to a non-existent daemon
  const client = new AinosClient({
    host: '127.0.0.1',
    port: 19999, // Wrong port
    connectTimeout: 2000,
    autoReconnect: false,
  });

  try {
    await client.connect();
    console.log('Connected (unexpected)');
  } catch (err) {
    if (err instanceof ConnectionError) {
      console.log('Caught ConnectionError:', err.message);
    } else if (err instanceof TimeoutError) {
      console.log('Caught TimeoutError:', err.message);
    } else {
      console.log('Caught error:', err);
    }
  } finally {
    client.disconnect();
  }
}

// ============================================================================
// Example 10: Factory Function
// ============================================================================

async function exampleFactoryFunction(): Promise<void> {
  console.log('\n=== Example 10: Factory Function ===');

  try {
    const client = await createClient({
      host: HOST,
      port: PORT,
      authToken: AUTH_TOKEN,
      connectTimeout: 5000,
    });

    console.log('Client created and connected via factory');

    const response = await client.infer({
      prompt: 'Hello!',
      maxTokens: 100,
    });

    console.log('Response:', response.output);
    client.disconnect();
  } catch (err) {
    console.error('Factory error:', err);
  }
}

// ============================================================================
// Main
// ============================================================================

async function main(): Promise<void> {
  console.log('Ainos SDK Examples');
  console.log(`Target: ${HOST}:${PORT}`);
  console.log(`Auth: ${AUTH_TOKEN ? 'configured' : 'not configured'}`);
  console.log('='.repeat(50));

  const examples = [
    exampleBasicInference,
    exampleStreamingInference,
    exampleAccumulateStream,
    exampleModelManagement,
    exampleSystemStatus,
    exampleContextStore,
    exampleBatchInference,
    exampleRateLimitStatus,
    exampleErrorHandling,
    exampleFactoryFunction,
  ];

  // Determine which examples to run
  const specificExample = process.argv[2];
  if (specificExample) {
    const idx = parseInt(specificExample, 10);
    if (idx >= 1 && idx <= examples.length) {
      await examples[idx - 1]();
    } else {
      console.error(`Example ${idx} not found. Choose 1-${examples.length}.`);
    }
  } else {
    // Run all examples (skip error handling to avoid confusion)
    for (let i = 0; i < examples.length; i++) {
      try {
        await examples[i]();
      } catch (err) {
        console.error(`Example ${i + 1} failed:`, err);
      }
    }
  }

  console.log('\nDone.');
}

main().catch(console.error);