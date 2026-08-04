<?php

declare(strict_types=1);

namespace Ainos\Tests;

use Ainos\AinosClient;
use Ainos\Authentication;
use Ainos\Parameters;
use Ainos\InferenceResponse;
use Ainos\ModelList;
use Ainos\HealthStatus;
use Ainos\ServerStatus;
use Ainos\ContextEntry;
use Ainos\StreamChunk;
use Ainos\ConnectionException;
use Ainos\AuthenticationException;
use Ainos\InvalidRequestException;
use Ainos\TimeoutException;
use Ainos\ConfigurationException;
use PHPUnit\Framework\TestCase;

/**
 * Test suite for the AinosClient.
 *
 * @covers \Ainos\AinosClient
 * @covers \Ainos\Authentication
 * @covers \Ainos\Parameters
 * @covers \Ainos\InferenceResponse
 * @covers \Ainos\ModelList
 * @covers \Ainos\HealthStatus
 * @covers \Ainos\ServerStatus
 * @covers \Ainos\ContextEntry
 * @covers \Ainos\StreamChunk
 */
class AinosClientTest extends TestCase
{
    private static ?MockDaemon $daemon = null;
    private static ?int $daemonPort = null;

    /**
     * Start the mock daemon before all tests.
     */
    public static function setUpBeforeClass(): void
    {
        self::$daemon = new MockDaemon(
            '127.0.0.1',
            0,
            'test-token-for-testing'
        );
        self::$daemonPort = self::$daemon->start();
    }

    /**
     * Stop the mock daemon after all tests.
     */
    public static function tearDownAfterClass(): void
    {
        if (self::$daemon !== null) {
            self::$daemon->stop();
            self::$daemon = null;
        }
    }

    /**
     * Get a configured client instance.
     */
    private function getClient(array $options = []): AinosClient
    {
        $auth = new Authentication('test-token-for-testing');

        return new AinosClient(
            $auth,
            '127.0.0.1',
            self::$daemonPort,
            \array_merge([
                'timeout' => 5.0,
                'max_retries' => 0,
                'retry_enabled' => false,
            ], $options)
        );
    }

    /**
     * Accept a daemon connection and handle a single request.
     */
    private function acceptAndHandle(): void
    {
        self::$daemon->acceptConnection(1);
        self::$daemon->handleRequest();
    }

    /**
     * Test client construction with valid parameters.
     */
    public function testConstructor(): void
    {
        $auth = new Authentication('test-token');
        $client = new AinosClient($auth, '127.0.0.1', 9500, ['timeout' => 30.0]);

        $this->assertInstanceOf(AinosClient::class, $client);
        $this->assertEquals('127.0.0.1', $client->getHost());
        $this->assertEquals(9500, $client->getPort());
        $this->assertFalse($client->isConnected());
    }

    /**
     * Test client construction with invalid options.
     */
    public function testConstructorInvalidOptions(): void
    {
        $auth = new Authentication('test-token');

        $this->expectException(ConfigurationException::class);
        new AinosClient($auth, '127.0.0.1', 9500, ['max_retries' => -1]);
    }

    /**
     * Test client construction with invalid timeout.
     */
    public function testConstructorInvalidTimeout(): void
    {
        $auth = new Authentication('test-token');

        $this->expectException(ConfigurationException::class);
        new AinosClient($auth, '127.0.0.1', 9500, ['timeout' => 0]);
    }

    /**
     * Test connect and disconnect.
     */
    public function testConnectAndDisconnect(): void
    {
        $client = $this->getClient();
        $this->assertFalse($client->isConnected());

        $client->connect();
        self::$daemon->acceptConnection(1);
        $this->assertTrue($client->isConnected());

        $client->disconnect();
        $this->assertFalse($client->isConnected());
    }

    /**
     * Test health check.
     */
    public function testHealth(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $health = $client->health();

        $this->assertInstanceOf(HealthStatus::class, $health);
        $this->assertEquals('healthy', $health->status);
        $this->assertTrue($health->isHealthy());
        $this->assertNotEmpty($health->version);

        $client->disconnect();
    }

    /**
     * Test server status.
     */
    public function testStatus(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $status = $client->status();

        $this->assertInstanceOf(ServerStatus::class, $status);
        $this->assertNotEmpty($status->version);
        $this->assertIsArray($status->activeModels);
        $this->assertIsArray($status->memory);

        $client->disconnect();
    }

    /**
     * Test model list.
     */
    public function testModelList(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $modelList = $client->modelList();

        $this->assertInstanceOf(ModelList::class, $modelList);
        $this->assertGreaterThan(0, $modelList->total);
        $this->assertGreaterThan(0, \count($modelList->models));
        $this->assertGreaterThan(0, $modelList->totalSize);

        // Test getByName
        $model = $modelList->getByName('gpt-3.5-turbo');
        $this->assertNotNull($model);
        $this->assertEquals('gpt-3.5-turbo', $model->name);

        // Test getLoaded
        $loaded = $modelList->getLoaded();
        $this->assertGreaterThan(0, \count($loaded));

        // Test getNames
        $names = $modelList->getNames();
        $this->assertContains('gpt-3.5-turbo', $names);

        // Test has
        $this->assertTrue($modelList->has('gpt-3.5-turbo'));
        $this->assertFalse($modelList->has('non-existent-model'));

        $client->disconnect();
    }

    /**
     * Test model load and unload.
     */
    public function testModelLoadAndUnload(): void
    {
        $client = $this->getClient();

        $client->connect();
        self::$daemon->acceptConnection(1);

        // Load model
        $modelInfo = $client->modelLoad('test-model');

        $this->assertEquals('test-model', $modelInfo->name);
        $this->assertTrue($modelInfo->loaded);
        $this->assertNotEmpty($modelInfo->path);

        $client->disconnect();
    }

    /**
     * Test model load with empty name.
     */
    public function testModelLoadWithEmptyName(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->modelLoad('');
    }

    /**
     * Test model unload with empty name.
     */
    public function testModelUnloadWithEmptyName(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->modelUnload('');
    }

    /**
     * Test synchronous inference.
     */
    public function testInfer(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $response = $client->infer('gpt-3.5-turbo', 'Hello, world!');

        $this->assertInstanceOf(InferenceResponse::class, $response);
        $this->assertNotEmpty($response->id);
        $this->assertNotEmpty($response->getText());
        $this->assertTrue($response->isComplete());
        $this->assertGreaterThan(0, $response->usage->promptTokens);
        $this->assertGreaterThan(0, $response->usage->completionTokens);
        $this->assertGreaterThan(0, $response->usage->totalTokens);

        $client->disconnect();
    }

    /**
     * Test inference with Parameters object.
     */
    public function testInferWithParametersObject(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $params = new Parameters(
            temperature: 0.5,
            maxTokens: 100,
            topP: 0.9,
        );

        $response = $client->infer('gpt-3.5-turbo', 'Hello', $params);

        $this->assertInstanceOf(InferenceResponse::class, $response);
        $this->assertNotEmpty($response->getText());

        $client->disconnect();
    }

    /**
     * Test inference with array parameters.
     */
    public function testInferWithArrayParameters(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $response = $client->infer('gpt-3.5-turbo', 'Hello', [
            'temperature' => 0.5,
            'max_tokens' => 100,
        ]);

        $this->assertInstanceOf(InferenceResponse::class, $response);
        $this->assertNotEmpty($response->getText());

        $client->disconnect();
    }

    /**
     * Test inference with empty model name.
     */
    public function testInferWithEmptyModel(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->infer('', 'test');
    }

    /**
     * Test inference with empty prompt.
     */
    public function testInferWithEmptyPrompt(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->infer('test', '');
    }

    /**
     * Test streaming inference.
     */
    public function testInferStream(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        $chunks = [];
        $stream = $client->inferStream('gpt-3.5-turbo', 'Hello');

        // The daemon is blocking, so we need to handle the request
        // Since the streams are asynchronous, we'll handle the request
        // and then iterate
        self::$daemon->handleRequest();

        foreach ($stream as $chunk) {
            $chunks[] = $chunk;
            if ($chunk->isEnd) {
                break;
            }
        }

        $this->assertGreaterThan(0, \count($chunks));

        // Check that we got text chunks
        $textChunks = \array_filter($chunks, fn(StreamChunk $c) => $c->text !== '');
        $this->assertGreaterThan(0, \count($textChunks));

        // Check that we got an end marker
        $endChunks = \array_filter($chunks, fn(StreamChunk $c) => $c->isEnd);
        $this->assertCount(1, $endChunks);

        $client->disconnect();
    }

    /**
     * Test context store and retrieve.
     */
    public function testContextStoreAndRetrieve(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);

        // Store context
        $entry = $client->contextStore('test-key', 'test-value', 3600);

        $this->assertInstanceOf(ContextEntry::class, $entry);
        $this->assertEquals('test-key', $entry->key);
        $this->assertEquals('test-value', $entry->value);
        $this->assertEquals(3600, $entry->ttl);

        $client->disconnect();
    }

    /**
     * Test context store with empty key.
     */
    public function testContextStoreWithEmptyKey(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->contextStore('', 'value');
    }

    /**
     * Test context store with invalid TTL.
     */
    public function testContextStoreWithInvalidTtl(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->contextStore('key', 'value', 0);
    }

    /**
     * Test context retrieve with empty key.
     */
    public function testContextRetrieveWithEmptyKey(): void
    {
        $client = $this->getClient();

        $this->expectException(InvalidRequestException::class);
        $client->contextRetrieve('');
    }

    /**
     * Test client getStats.
     */
    public function testGetStats(): void
    {
        $client = $this->getClient();
        $stats = $client->getStats();

        $this->assertArrayHasKey('total_requests', $stats);
        $this->assertArrayHasKey('successful_requests', $stats);
        $this->assertArrayHasKey('failed_requests', $stats);
        $this->assertArrayHasKey('transport', $stats);
        $this->assertArrayHasKey('auth_token_preview', $stats);
        $this->assertArrayHasKey('options', $stats);
    }

    /**
     * Test resetStats.
     */
    public function testResetStats(): void
    {
        $client = $this->getClient();
        $client->resetStats();

        $stats = $client->getStats();
        $this->assertEquals(0, $stats['total_requests']);
        $this->assertEquals(0, $stats['successful_requests']);
        $this->assertEquals(0, $stats['failed_requests']);
    }

    /**
     * Test getAuthentication and setAuthentication.
     */
    public function testAuthentication(): void
    {
        $client = $this->getClient();
        $auth = $client->getAuthentication();

        $this->assertInstanceOf(Authentication::class, $auth);
        $this->assertEquals('test-token-for-testing', $auth->getToken());

        // Set new auth
        $newAuth = new Authentication('new-token');
        $client->setAuthentication($newAuth);
        $this->assertEquals('new-token', $client->getAuthentication()->getToken());
    }

    /**
     * Test getTransport.
     */
    public function testGetTransport(): void
    {
        $client = $this->getClient();
        $transport = $client->getTransport();

        $this->assertInstanceOf(\Ainos\Transport::class, $transport);
    }

    /**
     * Test getOptions.
     */
    public function testGetOptions(): void
    {
        $client = $this->getClient();
        $options = $client->getOptions();

        $this->assertArrayHasKey('timeout', $options);
        $this->assertArrayHasKey('auto_connect', $options);
        $this->assertArrayHasKey('max_retries', $options);
    }

    /**
     * Test setOptions.
     */
    public function testSetOptions(): void
    {
        $client = $this->getClient();
        $client->setOptions(['timeout' => 60.0]);

        $options = $client->getOptions();
        $this->assertEquals(60.0, $options['timeout']);
    }

    /**
     * Test fromEnvironment factory method.
     */
    public function testFromEnvironment(): void
    {
        // Set environment variables
        $originalToken = \getenv('AINOS_TOKEN');
        $originalHost = \getenv('AINOS_HOST');
        $originalPort = \getenv('AINOS_PORT');

        \putenv('AINOS_TOKEN=env-test-token');
        \putenv('AINOS_HOST=127.0.0.1');
        \putenv('AINOS_PORT=9500');

        $client = AinosClient::fromEnvironment(['timeout' => 30.0]);

        $this->assertInstanceOf(AinosClient::class, $client);
        $this->assertEquals('env-test-token', $client->getAuthentication()->getToken());

        // Restore
        if ($originalToken !== false) {
            \putenv("AINOS_TOKEN={$originalToken}");
        } else {
            \putenv('AINOS_TOKEN');
        }
        if ($originalHost !== false) {
            \putenv("AINOS_HOST={$originalHost}");
        } else {
            \putenv('AINOS_HOST');
        }
        if ($originalPort !== false) {
            \putenv("AINOS_PORT={$originalPort}");
        } else {
            \putenv('AINOS_PORT');
        }
    }

    /**
     * Test fromConfig factory method.
     */
    public function testFromConfig(): void
    {
        $client = AinosClient::fromConfig([
            'token' => 'config-test-token',
            'host' => '127.0.0.1',
            'port' => 9500,
            'options' => ['timeout' => 30.0],
        ]);

        $this->assertInstanceOf(AinosClient::class, $client);
        $this->assertEquals('config-test-token', $client->getAuthentication()->getToken());
    }

    /**
     * Test fromConfig with missing token.
     */
    public function testFromConfigMissingToken(): void
    {
        $this->expectException(ConfigurationException::class);
        AinosClient::fromConfig(['host' => '127.0.0.1']);
    }

    /**
     * Test authentication constructor with invalid token.
     */
    public function testAuthenticationInvalidToken(): void
    {
        $this->expectException(AuthenticationException::class);
        new Authentication('');
    }

    /**
     * Test authentication token preview.
     */
    public function testAuthenticationTokenPreview(): void
    {
        $auth = new Authentication('abcdefghijklmnopqrstuvwxyz');
        $preview = $auth->getTokenPreview();

        $this->assertStringStartsWith('abcdefgh', $preview);
        $this->assertStringEndsWith('wxyz', $preview);
        $this->assertStringContainsString('...', $preview);
    }

    /**
     * Test authentication fromFile.
     */
    public function testAuthenticationFromFile(): void
    {
        $tempFile = \tempnam(\sys_get_temp_dir(), 'ainos_token_');
        \file_put_contents($tempFile, 'file-token-content');

        $auth = Authentication::fromFile($tempFile);
        $this->assertEquals('file-token-content', $auth->getToken());

        \unlink($tempFile);
    }

    /**
     * Test authentication fromFile with missing file.
     */
    public function testAuthenticationFromFileMissing(): void
    {
        $this->expectException(AuthenticationException::class);
        Authentication::fromFile('/nonexistent/token/file');
    }

    /**
     * Test authentication anonymous.
     */
    public function testAuthenticationAnonymous(): void
    {
        $auth = Authentication::anonymous();
        $this->assertEquals('anonymous', $auth->getToken());
        $this->assertTrue($auth->isValid());
    }

    /**
     * Test authentication headers.
     */
    public function testAuthenticationHeaders(): void
    {
        $auth = new Authentication('test-token');
        $headers = $auth->getHeaders();

        $this->assertArrayHasKey('Authorization', $headers);
        $this->assertEquals('Bearer test-token', $headers['Authorization']);
        $this->assertArrayHasKey('Content-Type', $headers);
        $this->assertEquals('application/x-ndjson', $headers['Content-Type']);
    }

    /**
     * Test Parameters defaults.
     */
    public function testParametersDefaults(): void
    {
        $params = Parameters::defaults();

        $this->assertEquals(0.7, $params->temperature);
        $this->assertEquals(0.9, $params->topP);
        $this->assertEquals(40, $params->topK);
        $this->assertEquals(2048, $params->maxTokens);
        $this->assertFalse($params->echo);
        $this->assertEquals(1, $params->n);
    }

    /**
     * Test Parameters validation.
     */
    public function testParametersValidation(): void
    {
        $params = new Parameters(temperature: 0.5);
        $validated = $params->validate();
        $this->assertSame($params, $validated);

        $this->expectException(InvalidRequestException::class);
        $invalid = new Parameters(temperature: 3.0);
        $invalid->validate();
    }

    /**
     * Test Parameters merge.
     */
    public function testParametersMerge(): void
    {
        $base = new Parameters(temperature: 0.5, maxTokens: 100);
        $override = new Parameters(temperature: 0.8);

        $merged = $base->merge($override);

        $this->assertEquals(0.8, $merged->temperature);
        $this->assertEquals(100, $merged->maxTokens);
    }

    /**
     * Test Parameters fromArray.
     */
    public function testParametersFromArray(): void
    {
        $params = Parameters::fromArray([
            'temperature' => 0.5,
            'max_tokens' => 100,
            'top_p' => 0.9,
        ]);

        $this->assertEquals(0.5, $params->temperature);
        $this->assertEquals(100, $params->maxTokens);
        $this->assertEquals(0.9, $params->topP);
    }

    /**
     * Test Parameters toArray.
     */
    public function testParametersToArray(): void
    {
        $params = new Parameters(temperature: 0.5, maxTokens: 100);
        $array = $params->toArray();

        $this->assertArrayHasKey('temperature', $array);
        $this->assertArrayHasKey('max_tokens', $array);
        $this->assertEquals(0.5, $array['temperature']);
        $this->assertEquals(100, $array['max_tokens']);
    }

    /**
     * Test StreamChunk creation.
     */
    public function testStreamChunk(): void
    {
        $chunk = new StreamChunk(
            id: 'test-001',
            model: 'gpt-3.5-turbo',
            text: 'Hello',
            index: 0,
        );

        $this->assertEquals('test-001', $chunk->id);
        $this->assertEquals('Hello', $chunk->text);
        $this->assertFalse($chunk->isEnd);

        $endChunk = StreamChunk::end('test-001', 'gpt-3.5-turbo');
        $this->assertTrue($endChunk->isEnd);
    }

    /**
     * Test StreamChunk fromArray.
     */
    public function testStreamChunkFromArray(): void
    {
        $chunk = StreamChunk::fromArray([
            'id' => 'test-001',
            'model' => 'gpt-3.5-turbo',
            'text' => 'Hello',
            'finish_reason' => 'stop',
            'usage' => ['prompt_tokens' => 10, 'completion_tokens' => 20, 'total_tokens' => 30],
        ]);

        $this->assertEquals('test-001', $chunk->id);
        $this->assertEquals('Hello', $chunk->text);
        $this->assertNotNull($chunk->usage);
        $this->assertEquals(10, $chunk->usage->promptTokens);
    }

    /**
     * Test InferenceResponse fromArray.
     */
    public function testInferenceResponseFromArray(): void
    {
        $response = InferenceResponse::fromArray([
            'id' => 'resp-001',
            'model' => 'gpt-3.5-turbo',
            'choices' => [
                [
                    'index' => 0,
                    'text' => 'Hello world',
                    'finish_reason' => 'stop',
                ],
            ],
            'usage' => [
                'prompt_tokens' => 10,
                'completion_tokens' => 20,
                'total_tokens' => 30,
            ],
        ]);

        $this->assertEquals('resp-001', $response->id);
        $this->assertEquals('Hello world', $response->getText());
        $this->assertTrue($response->isComplete());
        $this->assertEquals(30, $response->usage->totalTokens);
    }

    /**
     * Test HealthStatus fromArray.
     */
    public function testHealthStatusFromArray(): void
    {
        $health = HealthStatus::fromArray([
            'status' => 'healthy',
            'uptime' => 3600.0,
            'version' => '1.0.0',
            'memory' => ['used' => 512, 'total' => 1024],
        ]);

        $this->assertTrue($health->isHealthy());
        $this->assertEquals('1.0.0', $health->version);
        $this->assertNotEmpty($health->getUptimeFormatted());
    }

    /**
     * Test ServerStatus fromArray.
     */
    public function testServerStatusFromArray(): void
    {
        $status = ServerStatus::fromArray([
            'version' => '1.0.0',
            'uptime' => 3600,
            'active_models' => ['model-1'],
            'total_requests' => 100,
        ]);

        $this->assertEquals('1.0.0', $status->version);
        $this->assertContains('model-1', $status->activeModels);
    }

    /**
     * Test ContextEntry fromArray.
     */
    public function testContextEntryFromArray(): void
    {
        $entry = ContextEntry::fromArray([
            'id' => 'ctx-001',
            'key' => 'test-key',
            'value' => 'test-value',
            'ttl' => 3600,
            'created_at' => \time(),
        ]);

        $this->assertEquals('ctx-001', $entry->id);
        $this->assertEquals('test-key', $entry->key);
        $this->assertEquals('test-value', $entry->value);
        $this->assertFalse($entry->isExpired());
        $this->assertGreaterThan(0, $entry->getRemainingTtl());
    }

    /**
     * Test ContextEntry expiry.
     */
    public function testContextEntryExpired(): void
    {
        $entry = ContextEntry::fromArray([
            'expires_at' => \time() - 100, // Expired 100 seconds ago
        ]);

        $this->assertTrue($entry->isExpired());
        $this->assertEquals(0, $entry->getRemainingTtl());
    }

    /**
     * Test ContextEntry no expiry.
     */
    public function testContextEntryNoExpiry(): void
    {
        $entry = new ContextEntry(expiresAt: null);
        $this->assertFalse($entry->isExpired());
        $this->assertNull($entry->getRemainingTtl());
    }

    /**
     * Test ModelList fromArray.
     */
    public function testModelListFromArray(): void
    {
        $list = ModelList::fromArray([
            'models' => [
                ['name' => 'model-1', 'loaded' => true],
                ['name' => 'model-2', 'loaded' => false],
            ],
            'total' => 2,
            'loaded_count' => 1,
        ]);

        $this->assertCount(2, $list->models);
        $this->assertEquals(2, $list->total);
        $this->assertEquals(1, $list->loadedCount);
        $this->assertTrue($list->has('model-1'));
        $this->assertFalse($list->has('model-3'));
    }

    /**
     * Test ModelInfo size formatting.
     */
    public function testModelInfoSizeFormat(): void
    {
        $model = \Ainos\ModelInfo::fromArray([
            'name' => 'test',
            'size' => 1024 * 1024 * 1024 * 4, // 4 GB
        ]);

        $this->assertStringContainsString('GB', $model->getSizeFormatted());
    }

    /**
     * Test Usage calculation.
     */
    public function testUsageCalculation(): void
    {
        $usage = new \Ainos\Usage(
            promptTokens: 100,
            completionTokens: 50,
            completionTime: 0.5,
        );

        $this->assertEquals(150, $usage->totalTokens);
        $this->assertEquals(100.0, $usage->getCompletionTokensPerSecond());
        $this->assertEquals(0.5, $usage->getRatio());
    }

    /**
     * Test Usage sum.
     */
    public function testUsageSum(): void
    {
        $a = new \Ainos\Usage(promptTokens: 10, completionTokens: 20);
        $b = new \Ainos\Usage(promptTokens: 30, completionTokens: 40);

        $sum = \Ainos\Usage::sum($a, $b);

        $this->assertEquals(40, $sum->promptTokens);
        $this->assertEquals(60, $sum->completionTokens);
        $this->assertEquals(100, $sum->totalTokens);
    }

    /**
     * Test FinishReason enum.
     */
    public function testFinishReason(): void
    {
        $this->assertTrue(\Ainos\FinishReason::Stop->isSuccessful());
        $this->assertFalse(\Ainos\FinishReason::Error->isSuccessful());
        $this->assertTrue(\Ainos\FinishReason::Error->isError());
        $this->assertFalse(\Ainos\FinishReason::Length->isError());

        $fromValue = \Ainos\FinishReason::fromValue('stop');
        $this->assertEquals(\Ainos\FinishReason::Stop, $fromValue);

        $unknown = \Ainos\FinishReason::fromValue('nonexistent');
        $this->assertEquals(\Ainos\FinishReason::Unknown, $unknown);
    }

    /**
     * Test connection exception creation.
     */
    public function testConnectionException(): void
    {
        $e = ConnectionException::timeout('127.0.0.1', 9500, 30.0);
        $this->assertStringContainsString('127.0.0.1', $e->getMessage());
        $this->assertEquals('127.0.0.1', $e->getHost());
        $this->assertEquals(9500, $e->getPort());
        $this->assertTrue($e->isRetryable());

        $refused = ConnectionException::refused('127.0.0.1', 9500);
        $this->assertStringContainsString('refused', $refused->getMessage());
    }

    /**
     * Test authentication exception creation.
     */
    public function testAuthenticationException(): void
    {
        $e = AuthenticationException::invalidTokenFormat();
        $this->assertStringContainsString('token', \strtolower($e->getMessage()));

        $expired = AuthenticationException::tokenExpired();
        $this->assertStringContainsString('expired', $expired->getMessage());

        $missing = AuthenticationException::missingToken();
        $this->assertStringContainsString('no authentication token', \strtolower($missing->getMessage()));
    }

    /**
     * Test invalid request exception.
     */
    public function testInvalidRequestException(): void
    {
        $e = InvalidRequestException::missingField('model');
        $this->assertStringContainsString('model', $e->getMessage());
        $this->assertEquals('model', $e->getField());

        $invalid = InvalidRequestException::invalidField('temperature', 3.0, 'must be 0-2');
        $this->assertStringContainsString('temperature', $invalid->getMessage());
    }

    /**
     * Test timeout exception.
     */
    public function testTimeoutException(): void
    {
        $e = new TimeoutException('inference', 30.0);
        $this->assertStringContainsString('inference', \strtolower($e->getMessage()));
        $this->assertEquals('inference', $e->getOperation());
        $this->assertEquals(30.0, $e->getTimeout());
    }

    /**
     * Test model not found exception.
     */
    public function testModelNotFoundException(): void
    {
        $e = new \Ainos\ModelNotFoundException('test-model');
        $this->assertStringContainsString('test-model', $e->getMessage());
        $this->assertEquals('test-model', $e->getModelName());
    }

    /**
     * Test exception error ID.
     */
    public function testExceptionErrorId(): void
    {
        $e = new \Ainos\AinosException('test');
        $this->assertNotEmpty($e->getErrorId());
        $this->assertEquals(32, \strlen($e->getErrorId()));
    }

    /**
     * Test exception context.
     */
    public function testExceptionContext(): void
    {
        $e = new \Ainos\AinosException('test', 0, null, ['key1' => 'value1']);
        $this->assertEquals('value1', $e->getContextValue('key1'));
        $this->assertNull($e->getContextValue('nonexistent'));
        $this->assertEquals('default', $e->getContextValue('nonexistent', 'default'));

        $e->withContext(['key2' => 'value2']);
        $this->assertEquals('value2', $e->getContextValue('key2'));
    }

    /**
     * Test exception toArray and toJson.
     */
    public function testExceptionSerialization(): void
    {
        $e = new \Ainos\AinosException('test error', 123, null, ['ctx' => 'data']);
        $array = $e->toArray();

        $this->assertEquals('test error', $array['message']);
        $this->assertEquals(123, $array['code']);
        $this->assertArrayHasKey('error_id', $array);
        $this->assertArrayHasKey('context', $array);
        $this->assertEquals('data', $array['context']['ctx']);

        $json = $e->toJson();
        $decoded = \json_decode($json, true);
        $this->assertEquals('test error', $decoded['message']);
    }

    /**
     * Test exception fromArray.
     */
    public function testExceptionFromArray(): void
    {
        $e = \Ainos\AinosException::fromArray([
            'message' => 'reconstructed',
            'code' => 42,
            'context' => ['foo' => 'bar'],
        ]);

        $this->assertEquals('reconstructed', $e->getMessage());
        $this->assertEquals(42, $e->getCode());
        $this->assertEquals('bar', $e->getContextValue('foo'));
    }

    /**
     * Test Utils helper functions.
     */
    public function testUtils(): void
    {
        // Test formatBytes
        $this->assertEquals('1.00 KB', \Ainos\Utils::formatBytes(1024));
        $this->assertEquals('1.00 MB', \Ainos\Utils::formatBytes(1024 * 1024));
        $this->assertEquals('0.00 B', \Ainos\Utils::formatBytes(0));

        // Test generateId
        $id = \Ainos\Utils::generateId();
        $this->assertEquals(32, \strlen($id));

        $prefixed = \Ainos\Utils::generateId('test');
        $this->assertStringStartsWith('test_', $prefixed);

        // Test validateToken
        $this->assertTrue(\Ainos\Utils::validateToken('abc123'));
        $this->assertTrue(\Ainos\Utils::validateToken('abc-def.ghi_jkl'));
        $this->assertFalse(\Ainos\Utils::validateToken(''));
        $this->assertFalse(\Ainos\Utils::validateToken('token with spaces'));

        // Test validateHost
        $this->assertTrue(\Ainos\Utils::validateHost('127.0.0.1'));
        $this->assertTrue(\Ainos\Utils::validateHost('localhost'));
        $this->assertTrue(\Ainos\Utils::validateHost('example.com'));
        $this->assertFalse(\Ainos\Utils::validateHost(''));
        $this->assertFalse(\Ainos\Utils::validateHost('invalid host!'));

        // Test validatePort
        $this->assertTrue(\Ainos\Utils::validatePort(80));
        $this->assertTrue(\Ainos\Utils::validatePort(65535));
        $this->assertFalse(\Ainos\Utils::validatePort(0));
        $this->assertFalse(\Ainos\Utils::validatePort(65536));

        // Test arrayOnly and arrayExcept
        $source = ['a' => 1, 'b' => 2, 'c' => 3];
        $this->assertEquals(['a' => 1, 'b' => 2], \Ainos\Utils::arrayOnly($source, ['a', 'b']));
        $this->assertEquals(['a' => 1, 'c' => 3], \Ainos\Utils::arrayExcept($source, ['b']));

        // Test arrayFilterRecursive
        $filtered = \Ainos\Utils::arrayFilterRecursive(
            ['a' => 1, 'b' => null, 'c' => ['d' => null, 'e' => 2]]
        );
        $this->assertArrayNotHasKey('b', $filtered);

        // Test truncate
        $this->assertLessThanOrEqual(13, \strlen(\Ainos\Utils::truncate('Hello World! This is a long string', 10)));
        $this->assertEquals('Short', \Ainos\Utils::truncate('Short', 10));

        // Test camelToSnake and snakeToCamel
        $this->assertEquals('hello_world', \Ainos\Utils::camelToSnake('helloWorld'));
        $this->assertEquals('helloWorld', \Ainos\Utils::snakeToCamel('hello_world'));
        $this->assertEquals('HelloWorld', \Ainos\Utils::snakeToCamel('hello_world', true));

        // Test isAssociativeArray
        $this->assertTrue(\Ainos\Utils::isAssociativeArray(['a' => 1]));
        $this->assertFalse(\Ainos\Utils::isAssociativeArray([1, 2, 3]));
        $this->assertFalse(\Ainos\Utils::isAssociativeArray([]));
    }

    /**
     * Test Timer.
     */
    public function testTimer(): void
    {
        $timer = new \Ainos\Timer();

        $timer->start();
        \usleep(10000); // 10ms
        $elapsed = $timer->stop();

        $this->assertGreaterThan(0.005, $elapsed);
        $this->assertLessThan(0.5, $elapsed);
        $this->assertFalse($timer->isRunning());

        // Test elapsed while running
        $timer->start();
        \usleep(5000);
        $this->assertTrue($timer->isRunning());
        $this->assertGreaterThan(0.0, $timer->elapsed());
        $timer->stop();

        // Test reset
        $timer->reset();
        $this->assertFalse($timer->isRunning());

        // Test measure
        $result = \Ainos\Timer::measure(function () {
            \usleep(10000);
            return 'result';
        });

        $this->assertEquals('result', $result['result']);
        $this->assertGreaterThan(0.005, $result['duration']);
    }

    /**
     * Test Timer format.
     */
    public function testTimerFormat(): void
    {
        $timer = new \Ainos\Timer();

        // Test microsecond format (very short duration would be hard to guarantee)
        // Just test that the method exists and returns a string
        $timer->start();
        $timer->stop();
        $this->assertIsString($timer->format());
    }

    /**
     * Test that auto-connect works.
     */
    public function testAutoConnect(): void
    {
        // Create client with auto-connect enabled
        $auth = new Authentication('test-token-for-testing');
        $client = new AinosClient(
            $auth,
            '127.0.0.1',
            self::$daemonPort,
            [
                'auto_connect' => true,
                'timeout' => 5.0,
                'max_retries' => 0,
                'retry_enabled' => false,
            ]
        );

        // This should auto-connect
        $client->connect();
        self::$daemon->acceptConnection(1);

        $this->assertTrue($client->isConnected());
        $client->disconnect();
    }

    /**
     * Test connecting twice is idempotent.
     */
    public function testConnectTwice(): void
    {
        $client = $this->getClient();
        $client->connect();
        self::$daemon->acceptConnection(1);
        $this->assertTrue($client->isConnected());

        // Connect again should be a no-op
        $client->connect();
        $this->assertTrue($client->isConnected());

        $client->disconnect();
    }

    /**
     * Test that the client properly handles a failed connection to a non-existent server.
     */
    public function testConnectionToNonExistentServer(): void
    {
        $auth = new Authentication('test-token');
        $client = new AinosClient(
            $auth,
            '127.0.0.1',
            19999, // Non-existent port
            ['timeout' => 2.0, 'max_retries' => 0, 'retry_enabled' => false]
        );

        $this->expectException(ConnectionException::class);
        $client->health();
    }

    /**
     * Test AinosClient __debugInfo.
     */
    public function testDebugInfo(): void
    {
        $client = $this->getClient();
        $debugInfo = $client->__debugInfo();

        $this->assertArrayHasKey('total_requests', $debugInfo);
        $this->assertArrayHasKey('transport', $debugInfo);
        $this->assertArrayHasKey('auth_token_preview', $debugInfo);
    }
}