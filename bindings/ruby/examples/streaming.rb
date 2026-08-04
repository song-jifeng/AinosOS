# frozen_string_literal: true

# Streaming inference example for the Ainos Ruby SDK.
#
# Run with:
#   bundle exec ruby examples/streaming.rb
#
# Make sure the Ainos daemon is running on 127.0.0.1:9500
# and the AINOS_TOKEN environment variable is set.

$LOAD_PATH.unshift(File.expand_path('../lib', __dir__))

require 'ainos'
require 'logger'

# Configure logging
logger = Logger.new($stdout)
logger.level = Logger::WARN

# Create a client
client = Ainos::Client.new do |config|
  config.host = ENV.fetch('AINOS_HOST', '127.0.0.1')
  config.port = ENV.fetch('AINOS_PORT', 9500).to_i
  config.token = ENV['AINOS_TOKEN']
  config.logger = logger
  config.connection_timeout = 5.0
  config.read_timeout = 120.0
end

begin
  client.connect
  puts "Connected to Ainos daemon at #{client.config.host}:#{client.config.port}"

  # Find a loaded model
  models = client.model_list
  loaded_models = models.select(&:loaded?)

  if loaded_models.empty?
    puts 'No loaded models found. Please load a model first.'
    puts "Available models: #{models.map(&:name).join(', ')}"
    exit 1
  end

  model_name = loaded_models.first.name
  puts "Using model: #{model_name}"

  # ============================================================
  # Example 1: Basic streaming with block
  # ============================================================
  puts
  puts '=' * 60
  puts 'Example 1: Basic streaming with block'
  puts '=' * 60
  puts

  print 'Response: '

  client.infer_stream(
    model: model_name,
    prompt: 'Write a haiku about Ruby programming.',
    temperature: 0.8,
    max_tokens: 128
  ) do |chunk|
    print chunk.text
    $stdout.flush
  end

  puts
  puts

  # ============================================================
  # Example 2: Enumerator-based streaming
  # ============================================================
  puts '=' * 60
  puts 'Example 2: Enumerator-based streaming'
  puts '=' * 60
  puts

  chunks = client.infer_stream(
    model: model_name,
    prompt: 'Count from 1 to 5, one number per line.',
    temperature: 0.1,
    max_tokens: 64
  )

  chunks.each_with_index do |chunk, index|
    puts "[Chunk #{index}] #{chunk.text.inspect}"
  end

  puts

  # ============================================================
  # Example 3: StreamSession with collect
  # ============================================================
  puts '=' * 60
  puts 'Example 3: StreamSession with collect'
  puts '=' * 60
  puts

  request = Ainos::InferenceRequest.new(
    model: model_name,
    prompt: 'Explain the difference between arrays and hashes in Ruby.',
    temperature: 0.7,
    max_tokens: 256
  )

  session = Ainos::StreamSession.new(client, request)
  session.each_chunk do |chunk|
    print chunk.text
    $stdout.flush
  end

  puts
  puts

  response = session.collect
  puts "Collected response: #{response.text.length} characters"
  puts "Tokens: #{response.tokens}"
  puts "Finish reason: #{response.finish_reason}"
  puts "Chunks received: #{session.chunk_count}"
  puts

  # ============================================================
  # Example 4: StreamBuilder fluent interface
  # ============================================================
  puts '=' * 60
  puts 'Example 4: StreamBuilder fluent interface'
  puts '=' * 60
  puts

  builder = Ainos::StreamBuilder.new(client)
  builder.model(model_name)
         .prompt('What are three tips for writing clean Ruby code?')
         .temperature(0.7)
         .max_tokens(256)
         .on_chunk { |chunk| print chunk.text; $stdout.flush }
         .on_finish { |text| puts "\n\n[Complete: #{text.length} chars]" }
         .on_error { |error| puts "\n[Error: #{error.message}]" }
         .start

  puts

  # ============================================================
  # Example 5: StreamAccumulator
  # ============================================================
  puts '=' * 60
  puts 'Example 5: StreamAccumulator'
  puts '=' * 60
  puts

  accumulator = Ainos::StreamAccumulator.new
  accumulator.on_chunk { |chunk| print chunk.text; $stdout.flush }
  accumulator.on_finish { |full_text| puts "\n\n[Accumulated: #{full_text.length} chars]" }

  client.infer_stream(
    model: model_name,
    prompt: 'Write a short greeting in three different languages.',
    temperature: 0.8,
    max_tokens: 128
  ) do |chunk|
    accumulator << chunk
  end

  puts
  puts "Chunks processed: #{accumulator.chunk_count}"
  puts "Elapsed time: #{accumulator.elapsed_time&.round(3)}s"
  puts "Tokens/sec: #{accumulator.tokens_per_second&.round(1)}"
  puts

  # ============================================================
  # Example 6: StreamUtils
  # ============================================================
  puts '=' * 60
  puts 'Example 6: StreamUtils with timing'
  puts '=' * 60
  puts

  client.infer_stream(
    model: model_name,
    prompt: 'What is the meaning of life?',
    temperature: 0.9,
    max_tokens: 64
  ) do |chunk|
    Ainos::StreamUtils.with_timing([chunk]) do |c, delta|
      puts "[+#{format('%.3f', delta)}s] #{c.text}"
    end
  end

  puts

  # ============================================================
  # Example 7: Multiple concurrent streams
  # ============================================================
  puts '=' * 60
  puts 'Example 7: Sequential streams (concurrent requires threads)'
  puts '=' * 60
  puts

  prompts = [
    'Say "Hello" in French.',
    'Say "Hello" in German.',
    'Say "Hello" in Spanish.'
  ]

  prompts.each_with_index do |prompt, i|
    print "Stream #{i + 1}: "

    client.infer_stream(
      model: model_name,
      prompt: prompt,
      temperature: 0.5,
      max_tokens: 32
    ) do |chunk|
      print chunk.text
      $stdout.flush
    end

    puts
  end

rescue Ainos::ConnectionError => e
  puts "Connection error: #{e.message}"
  puts 'Make sure the Ainos daemon is running.'
rescue Ainos::Error => e
  puts "Ainos error: #{e.detailed_message}"
rescue StandardError => e
  puts "Unexpected error: #{e.class}: #{e.message}"
  puts e.backtrace.first(3).join("\n")
ensure
  client&.disconnect
  puts
  puts 'Disconnected.'
end