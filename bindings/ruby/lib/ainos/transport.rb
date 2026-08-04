# frozen_string_literal: true

require 'socket'
require 'json'
require 'securerandom'
require 'monitor'

module Ainos
  # TCP transport layer for communicating with the Ainos daemon.
  #
  # Handles NDJSON (Newline-Delimited JSON) protocol over TCP sockets.
  # Provides thread-safe message sending and receiving, automatic
  # reconnection, and comprehensive error handling.
  #
  # @example
  #   transport = Ainos::Transport.new('127.0.0.1', 9500)
  #   transport.connect
  #   response = transport.send_request(type: 'infer', payload: { ... })
  #   transport.disconnect
  class Transport
    # @return [String] the daemon host
    attr_reader :host

    # @return [Integer] the daemon port
    attr_reader :port

    # @return [Boolean] whether the transport is connected
    attr_reader :connected

    # @return [Hash] connection statistics
    attr_reader :stats

    # @return [Integer, nil] the socket file descriptor
    attr_reader :socket_fd

    # Create a new transport instance.
    #
    # @param host [String] the daemon hostname or IP
    # @param port [Integer] the daemon port
    # @param config [Configuration, Hash] configuration options
    def initialize(host, port, config = {})
      @host = host
      @port = port.to_i
      @config = config.is_a?(Configuration) ? config : Configuration.new(**config)

      @socket = nil
      @connected = false
      @running = false

      # Thread safety
      @mutex = Monitor.new
      @write_mutex = Monitor.new
      @read_mutex = Monitor.new

      # Pending request tracking
      @pending_requests = {}
      @pending_mutex = Monitor.new

      # Stream tracking
      @stream_queues = {}
      @stream_mutex = Monitor.new

      # Reader thread
      @reader_thread = nil

      # Statistics
      @stats = {
        started_at: nil,
        messages_sent: 0,
        messages_received: 0,
        bytes_sent: 0,
        bytes_received: 0,
        reconnections: 0,
        errors: 0,
        last_activity: nil
      }

      @logger = @config.logger
      @read_buffer = +''
      @partial_line = +''
    end

    # Connect to the Ainos daemon.
    #
    # @param timeout [Float, nil] connection timeout in seconds
    #
    # @return [Boolean] true if connected successfully
    #
    # @raise [Ainos::ConnectionError] if connection fails
    # @raise [Ainos::ConnectionTimeoutError] if connection times out
    #
    # @example
    #   transport.connect(timeout: 5.0)
    def connect(timeout: nil)
      timeout ||= @config.connection_timeout

      @mutex.synchronize do
        return true if @connected

        log_info("Connecting to #{@host}:#{@port} (timeout: #{timeout}s)")

        begin
          socket = create_socket(timeout)

          @socket = socket
          @connected = true
          @running = true
          @stats[:started_at] = Time.now
          @stats[:last_activity] = Time.now

          # Start the reader thread
          start_reader_thread

          log_info("Connected to #{@host}:#{@port}")

          true
        rescue Errno::ECONNREFUSED => e
          @connected = false
          raise ConnectionError.new(
            "Connection refused by #{@host}:#{@port}",
            host: @host, port: @port, cause: e
          )
        rescue Errno::ETIMEDOUT => e
          @connected = false
          raise ConnectionTimeoutError.new(
            timeout: timeout, host: @host, port: @port
          )
        rescue Errno::EADDRNOTAVAIL => e
          @connected = false
          raise ConnectionError.new(
            "Address not available: #{@host}:#{@port}",
            host: @host, port: @port, cause: e
          )
        rescue Errno::ENETUNREACH => e
          @connected = false
          raise ConnectionError.new(
            "Network unreachable: #{@host}:#{@port}",
            host: @host, port: @port, cause: e
          )
        rescue SocketError => e
          @connected = false
          raise ConnectionError.new(
            "Socket error connecting to #{@host}:#{@port}: #{e.message}",
            host: @host, port: @port, cause: e
          )
        end
      end
    end

    # Disconnect from the Ainos daemon.
    #
    # @return [Boolean] true if disconnected successfully
    #
    # @example
    #   transport.disconnect
    def disconnect
      @mutex.synchronize do
        was_connected = @connected
        @running = false
        @connected = false

        # Stop the reader thread
        if @reader_thread&.alive?
          @reader_thread.kill
          @reader_thread = nil
        end

        # Close the socket
        if @socket
          begin
            @socket.close
          rescue IOError
            # Socket already closed
          end
          @socket = nil
        end

        # Clean up pending requests
        @pending_mutex.synchronize do
          @pending_requests.each_value do |queue|
            queue.push(nil) # Signal termination
          end
          @pending_requests.clear
        end

        # Clean up stream queues
        @stream_mutex.synchronize do
          @stream_queues.each_value do |queue|
            queue.push(nil) # Signal termination
          end
          @stream_queues.clear
        end

        if was_connected
          log_info("Disconnected from #{@host}:#{@port}")
        end

        true
      end
    end

    # Check if the transport is connected.
    #
    # @return [Boolean] true if connected
    def connected?
      @connected && @socket && !@socket.closed?
    end

    # Send a request and wait for the response.
    #
    # @param type [String] the request type
    # @param payload [Hash] the request payload
    # @param auth [String, nil] auth token
    # @param request_id [String, nil] request ID (auto-generated if nil)
    # @param timeout [Float, nil] response timeout
    #
    # @return [ServerResponse] the server response
    #
    # @raise [Ainos::NotConnectedError] if not connected
    # @raise [Ainos::TimeoutError] if the request times out
    # @raise [Ainos::WriteError] if writing fails
    # @raise [Ainos::ReadError] if reading fails
    def send_request(type:, payload:, auth: nil, request_id: nil, timeout: nil)
      ensure_connected!

      request_id ||= SecureRandom.uuid
      timeout ||= @config.read_timeout

      request = ServerRequest.new(
        type: type.to_s,
        payload: payload,
        id: request_id,
        auth: auth
      )

      response_queue = Queue.new

      @pending_mutex.synchronize do
        @pending_requests[request_id] = response_queue
      end

      begin
        write_message(request.to_json)

        response = wait_for_response(response_queue, request_id, timeout)

        if response.nil?
          raise TimeoutError.new(
            timeout: timeout,
            operation: "request #{type} (#{request_id})"
          )
        end

        response
      rescue TimeoutError
        raise
      rescue StandardError => e
        @stats[:errors] += 1
        raise WriteError.new("Failed to send request: #{e.message}", cause: e)
      ensure
        @pending_mutex.synchronize do
          @pending_requests.delete(request_id)
        end
      end
    end

    # Send a request and return a stream of responses.
    #
    # @param type [String] the request type
    # @param payload [Hash] the request payload
    # @param auth [String, nil] auth token
    # @param request_id [String, nil] request ID
    #
    # @yield [StreamChunk] yields each stream chunk if a block is given
    #
    # @return [Enumerator<StreamChunk>] an enumerator of stream chunks
    #
    # @raise [Ainos::NotConnectedError] if not connected
    # @raise [Ainos::WriteError] if writing fails
    def send_stream_request(type:, payload:, auth: nil, request_id: nil, &block)
      ensure_connected!

      request_id ||= SecureRandom.uuid
      stream_queue = Queue.new

      @stream_mutex.synchronize do
        @stream_queues[request_id] = stream_queue
      end

      request = ServerRequest.new(
        type: type.to_s,
        payload: payload.merge(stream: true),
        id: request_id,
        auth: auth
      )

      write_message(request.to_json)

      # Create an enumerator for the stream
      stream_enum = Enumerator.new do |yielder|
        loop do
          chunk = stream_queue.pop
          break if chunk.nil? # Stream ended

          yielder << chunk

          break if chunk.final?
        end
      end.lazy

      if block
        stream_enum.each(&block)
      else
        stream_enum
      end
    ensure
      unless block
        @stream_mutex.synchronize do
          @stream_queues.delete(request_id)
        end
      end
    end

    # Reconnect to the daemon.
    #
    # @param timeout [Float, nil] connection timeout
    #
    # @return [Boolean] true if reconnected successfully
    #
    # @raise [Ainos::MaxReconnectError] if max reconnection attempts exceeded
    def reconnect(timeout: nil)
      attempts = 0
      max_attempts = @config.max_reconnect_attempts
      delay = @config.reconnect_delay

      begin
        disconnect if connected?
        attempts += 1
        connect(timeout: timeout)
        @stats[:reconnections] += 1
        log_info("Reconnected to #{@host}:#{@port} (attempt #{attempts})")
        true
      rescue ConnectionError, ConnectionTimeoutError => e
        if attempts < max_attempts
          log_warn("Reconnection attempt #{attempts}/#{max_attempts} failed: #{e.message}")
          sleep(delay * attempts) # Exponential backoff
          retry
        else
          raise MaxReconnectError.new(
            attempts: attempts,
            host: @host,
            port: @port,
            cause: e
          )
        end
      end
    end

    # Send a raw message without waiting for a response.
    #
    # @param message [String] the JSON message to send
    #
    # @return [Integer] the number of bytes sent
    #
    # @api private
    def send_raw(message)
      ensure_connected!
      write_message(message)
    end

    # Check if the connection appears healthy.
    #
    # @return [Boolean] true if the connection is healthy
    def healthy?
      return false unless connected?

      # Check if the socket is readable/writable
      begin
        socket = @socket
        return false if socket.nil?

        # Use IO.select to check if the socket is still alive
        _, write_err = IO.select(nil, nil, [socket], 0)
        return false if write_err&.any?

        true
      rescue IOError
        false
      end
    end

    # Reset connection statistics.
    def reset_stats!
      @mutex.synchronize do
        @stats = {
          started_at: @stats[:started_at],
          messages_sent: 0,
          messages_received: 0,
          bytes_sent: 0,
          bytes_received: 0,
          reconnections: @stats[:reconnections],
          errors: 0,
          last_activity: nil
        }
      end
    end

    # Get the connection age in seconds.
    #
    # @return [Float, nil] seconds since connection
    def connection_age
      return nil unless @stats[:started_at]

      Time.now - @stats[:started_at]
    end

    private

    # Create a TCP socket with the specified timeout.
    #
    # @param timeout [Float] connection timeout
    # @return [TCPSocket] the connected socket
    def create_socket(timeout)
      addr = Socket.getaddrinfo(@host, nil)
      sockaddr = Socket.pack_sockaddr_in(@port, addr[0][3])

      socket = Socket.new(Socket::AF_INET, Socket::SOCK_STREAM, 0)
      socket.setsockopt(Socket::IPPROTO_TCP, Socket::TCP_NODELAY, 1)
      socket.setsockopt(Socket::SOL_SOCKET, Socket::SO_KEEPALIVE, 1)

      # Set socket timeouts
      socket.sync = true

      # Connect with timeout
      begin
        socket.connect_nonblock(sockaddr)
      rescue IO::WaitWritable
        result = IO.select(nil, [socket], nil, timeout)
        if result.nil?
          socket.close
          raise ConnectionTimeoutError.new(
            timeout: timeout, host: @host, port: @port
          )
        end

        begin
          socket.connect_nonblock(sockaddr)
        rescue Errno::EISCONN
          # Connected successfully
        end
      end

      socket
    end

    # Start the reader thread that processes incoming messages.
    def start_reader_thread
      @reader_thread = Thread.new do
        Thread.current.name = "ainos-reader-#{@host}-#{@port}"
        read_loop
      end

      @reader_thread.abort_on_exception = false
    end

    # The main read loop, runs in a separate thread.
    def read_loop
      while @running
        begin
          line = read_line
          break if line.nil?

          process_message(line)
        rescue MalformedMessageError => e
          @stats[:errors] += 1
          log_warn("Malformed message received: #{e.message}")
        rescue JSON::ParserError => e
          @stats[:errors] += 1
          log_warn("JSON parse error: #{e.message}")
        rescue IOError => e
          log_warn("IO error in reader thread: #{e.message}")
          break if @running
        rescue Errno::ECONNRESET => e
          log_warn("Connection reset by peer: #{e.message}")
          break if @running
        rescue StandardError => e
          @stats[:errors] += 1
          log_error("Unexpected error in reader thread: #{e.class}: #{e.message}")
          break if @running
        end
      end

      # Connection was lost, clean up
      if @running
        @mutex.synchronize do
          @connected = false
          @socket = nil
        end

        if @config.auto_reconnect
          begin
            reconnect
          rescue MaxReconnectError => e
            log_error("Auto-reconnect failed: #{e.message}")
          end
        end
      end
    end

    # Read a single line from the socket.
    #
    # @return [String, nil] the line read, or nil on EOF
    def read_line
      @read_mutex.synchronize do
        ensure_connected!

        socket = @socket
        return nil if socket.nil?

        # Read until we have a complete line
        loop do
          # Check if we already have a complete line in the buffer
          if (idx = @partial_line.index(NDJSON_DELIMITER))
            line = @partial_line.slice!(0, idx + 1)
            line = line.chomp(NDJSON_DELIMITER)
            @stats[:messages_received] += 1
            @stats[:bytes_received] += line.bytesize + 1
            @stats[:last_activity] = Time.now
            return line
          end

          # Read more data from the socket
          chunk = socket.readpartial(READ_BUFFER_SIZE)
          @partial_line << chunk
        end
      end
    rescue EOFError
      log_info("EOF on socket to #{@host}:#{@port}")
      nil
    rescue IOError => e
      if @running
        log_warn("IO error reading from socket: #{e.message}")
      end
      nil
    end

    # Write a message to the socket.
    #
    # @param message [String] the JSON message to write
    def write_message(message)
      @write_mutex.synchronize do
        ensure_connected!

        socket = @socket
        raise WriteError.new('Socket is nil') if socket.nil?

        data = message + NDJSON_DELIMITER
        bytes = data.bytesize

        if bytes > @config.max_message_size
          raise MessageTooLargeError.new(
            message_size: bytes,
            max_size: @config.max_message_size
          )
        end

        total_written = 0
        while total_written < bytes
          written = socket.write_nonblock(data.byteslice(total_written..-1))
          total_written += written
        end

        @stats[:messages_sent] += 1
        @stats[:bytes_sent] += bytes
        @stats[:last_activity] = Time.now

        total_written
      end
    rescue IO::WaitWritable
      # Wait for the socket to be writable
      result = IO.select(nil, [@socket], nil, @config.write_timeout)
      if result.nil?
        raise TimeoutError.new(
          timeout: @config.write_timeout,
          operation: 'write to socket'
        )
      end

      retry
    rescue IOError => e
      raise WriteError.new("IO error writing to socket: #{e.message}", cause: e)
    rescue Errno::EPIPE => e
      @connected = false
      raise WriteError.new("Broken pipe - connection to server lost", cause: e)
    end

    # Process an incoming message from the server.
    #
    # @param line [String] the raw JSON line
    def process_message(line)
      hash = JSON.parse(line)
      response = ServerResponse.from_hash(hash)

      # Check if this is a response to a pending request
      @pending_mutex.synchronize do
        if (queue = @pending_requests[response.id])
          queue.push(response)
          return
        end
      end

      # Check if this is a stream chunk
      @stream_mutex.synchronize do
        if (queue = @stream_queues[response.id])
          if response.stream_end?
            queue.push(StreamChunk.new(
              text: '', index: -1, finished: true,
              finish_reason: response.payload.fetch('finish_reason', 'stop'),
              tokens: response.payload.fetch('tokens', nil),
              request_id: response.id
            ))
            queue.push(nil) # Signal end of stream
            @stream_queues.delete(response.id)
          elsif response.stream? || response.type == 'result'
            chunk = StreamChunk.new(
              text: response.payload.fetch('text', ''),
              index: response.payload.fetch('index', 0),
              finished: response.payload.fetch('finished', false),
              finish_reason: response.payload.fetch('finish_reason', nil),
              tokens: response.payload.fetch('tokens', nil),
              request_id: response.id,
              logprobs: response.payload.fetch('logprobs', nil),
              metadata: response.payload.fetch('metadata', {})
            )
            queue.push(chunk)
          end
          return
        end
      end

      # Handle unsolicited messages
      log_debug("Received unsolicited message: type=#{response.type} id=#{response.id}")
    end

    # Wait for a response on a queue with timeout.
    #
    # @param queue [Queue] the response queue
    # @param request_id [String] the request ID
    # @param timeout [Float] the timeout in seconds
    # @return [ServerResponse, nil] the response, or nil on timeout
    def wait_for_response(queue, request_id, timeout)
      result = nil

      begin
        result = Timeout.timeout(timeout) do
          queue.pop
        end
      rescue ::Timeout::Error
        log_warn("Request #{request_id} timed out after #{timeout}s")
        # Clean up the queue
        @pending_mutex.synchronize do
          @pending_requests.delete(request_id)
        end
        return nil
      end

      result
    end

    # Ensure the transport is connected.
    #
    # @raise [Ainos::NotConnectedError] if not connected
    def ensure_connected!
      unless connected?
        if @config.auto_reconnect
          reconnect
        else
          raise NotConnectedError.new(
            "Not connected to #{@host}:#{@port}"
          )
        end
      end
    end

    # Log an info message.
    def log_info(msg)
      @logger&.info("[Ainos::Transport] #{msg}")
    end

    # Log a warning message.
    def log_warn(msg)
      @logger&.warn("[Ainos::Transport] #{msg}")
    end

    # Log an error message.
    def log_error(msg)
      @logger&.error("[Ainos::Transport] #{msg}")
    end

    # Log a debug message.
    def log_debug(msg)
      @logger&.debug("[Ainos::Transport] #{msg}")
    end
  end
end