# frozen_string_literal: true

require_relative 'spec_helper'

RSpec.describe Ainos::Transport do
  let(:host) { '127.0.0.1' }
  let(:port) { 0 }
  let(:config) { Ainos::Configuration.new(host: host, port: port, auto_reconnect: false) }
  let(:transport) { described_class.new(host, port, config) }
  let(:mock_daemon) { MockDaemon.new }

  before(:each) do
    mock_daemon.start
    # Update transport to use the mock daemon's port
    # Re-create transport with the actual port
    @real_transport = Ainos::Transport.new(host, mock_daemon.port, config)
  end

  after(:each) do
    @real_transport&.disconnect rescue nil
    mock_daemon.stop rescue nil
  end

  describe '#initialize' do
    it 'creates a transport with the given host and port' do
      transport = Ainos::Transport.new('127.0.0.1', 9500)
      expect(transport.host).to eq('127.0.0.1')
      expect(transport.port).to eq(9500)
    end

    it 'creates a transport with a configuration object' do
      cfg = Ainos::Configuration.new(host: 'localhost', port: 9500)
      transport = Ainos::Transport.new('localhost', 9500, cfg)
      expect(transport.host).to eq('localhost')
      expect(transport.port).to eq(9500)
    end

    it 'initializes with not connected' do
      expect(@real_transport.connected?).to be false
    end

    it 'initializes stats with zeros' do
      expect(@real_transport.stats[:messages_sent]).to eq(0)
      expect(@real_transport.stats[:messages_received]).to eq(0)
      expect(@real_transport.stats[:bytes_sent]).to eq(0)
      expect(@real_transport.stats[:bytes_received]).to eq(0)
    end
  end

  describe '#connect' do
    it 'connects to the daemon' do
      result = @real_transport.connect
      expect(result).to be true
      expect(@real_transport.connected?).to be true
    end

    it 'returns true if already connected' do
      @real_transport.connect
      result = @real_transport.connect
      expect(result).to be true
    end

    it 'raises ConnectionError when connection is refused' do
      bad_transport = Ainos::Transport.new('127.0.0.1', 1, config)
      expect { bad_transport.connect(timeout: 1) }.to raise_error(Ainos::ConnectionError)
    end

    it 'sets the socket file descriptor' do
      @real_transport.connect
      expect(@real_transport.socket_fd).to be_a(Integer)
    end

    it 'records the start time in stats' do
      @real_transport.connect
      expect(@real_transport.stats[:started_at]).to be_a(Time)
    end
  end

  describe '#disconnect' do
    it 'disconnects from the daemon' do
      @real_transport.connect
      result = @real_transport.disconnect
      expect(result).to be true
      expect(@real_transport.connected?).to be false
    end

    it 'returns true even if not connected' do
      result = @real_transport.disconnect
      expect(result).to be true
    end

    it 'can reconnect after disconnect' do
      @real_transport.connect
      @real_transport.disconnect
      @real_transport.connect
      expect(@real_transport.connected?).to be true
    end
  end

  describe '#connected?' do
    it 'returns false when not connected' do
      expect(@real_transport.connected?).to be false
    end

    it 'returns true when connected' do
      @real_transport.connect
      expect(@real_transport.connected?).to be true
    end

    it 'returns false after disconnect' do
      @real_transport.connect
      @real_transport.disconnect
      expect(@real_transport.connected?).to be false
    end
  end

  describe '#send_request' do
    before(:each) { @real_transport.connect }

    it 'sends a request and receives a response' do
      response = @real_transport.send_request(
        type: 'ping',
        payload: {}
      )
      expect(response).to be_a(Ainos::ServerResponse)
      expect(response.success?).to be true
      expect(response.type).to eq('result')
    end

    it 'includes the request ID in the response' do
      response = @real_transport.send_request(
        type: 'ping',
        payload: {},
        request_id: 'my-custom-id'
      )
      expect(response.id).to eq('my-custom-id')
    end

    it 'raises NotConnectedError when not connected' do
      @real_transport.disconnect
      expect {
        @real_transport.send_request(type: 'ping', payload: {})
      }.to raise_error(Ainos::NotConnectedError)
    end

    it 'sends multiple requests with unique IDs' do
      r1 = @real_transport.send_request(type: 'ping', payload: {}, request_id: 'req-1')
      r2 = @real_transport.send_request(type: 'ping', payload: {}, request_id: 'req-2')

      expect(r1.id).to eq('req-1')
      expect(r2.id).to eq('req-2')
    end

    it 'handles error responses from the server' do
      mock_daemon.on_default do |request, client|
        mock_daemon.send(:send_error, client, request, 'Test error', code: 'test_error')
      end

      response = @real_transport.send_request(type: 'error_test', payload: {})
      expect(response.success?).to be false
      expect(response.error).to eq('Test error')
    end

    it 'increments message counters' do
      expect {
        @real_transport.send_request(type: 'ping', payload: {})
      }.to change { @real_transport.stats[:messages_sent] }.by(1)
    end
  end

  describe '#send_stream_request' do
    before(:each) { @real_transport.connect }

    it 'yields stream chunks when a block is given' do
      chunks = []
      mock_daemon.stream_scenario(['Hello', ' ', 'World'])

      @real_transport.send_stream_request(
        type: 'infer',
        payload: { model: 'test', prompt: 'Hi', stream: true }
      ) { |chunk| chunks << chunk }

      expect(chunks.length).to eq(3)
      expect(chunks.map(&:text).join).to eq('Hello World')
    end

    it 'returns an enumerator when no block is given' do
      mock_daemon.stream_scenario(['A', 'B', 'C'])

      enum = @real_transport.send_stream_request(
        type: 'infer',
        payload: { model: 'test', prompt: 'Hi', stream: true }
      )

      expect(enum).to be_a(Enumerator::Lazy)
      expect(enum.map(&:text).to_a.join).to eq('ABC')
    end

    it 'marks the final chunk correctly' do
      chunks = []
      mock_daemon.stream_scenario(['One', 'Two'])

      @real_transport.send_stream_request(
        type: 'infer',
        payload: { model: 'test', prompt: 'Hi', stream: true }
      ) { |chunk| chunks << chunk }

      expect(chunks.last.final?).to be true
    end

    it 'raises NotConnectedError when not connected' do
      @real_transport.disconnect
      expect {
        @real_transport.send_stream_request(
          type: 'infer',
          payload: { model: 'test', prompt: 'Hi', stream: true }
        )
      }.to raise_error(Ainos::NotConnectedError)
    end
  end

  describe '#reconnect' do
    it 'reconnects after disconnection' do
      @real_transport.connect
      @real_transport.disconnect
      result = @real_transport.reconnect
      expect(result).to be true
      expect(@real_transport.connected?).to be true
    end

    it 'raises MaxReconnectError after max attempts' do
      bad_transport = Ainos::Transport.new('127.0.0.1', 1, Ainos::Configuration.new(
        host: '127.0.0.1', port: 1,
        max_reconnect_attempts: 2, reconnect_delay: 0.1,
        auto_reconnect: false
      ))

      expect {
        bad_transport.reconnect(timeout: 0.5)
      }.to raise_error(Ainos::MaxReconnectError)
    end

    it 'increments reconnection counter' do
      @real_transport.connect
      @real_transport.disconnect
      expect {
        @real_transport.reconnect
      }.to change { @real_transport.stats[:reconnections] }.by(1)
    end
  end

  describe '#healthy?' do
    it 'returns false when not connected' do
      expect(@real_transport.healthy?).to be false
    end

    it 'returns true when connected and healthy' do
      @real_transport.connect
      expect(@real_transport.healthy?).to be true
    end
  end

  describe '#reset_stats!' do
    it 'resets all statistics' do
      @real_transport.connect
      @real_transport.send_request(type: 'ping', payload: {})
      @real_transport.reset_stats!

      expect(@real_transport.stats[:messages_sent]).to eq(0)
      expect(@real_transport.stats[:messages_received]).to eq(0)
      expect(@real_transport.stats[:bytes_sent]).to eq(0)
      expect(@real_transport.stats[:bytes_received]).to eq(0)
    end

    it 'preserves the started_at and reconnection count' do
      @real_transport.connect
      @real_transport.disconnect
      @real_transport.reconnect
      started_at = @real_transport.stats[:started_at]
      reconnections = @real_transport.stats[:reconnections]

      @real_transport.reset_stats!

      expect(@real_transport.stats[:started_at]).to eq(started_at)
      expect(@real_transport.stats[:reconnections]).to eq(reconnections)
    end
  end

  describe '#connection_age' do
    it 'returns nil when not connected' do
      expect(@real_transport.connection_age).to be_nil
    end

    it 'returns the connection age when connected' do
      @real_transport.connect
      expect(@real_transport.connection_age).to be_a(Float)
      expect(@real_transport.connection_age).to be >= 0
    end
  end

  describe 'thread safety' do
    it 'handles concurrent requests' do
      @real_transport.connect
      threads = []
      results = []

      mutex = Mutex.new
      5.times do |i|
        threads << Thread.new do
          response = @real_transport.send_request(
            type: 'ping',
            payload: {},
            request_id: "concurrent-#{i}"
          )
          mutex.synchronize { results << response }
        end
      end

      threads.each(&:join)
      expect(results.length).to eq(5)
      expect(results.all?(&:success?)).to be true
    end
  end
end