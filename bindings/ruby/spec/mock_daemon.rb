# frozen_string_literal: true

require 'socket'
require 'json'
require 'thread'

# A mock Ainos daemon for testing purposes.
#
# Listens on a TCP socket and responds to NDJSON requests with
# configurable responses. Supports testing of normal operations,
# error conditions, and streaming scenarios.
#
# @example
#   daemon = MockDaemon.new
#   daemon.start
#   port = daemon.port
#   # ... run tests against localhost:#{port}
#   daemon.stop
class MockDaemon
  # @return [Integer] the port the daemon is listening on
  attr_reader :port

  # @return [String] the host the daemon is listening on
  attr_reader :host

  # @return [Array<String>] log of received requests
  attr_reader :request_log

  # @return [Boolean] whether the daemon is running
  attr_reader :running

  # Create a new mock daemon.
  #
  # @param host [String] the host to bind to
  # @param port [Integer] the port to bind to (0 for auto-assign)
  # @param auth_token [String, nil] expected auth token
  def initialize(host: '127.0.0.1', port: 0, auth_token: nil)
    @host = host
    @port = port
    @auth_token = auth_token
    @server = nil
    @running = false
    @server_thread = nil
    @request_log = []
    @response_handlers = {}
    @default_handler = nil
    @mutex = Mutex.new
    @client_threads = []
    @delay = 0.0 # Artificial delay for all responses
    @should_fail = false
    @fail_after = nil
    @connection_count = 0
    @stream_scenario = nil
  end

  # Start the mock daemon.
  #
  # @return [self]
  def start
    @mutex.synchronize do
      return self if @running

      @server = TCPServer.new(@host, @port)
      @port = @server.addr[1]
      @running = true
      @connection_count = 0
      @request_log.clear

      @server_thread = Thread.new { accept_connections }
      @server_thread.abort_on_exception = false

      # Wait for the server to be ready
      sleep(0.01) until @server_thread.alive? && @server&.closed? == false
    end

    self
  end

  # Stop the mock daemon.
  #
  # @return [self]
  def stop
    @mutex.synchronize do
      @running = false
      @server&.close
      @server = nil

      @client_threads.each(&:kill)
      @client_threads.clear
    end

    self
  end

  # Register a handler for a specific request type.
  #
  # @param type [String] the request type
  # @yield [request_hash, client_socket] handler
  def on_request(type, &block)
    @response_handlers[type.to_s] = block
  end

  # Set the default handler for unhandled request types.
  #
  # @yield [request_hash, client_socket] handler
  def on_default(&block)
    @default_handler = block
  end

  # Set an artificial delay before responding.
  #
  # @param seconds [Float] the delay in seconds
  def delay=(seconds)
    @delay = seconds.to_f
  end

  # Configure the daemon to fail after a certain number of requests.
  #
  # @param count [Integer, nil] fail after this many requests (nil = never)
  # @param error [String] the error message to return
  def fail_after(count, error: 'Internal server error')
    @fail_after = count
    @fail_error = error
  end

  # Configure a streaming scenario.
  #
  # @param chunks [Array<String>] the text chunks to stream
  # @param finish_reason [String] the finish reason
  def stream_scenario(chunks, finish_reason: 'stop')
    @stream_scenario = {
      chunks: chunks,
      finish_reason: finish_reason
    }
  end

  # Get the number of active connections.
  #
  # @return [Integer] connection count
  def connection_count
    @mutex.synchronize { @connection_count }
  end

  # Wait for a specific number of requests to be received.
  #
  # @param count [Integer] the number of requests to wait for
  # @param timeout [Float] the timeout in seconds
  # @return [Boolean] true if the count was reached
  def wait_for_requests(count, timeout: 5.0)
    start = Time.now
    while @request_log.length < count
      break if Time.now - start >= timeout
      sleep(0.01)
    end
    @request_log.length >= count
  end

  private

  # Accept incoming connections.
  def accept_connections
    loop do
      begin
        client = @server.accept
        @mutex.synchronize { @connection_count += 1 }
        thread = Thread.new(client) { |c| handle_client(c) }
        @client_threads << thread
        @client_threads.reject!(&:alive?)
      rescue IOError
        break unless @running
      rescue StandardError => e
        break unless @running
      end
    end
  end

  # Handle a client connection.
  #
  # @param client [TCPSocket] the client socket
  def handle_client(client)
    log_request = +''

    loop do
      begin
        line = client.gets
        break if line.nil?

        line = line.chomp
        next if line.empty?

        request = JSON.parse(line)
        log_request = line

        @mutex.synchronize do
          @request_log << request.dup
        end

        # Check if we should fail
        if @fail_after && @request_log.length >= @fail_after
          send_error(client, request, @fail_error || 'Simulated failure')
          break
        end

        # Apply artificial delay
        sleep(@delay) if @delay > 0

        # Find and invoke handler
        handler = @response_handlers[request['type']] || @default_handler

        if handler
          handler.call(request, client)
        else
          send_default_response(client, request)
        end
      rescue JSON::ParserError
        send_raw(client, JSON.generate({
          type: 'error', id: 'parse-error', ok: false,
          payload: {}, error: 'Invalid JSON'
        }) + "\n")
      rescue IOError
        break
      rescue StandardError => e
        send_raw(client, JSON.generate({
          type: 'error', id: 'unknown', ok: false,
          payload: {}, error: e.message
        }) + "\n")
        break
      end
    end
  rescue IOError
    # Client disconnected
  ensure
    client.close rescue nil
    @mutex.synchronize { @connection_count -= 1 }
  end

  # Send a default response for a request type.
  #
  # @param client [TCPSocket] the client
  # @param request [Hash] the request
  def send_default_response(client, request)
    case request['type']
    when 'health'
      send_response(client, request, {
        status: 'ok', healthy: true, version: '1.0.0',
        uptime: 3600, active_connections: 1, loaded_models: 2
      })
    when 'status'
      send_response(client, request, {
        version: '1.0.0', started_at: Time.now.iso8601,
        active_connections: 1, total_requests: 100,
        avg_latency_ms: 45.2, loaded_models: 2, total_models: 5,
        memory: { used: '4.2GB', total: '16GB' },
        cpu: { usage: 12.5 }
      })
    when 'ping'
      send_response(client, request, { pong: true })
    when 'model_list'
      send_response(client, request, {
        models: [
          { name: 'llama3', status: 'loaded', version: '1.0',
            size_bytes: 4_700_000_000, capabilities: %w[chat completion] },
          { name: 'mistral', status: 'loaded', version: '2.0',
            size_bytes: 3_200_000_000, capabilities: %w[chat completion code] },
          { name: 'codellama', status: 'unloaded', version: '1.5',
            size_bytes: 5_100_000_000, capabilities: %w[code completion] }
        ]
      })
    when 'model_load'
      send_response(client, request, {
        name: request.dig('payload', 'model') || 'unknown',
        status: 'loaded', loaded_at: Time.now.iso8601
      })
    when 'model_unload'
      send_response(client, request, { unloaded: true })
    when 'infer'
      if request.dig('payload', 'stream')
        send_stream_response(client, request)
      else
        send_response(client, request, {
          text: "This is a mock response to: #{request.dig('payload', 'prompt')}",
          tokens: 42, finish_reason: 'stop',
          model: request.dig('payload', 'model'),
          usage: { prompt_tokens: 10, completion_tokens: 42, total_tokens: 52 },
          timing: { generation_ms: 150 }
        })
      end
    when 'context_store'
      send_response(client, request, {
        created_at: Time.now.iso8601,
        updated_at: Time.now.iso8601,
        token_count: 0
      })
    when 'context_retrieve'
      send_response(client, request, {
        data: { stored: true, original: 'data' },
        created_at: Time.now.iso8601
      })
    when 'auth_check'
      check_auth(client, request)
    else
      send_response(client, request, {})
    end
  end

  # Send a streaming response.
  #
  # @param client [TCPSocket] the client
  # @param request [Hash] the request
  def send_stream_response(client, request)
    if @stream_scenario
      chunks = @stream_scenario[:chunks]
      finish_reason = @stream_scenario[:finish_reason]
    else
      chunks = ['Hello', ', ', 'world', '!']
      finish_reason = 'stop'
    end

    chunks.each_with_index do |text, index|
      stream_chunk = {
        type: 'stream',
        id: request['id'],
        payload: {
          text: text,
          index: index,
          finished: false
        },
        ok: true
      }
      send_raw(client, JSON.generate(stream_chunk) + "\n")
      sleep(0.001) # Small delay to simulate streaming
    end

    # Send end marker
    end_chunk = {
      type: 'stream_end',
      id: request['id'],
      payload: {
        text: '',
        tokens: chunks.join.length / 4,
        finished: true,
        finish_reason: finish_reason
      },
      ok: true
    }
    send_raw(client, JSON.generate(end_chunk) + "\n")
  end

  # Check authentication.
  #
  # @param client [TCPSocket] the client
  # @param request [Hash] the request
  def check_auth(client, request)
    auth = request['auth']
    if @auth_token && auth != "Bearer #{@auth_token}"
      send_raw(client, JSON.generate({
        type: 'auth_result', id: request['id'], ok: false,
        payload: {}, error: 'Invalid token'
      }) + "\n")
    else
      send_response(client, request, { authenticated: true })
    end
  end

  # Send a success response.
  #
  # @param client [TCPSocket] the client
  # @param request [Hash] the request
  # @param payload [Hash] the response payload
  def send_response(client, request, payload)
    response = {
      type: 'result',
      id: request['id'],
      payload: payload,
      ok: true
    }
    send_raw(client, JSON.generate(response) + "\n")
  end

  # Send an error response.
  #
  # @param client [TCPSocket] the client
  # @param request [Hash] the request
  # @param error [String] the error message
  # @param code [String] the error code
  def send_error(client, request, error, code: 'error')
    response = {
      type: 'result',
      id: request['id'],
      payload: { error_code: code },
      ok: false,
      error: error
    }
    send_raw(client, JSON.generate(response) + "\n")
  end

  # Send raw data to the client.
  #
  # @param client [TCPSocket] the client
  # @param data [String] the raw data
  def send_raw(client, data)
    client.write(data)
    client.flush
  end
end

# RSpec shared context for mock daemon tests.
RSpec.shared_context 'with mock daemon' do
  let(:mock_daemon) { MockDaemon.new }
  let(:client) do
    Ainos::Client.new(
      host: '127.0.0.1',
      port: mock_daemon.port,
      token: 'test-token',
      auto_reconnect: false,
      connection_timeout: 2.0,
      read_timeout: 5.0
    )
  end

  before(:each) do
    mock_daemon.start
    client.connect
  end

  after(:each) do
    client.disconnect rescue nil
    mock_daemon.stop rescue nil
  end
end