# Ainos Ruby SDK

A comprehensive Ruby SDK for interacting with the **Ainos inference daemon** over the NDJSON-over-TCP protocol. Supports model inference, streaming responses, model management, server health monitoring, and context management.

## Requirements

- Ruby 3.0 or higher
- Ainos daemon running on port 9500 (default)

## Installation

### Using Bundler

Add this to your `Gemfile`:

```ruby
gem 'ainos-sdk'
```

Then:

```bash
$ bundle install
```

### Manual Installation

```bash
$ gem install ainos-sdk
```

## Quick Start

```ruby
require 'ainos'

# Create a client
client = Ainos::Client.new(token: ENV['AINOS_TOKEN'])
client.connect

# Basic inference
response = client.infer(
  model: 'llama3',
  prompt: 'What is the capital of France?',
  temperature: 0.7,
  max_tokens: 256
)
puts response.text
# => "The capital of France is Paris."

# Clean up
client.disconnect
```

## Configuration

```ruby
# Using a configuration block
client = Ainos::Client.new do |config|
  config.host = '192.168.1.100'
  config.port = 9500
  config.token = ENV['AINOS_API_TOKEN']
  config.connection_timeout = 10.0
  config.read_timeout = 60.0
  config.auto_reconnect = true
  config.max_reconnect_attempts = 5
  config.logger = Logger.new($stdout)
end

client.connect
```

## API Reference

### Client

| Method | Description |
|--------|-------------|
| `connect` | Connect to the Ainos daemon |
| `disconnect` | Disconnect from the daemon |
| `connected?` | Check if connected |
| `infer` | Perform inference |
| `infer_stream` | Perform streaming inference |
| `model_list` | List available models |
| `model_load` | Load a model |
| `model_unload` | Unload a model |
| `health` | Check daemon health |
| `status` | Get detailed server status |
| `context_store` | Store conversation context |
| `context_retrieve` | Retrieve conversation context |
| `ping` | Check connectivity |
| `wait_for_model` | Wait for a model to be ready |
| `stats` | Get connection statistics |

### Basic Inference

```ruby
# With keyword arguments
response = client.infer(
  model: 'llama3',
  prompt: 'Explain quantum computing in simple terms.',
  system_prompt: 'You are a helpful physics teacher.',
  temperature: 0.8,
  max_tokens: 1024,
  top_p: 0.95,
  stop_sequences: ['\n\n'],
  context_id: 'conv-123'
)

puts response.text
puts "Tokens: #{response.tokens}"
puts "Finish reason: #{response.finish_reason}"
puts "Model: #{response.model}"

# With a request object
request = Ainos::InferenceRequest.new(
  model: 'llama3',
  prompt: 'Hello!',
  temperature: 0.7
)
response = client.infer(request)
```

### Streaming Inference

```ruby
# Block-based (recommended)
client.infer_stream(model: 'llama3', prompt: 'Write a poem about AI.') do |chunk|
  print chunk.text
  # Process each chunk as it arrives
end
puts # Newline after stream ends

# Enumerator-based (lazy)
chunks = client.infer_stream(model: 'llama3', prompt: 'Tell me a story.')
chunks.each_with_index do |chunk, i|
  puts "[#{i}] #{chunk.text}"
end

# Using StreamSession
session = Ainos::StreamSession.new(client, request)
session.each_chunk { |chunk| print chunk.text }
response = session.collect
puts response.text

# Using StreamBuilder
builder = Ainos::StreamBuilder.new(client)
builder.model('llama3')
       .prompt('Hello!')
       .temperature(0.8)
       .on_chunk { |chunk| print chunk.text }
       .on_finish { |text| puts "\nComplete! (#{text.length} chars)" }
       .start
```

### Model Management

```ruby
# List all models
models = client.model_list
models.each do |model|
  puts "#{model.name} - #{model.status} (#{model.size_human})"
end

# Load a model
model = client.model_load('llama3', gpu_layers: 32, context_size: 4096)
puts "#{model.name} loaded: #{model.loaded?}"

# Check if a model is loaded
if client.model_loaded?('llama3')
  puts "Model is ready!"
end

# Wait for a model to be ready
client.wait_for_model('llama3', timeout: 120)

# Unload a model
client.model_unload('llama3')
```

### Health and Status

```ruby
# Health check
health = client.health
puts "Server healthy: #{health.healthy?}"
puts "Version: #{health.version}"

# Server status
status = client.status
puts status.to_s
# => "Server v1.2.3 | Uptime: 2d 14h 30m | Models: 3/5 loaded | Requests: 1234 | Avg latency: 45.2ms"
```

### Context Management

```ruby
# Store conversation context
context = client.context_store('conv-123', {
  messages: [
    { role: 'user', content: 'Hello!' },
    { role: 'assistant', content: 'Hi there!' }
  ],
  metadata: { user_id: 42 }
}, ttl: 3600)

# Retrieve context
context = client.context_retrieve('conv-123')
puts context.data.inspect
puts "Expired: #{context.expired?}"
```

### Authentication

```ruby
# From environment variable
client = Ainos::Client.new(token: ENV['AINOS_TOKEN'])

# Using Auth class
auth = Ainos::Auth.new('my-token')
client = Ainos::Client.new(token: auth.token)

# From file
auth = Ainos::Auth.from_file('/etc/ainos/token')

# Token rotation
provider = Ainos::TokenProvider.new
provider.add_token('primary', 'token-1')
provider.add_token('backup', 'token-2')
provider.switch_to('backup')
```

## Error Handling

```ruby
begin
  response = client.infer(model: 'llama3', prompt: 'Hello!')
rescue Ainos::ConnectionError => e
  puts "Cannot connect: #{e.message}"
rescue Ainos::ModelNotFoundError => e
  puts "Model not found: #{e.model_name}"
rescue Ainos::InferenceError => e
  puts "Inference failed: #{e.message}"
rescue Ainos::TimeoutError => e
  puts "Request timed out: #{e.operation}"
rescue Ainos::AuthError => e
  puts "Authentication failed: #{e.reason}"
rescue Ainos::Error => e
  puts "Ainos error: #{e.detailed_message}"
end
```

## Streaming Utilities

```ruby
require 'ainos'

client = Ainos::Client.new(token: ENV['AINOS_TOKEN'])
client.connect

# Using StreamUtils to process streams
stream = client.infer_stream(model: 'llama3', prompt: 'Long text...')

# Sliding window processing
Ainos::StreamUtils.sliding_window(stream, window_size: 50) do |window|
  print window
  sleep(0.01) # Simulate processing time
end

# Filter chunks
stream = client.infer_stream(model: 'llama3', prompt: 'Text...')
filtered = Ainos::StreamUtils.filter(stream) { |chunk| chunk.text.length > 0 }
filtered.each { |chunk| print chunk.text }

# Map chunks
stream = client.infer_stream(model: 'llama3', prompt: 'Text...')
uppercased = Ainos::StreamUtils.map(stream, &:text)
uppercased.each { |text| print text.upcase }

# Timing
Ainos::StreamUtils.with_timing(stream) do |chunk, delta|
  puts "[+#{format('%.3f', delta)}s] #{chunk.text}"
end

client.disconnect
```

## Development

### Setup

```bash
$ git clone https://github.com/ainos/ainos-sdk-ruby.git
$ cd ainos-sdk-ruby
$ bundle install
```

### Running Tests

```bash
$ bundle exec rspec
$ bundle exec rspec spec/test_transport.rb
```

### Generating Documentation

```bash
$ bundle exec yard doc
$ open doc/index.html
```

### Linting

```bash
$ bundle exec rubocop
```

## Architecture

The SDK is organized into the following layers:

```
lib/ainos/
├── ainos.rb        # Entry point, top-level convenience methods
├── version.rb      # Version constants
├── errors.rb       # Error hierarchy
├── types.rb        # Data classes (requests, responses, models)
├── auth.rb         # Bearer token authentication
├── transport.rb    # TCP transport with NDJSON framing
├── streaming.rb    # Streaming inference support
└── client.rb       # Main client class
```

The transport layer uses a thread-safe design with a dedicated reader thread that processes incoming NDJSON messages and dispatches them to the appropriate pending request or stream queue.

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -am 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License. See `LICENSE.txt` for details.