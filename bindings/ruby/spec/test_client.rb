# frozen_string_literal: true

require_relative 'spec_helper'

RSpec.describe Ainos::Client do
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

  describe '#initialize' do
    it 'creates a client with default configuration' do
      c = Ainos::Client.new
      expect(c.config.host).to eq('127.0.0.1')
      expect(c.config.port).to eq(9500)
    end

    it 'creates a client with a configuration block' do
      c = Ainos::Client.new do |config|
        config.host = '10.0.0.1'
        config.port = 9000
        config.token = 'custom-token'
      end
      expect(c.config.host).to eq('10.0.0.1')
      expect(c.config.port).to eq(9000)
      expect(c.config.token).to eq('custom-token')
    end

    it 'creates a client with keyword arguments' do
      c = Ainos::Client.new(host: '192.168.1.1', port: 9500, token: 'kw-token')
      expect(c.config.host).to eq('192.168.1.1')
      expect(c.config.port).to eq(9500)
      expect(c.config.token).to eq('kw-token')
    end

    it 'sets up authentication from the token' do
      c = Ainos::Client.new(token: 'my-secret-token-12345')
      expect(c.auth).to be_a(Ainos::Auth)
      expect(c.auth.token).to eq('my-secret-token-12345')
    end

    it 'does not require authentication' do
      c = Ainos::Client.new
      expect(c.auth).to be_nil
    end
  end

  describe '#connect' do
    it 'connects to the daemon' do
      c = Ainos::Client.new(host: '127.0.0.1', port: mock_daemon.port)
      result = c.connect
      expect(result).to be true
      expect(c.connected?).to be true
      c.disconnect
    end

    it 'raises ConnectionError when connection fails' do
      c = Ainos::Client.new(host: '127.0.0.1', port: 1, connection_timeout: 1)
      expect { c.connect }.to raise_error(Ainos::ConnectionError)
    end
  end

  describe '#disconnect' do
    it 'disconnects from the daemon' do
      result = client.disconnect
      expect(result).to be true
      expect(client.connected?).to be false
    end

    it 'can be called multiple times' do
      client.disconnect
      result = client.disconnect
      expect(result).to be true
    end
  end

  describe '#connected?' do
    it 'returns true when connected' do
      expect(client.connected?).to be true
    end

    it 'returns false after disconnect' do
      client.disconnect
      expect(client.connected?).to be false
    end
  end

  describe '#health' do
    it 'returns a HealthStatus object' do
      health = client.health
      expect(health).to be_a(Ainos::HealthStatus)
      expect(health.healthy?).to be true
    end

    it 'contains server information' do
      health = client.health
      expect(health.status).to eq('ok')
      expect(health.version).to eq('1.0.0')
    end

    it 'includes uptime information' do
      health = client.health
      expect(health.uptime).to be_a(Float)
    end
  end

  describe '#status' do
    it 'returns a ServerStatus object' do
      status = client.status
      expect(status).to be_a(Ainos::ServerStatus)
    end

    it 'contains server details' do
      status = client.status
      expect(status.version).to be_a(String)
      expect(status.active_connections).to be_a(Integer)
      expect(status.total_requests).to be_a(Integer)
    end

    it 'has a formatted string representation' do
      status = client.status
      expect(status.to_s).to include('Server')
      expect(status.to_s).to include('v1.0.0')
    end
  end

  describe '#infer' do
    it 'returns an InferenceResponse' do
      response = client.infer(model: 'llama3', prompt: 'Hello!')
      expect(response).to be_a(Ainos::InferenceResponse)
    end

    it 'contains the generated text' do
      response = client.infer(model: 'llama3', prompt: 'Hello!')
      expect(response.text).to be_a(String)
      expect(response.text).not_to be_empty
    end

    it 'accepts an InferenceRequest object' do
      request = Ainos::InferenceRequest.new(model: 'llama3', prompt: 'Test')
      response = client.infer(request)
      expect(response).to be_a(Ainos::InferenceResponse)
    end

    it 'includes token usage information' do
      response = client.infer(model: 'llama3', prompt: 'Hello!')
      expect(response.tokens).to be_a(Integer)
      expect(response.finish_reason).to eq('stop')
    end

    it 'raises InferenceError when the server returns an error' do
      mock_daemon.on_request('infer') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Inference failed', code: 'inference_error')
      end

      expect {
        client.infer(model: 'llama3', prompt: 'Hello!')
      }.to raise_error(Ainos::InferenceError)
    end

    it 'raises ModelNotFoundError when the model is not found' do
      mock_daemon.on_request('infer') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Model not found', code: 'model_not_found')
      end

      expect {
        client.infer(model: 'nonexistent', prompt: 'Hello!')
      }.to raise_error(Ainos::ModelNotFoundError)
    end
  end

  describe '#infer_stream' do
    it 'yields StreamChunk objects when a block is given' do
      chunks = []
      mock_daemon.stream_scenario(['Hello', ' ', 'World'])

      client.infer_stream(model: 'llama3', prompt: 'Hi') { |chunk| chunks << chunk }
      expect(chunks.length).to be > 0
      expect(chunks.first).to be_a(Ainos::StreamChunk)
    end

    it 'returns a lazy enumerator when no block is given' do
      mock_daemon.stream_scenario(['A', 'B', 'C'])

      enum = client.infer_stream(model: 'llama3', prompt: 'Hi')
      expect(enum).to be_a(Enumerator::Lazy)
    end

    it 'returns a StreamSession when a block is given' do
      session = client.infer_stream(model: 'llama3', prompt: 'Hi') { |c| }
      expect(session).to be_a(Ainos::StreamSession)
    end
  end

  describe '#model_list' do
    it 'returns an array of ModelInfo objects' do
      models = client.model_list
      expect(models).to be_an(Array)
      expect(models.first).to be_a(Ainos::ModelInfo)
    end

    it 'includes model details' do
      models = client.model_list
      model = models.first
      expect(model.name).to be_a(String)
      expect(model.status).to be_a(String)
    end

    it 'returns multiple models' do
      models = client.model_list
      expect(models.length).to be >= 3
    end

    it 'identifies loaded models' do
      models = client.model_list
      loaded = models.select(&:loaded?)
      expect(loaded.length).to be >= 2
    end
  end

  describe '#model_load' do
    it 'returns a ModelInfo for the loaded model' do
      result = client.model_load('llama3')
      expect(result).to be_a(Ainos::ModelInfo)
      expect(result.status).to eq('loaded')
    end

    it 'accepts a ModelLoadRequest object' do
      request = Ainos::ModelLoadRequest.new(model: 'llama3', gpu_layers: 32)
      result = client.model_load(request)
      expect(result).to be_a(Ainos::ModelInfo)
    end

    it 'accepts a string model name' do
      result = client.model_load('llama3')
      expect(result).to be_a(Ainos::ModelInfo)
    end

    it 'raises ModelLoadError on failure' do
      mock_daemon.on_request('model_load') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Load failed', code: 'load_failed')
      end

      expect {
        client.model_load('broken-model')
      }.to raise_error(Ainos::ModelLoadError)
    end
  end

  describe '#model_unload' do
    it 'returns true when successful' do
      result = client.model_unload('llama3')
      expect(result).to be true
    end

    it 'raises ModelUnloadError on failure' do
      mock_daemon.on_request('model_unload') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Unload failed', code: 'unload_failed')
      end

      expect {
        client.model_unload('broken-model')
      }.to raise_error(Ainos::ModelUnloadError)
    end
  end

  describe '#context_store' do
    it 'returns a ContextEntry' do
      context = client.context_store('test-context', { key: 'value' })
      expect(context).to be_a(Ainos::ContextEntry)
      expect(context.id).to eq('test-context')
    end

    it 'accepts a TTL parameter' do
      context = client.context_store('test-context', { key: 'value' }, ttl: 3600)
      expect(context.ttl).to eq(3600)
    end

    it 'raises ContextError on failure' do
      mock_daemon.on_request('context_store') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Store failed')
      end

      expect {
        client.context_store('test', {})
      }.to raise_error(Ainos::ContextError)
    end
  end

  describe '#context_retrieve' do
    it 'returns a ContextEntry for existing contexts' do
      client.context_store('test-context', { key: 'value' })
      context = client.context_retrieve('test-context')
      expect(context).to be_a(Ainos::ContextEntry)
      expect(context.id).to eq('test-context')
    end

    it 'raises ContextError on failure' do
      mock_daemon.on_request('context_retrieve') do |request, socket|
        mock_daemon.send(:send_error, socket, request, 'Retrieve failed')
      end

      expect {
        client.context_retrieve('missing')
      }.to raise_error(Ainos::ContextError)
    end
  end

  describe '#ping' do
    it 'returns true when the server responds' do
      expect(client.ping).to be true
    end

    it 'returns false when not connected' do
      client.disconnect
      expect(client.ping).to be false
    end
  end

  describe '#model_loaded?' do
    it 'returns true for loaded models' do
      expect(client.model_loaded?('llama3')).to be true
    end

    it 'returns false for unloaded models' do
      expect(client.model_loaded?('nonexistent')).to be false
    end
  end

  describe '#request_count' do
    it 'starts at zero' do
      c = Ainos::Client.new(host: '127.0.0.1', port: mock_daemon.port, token: 'test')
      c.connect
      expect(c.request_count).to eq(0)
      c.disconnect
    end

    it 'increments with each request' do
      client.infer(model: 'llama3', prompt: 'Hello!')
      client.health
      expect(client.request_count).to be >= 2
    end
  end

  describe '#stats' do
    it 'returns a hash with connection information' do
      stats = client.stats
      expect(stats).to be_a(Hash)
      expect(stats[:connected]).to be true
      expect(stats[:request_count]).to be_a(Integer)
      expect(stats[:transport_stats]).to be_a(Hash)
    end
  end

  describe '#daemon_version' do
    it 'returns the version string' do
      expect(client.daemon_version).to eq('1.0.0')
    end
  end

  describe '#wait_for_model' do
    it 'returns true when the model is ready' do
      expect(client.wait_for_model('llama3', timeout: 5)).to be true
    end

    it 'raises TimeoutError when the model is not ready in time' do
      mock_daemon.on_request('model_list') do |request, socket|
        mock_daemon.send(:send_response, socket, request, { models: [] })
      end

      expect {
        client.wait_for_model('ghost-model', timeout: 1, poll_interval: 0.1)
      }.to raise_error(Ainos::TimeoutError)
    end
  end
end