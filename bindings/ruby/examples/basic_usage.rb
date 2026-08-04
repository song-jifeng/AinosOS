# frozen_string_literal: true

# Basic usage example for the Ainos Ruby SDK.
#
# Run with:
#   bundle exec ruby examples/basic_usage.rb
#
# Make sure the Ainos daemon is running on 127.0.0.1:9500
# and the AINOS_TOKEN environment variable is set.

$LOAD_PATH.unshift(File.expand_path('../lib', __dir__))

require 'ainos'
require 'logger'

# Configure logging
logger = Logger.new($stdout)
logger.level = Logger::INFO

# Example 1: Basic client with configuration block
puts '=' * 60
puts 'Example 1: Basic client setup'
puts '=' * 60

client = Ainos::Client.new do |config|
  config.host = ENV.fetch('AINOS_HOST', '127.0.0.1')
  config.port = ENV.fetch('AINOS_PORT', 9500).to_i
  config.token = ENV['AINOS_TOKEN']
  config.logger = logger
  config.connection_timeout = 5.0
  config.read_timeout = 30.0
  config.auto_reconnect = true
end

begin
  # Connect to the daemon
  puts 'Connecting to Ainos daemon...'
  client.connect
  puts "Connected: #{client.connected?}"

  # Example 2: Health check
  puts
  puts '=' * 60
  puts 'Example 2: Health check'
  puts '=' * 60

  health = client.health
  puts "Server healthy: #{health.healthy?}"
  puts "Status: #{health.status}"
  puts "Version: #{health.version}" if health.version
  puts "Uptime: #{health.uptime}s" if health.uptime

  # Example 3: Server status
  puts
  puts '=' * 60
  puts 'Example 3: Server status'
  puts '=' * 60

  status = client.status
  puts status.to_s
  puts "Memory: #{status.memory.inspect}" unless status.memory.empty?
  puts "CPU: #{status.cpu.inspect}" unless status.cpu.empty?

  # Example 4: List models
  puts
  puts '=' * 60
  puts 'Example 4: Available models'
  puts '=' * 60

  models = client.model_list
  if models.empty?
    puts 'No models available.'
  else
    models.each do |model|
      puts "  - #{model.name} (v#{model.version || 'N/A'})"
      puts "    Status: #{model.status}"
      puts "    Size: #{model.size_human}"
      puts "    Capabilities: #{model.capabilities.join(', ')}" unless model.capabilities.empty?
      puts "    Context length: #{model.context_length}" if model.context_length
    end
  end

  # Example 5: Basic inference
  puts
  puts '=' * 60
  puts 'Example 5: Basic inference'
  puts '=' * 60

  if models.any? { |m| m.loaded? }
    model_name = models.find(&:loaded?).name
    puts "Using model: #{model_name}"

    response = client.infer(
      model: model_name,
      prompt: 'What is the Ruby programming language?',
      system_prompt: 'You are a helpful programming expert.',
      temperature: 0.7,
      max_tokens: 256
    )

    puts
    puts 'Response:'
    puts response.text
    puts
    puts "Stats:"
    puts "  Tokens: #{response.tokens}"
    puts "  Finish reason: #{response.finish_reason}"
    puts "  Model: #{response.model}"
    puts "  Request ID: #{response.request_id}"
  else
    puts 'No loaded models available. Try loading one first.'
    puts 'Example: client.model_load("llama3")'
  end

  # Example 6: Context management
  puts
  puts '=' * 60
  puts 'Example 6: Context management'
  puts '=' * 60

  context_id = 'example-conversation'
  context = client.context_store(context_id, {
    messages: [
      { role: 'user', content: 'Hello!' }
    ],
    metadata: { example: true }
  }, ttl: 3600)

  puts "Context stored: #{context.id}"
  puts "Created at: #{context.created_at}"

  retrieved = client.context_retrieve(context_id)
  if retrieved
    puts "Context retrieved: #{retrieved.id}"
    puts "Data: #{retrieved.data.inspect}"
    puts "Expired: #{retrieved.expired?}"
  end

  # Example 7: Ping
  puts
  puts '=' * 60
  puts 'Example 7: Ping'
  puts '=' * 60

  if client.ping
    puts 'Server responded to ping!'
  else
    puts 'Ping failed.'
  end

  # Example 8: Connection statistics
  puts
  puts '=' * 60
  puts 'Example 8: Connection statistics'
  puts '=' * 60

  stats = client.stats
  puts "Connected: #{stats[:connected]}"
  puts "Request count: #{stats[:request_count]}"
  puts "Connection age: #{stats[:connection_age]&.round(2)}s"

  transport_stats = stats[:transport_stats]
  puts "Messages sent: #{transport_stats[:messages_sent]}"
  puts "Messages received: #{transport_stats[:messages_received]}"
  puts "Bytes sent: #{transport_stats[:bytes_sent]}"
  puts "Bytes received: #{transport_stats[:bytes_received]}"

rescue Ainos::ConnectionError => e
  puts "Connection error: #{e.message}"
  puts 'Make sure the Ainos daemon is running.'
rescue Ainos::AuthError => e
  puts "Authentication error: #{e.message}"
  puts 'Make sure AINOS_TOKEN is set correctly.'
rescue Ainos::Error => e
  puts "Ainos error: #{e.detailed_message}"
rescue StandardError => e
  puts "Unexpected error: #{e.class}: #{e.message}"
  puts e.backtrace.first(5).join("\n")
ensure
  # Always disconnect
  client.disconnect if client&.connected?
  puts
  puts 'Disconnected.'
end