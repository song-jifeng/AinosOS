# frozen_string_literal: true

# Ainos Ruby SDK
#
# Ruby SDK for interacting with the Ainos inference daemon.
# Provides a high-level client for model inference, streaming,
# model management, and server monitoring.
#
# @example
#   require 'ainos'
#
#   client = Ainos::Client.new(token: ENV['AINOS_TOKEN'])
#   client.connect
#
#   response = client.infer(model: 'llama3', prompt: 'Hello, world!')
#   puts response.text
#
#   client.disconnect
#
# @see Ainos::Client Main client class
# @see Ainos::InferenceRequest Request object for inference
# @see Ainos::StreamSession Streaming inference support

require_relative 'ainos/version'
require_relative 'ainos/errors'
require_relative 'ainos/types'
require_relative 'ainos/auth'
require_relative 'ainos/transport'
require_relative 'ainos/streaming'
require_relative 'ainos/client'

# Check Ruby version compatibility
Ainos.check_version!

# Top-level convenience methods for the Ainos module.
#
# These methods provide quick access to common operations
# without explicitly creating a Client instance.
module Ainos
  class << self
    # Create a new client and connect to the daemon.
    #
    # @param kwargs [Hash] configuration options
    # @yield [config] optional configuration block
    #
    # @return [Client] a connected client
    #
    # @example
    #   client = Ainos.new_client(token: 'my-token')
    def new_client(**kwargs, &block)
      client = Client.new(**kwargs, &block)
      client.connect
      client
    end

    # Quick inference with a single call.
    #
    # Creates a client, connects, performs inference, and disconnects.
    #
    # @param prompt [String] the input prompt
    # @param model [String] the model name
    # @param kwargs [Hash] additional inference parameters
    #
    # @return [InferenceResponse] the inference response
    #
    # @example
    #   response = Ainos.infer(prompt: 'Hello!', model: 'llama3')
    def infer(prompt:, model:, **kwargs)
      token = kwargs.delete(:token) || ENV['AINOS_TOKEN']
      host = kwargs.delete(:host) || DEFAULT_HOST
      port = kwargs.delete(:port) || DEFAULT_PORT

      client = new_client(token: token, host: host, port: port)

      begin
        client.infer(model: model, prompt: prompt, **kwargs)
      ensure
        client.disconnect
      end
    end

    # Quick streaming inference.
    #
    # @param prompt [String] the input prompt
    # @param model [String] the model name
    # @param kwargs [Hash] additional parameters
    # @yield [StreamChunk] each chunk
    #
    # @return [StreamSession] the stream session
    def infer_stream(prompt:, model:, **kwargs, &block)
      token = kwargs.delete(:token) || ENV['AINOS_TOKEN']
      host = kwargs.delete(:host) || DEFAULT_HOST
      port = kwargs.delete(:port) || DEFAULT_PORT

      client = new_client(token: token, host: host, port: port)

      begin
        client.infer_stream(model: model, prompt: prompt, **kwargs, &block)
      ensure
        client.disconnect unless block
      end
    end

    # Check the health of a daemon.
    #
    # @param host [String] the daemon host
    # @param port [Integer] the daemon port
    # @param token [String, nil] auth token
    #
    # @return [HealthStatus] the health status
    def health(host: DEFAULT_HOST, port: DEFAULT_PORT, token: nil)
      client = new_client(token: token, host: host, port: port)

      begin
        client.health
      ensure
        client.disconnect
      end
    end

    # List available models.
    #
    # @param host [String] the daemon host
    # @param port [Integer] the daemon port
    # @param token [String, nil] auth token
    #
    # @return [Array<ModelInfo>] list of models
    def model_list(host: DEFAULT_HOST, port: DEFAULT_PORT, token: nil)
      client = new_client(token: token, host: host, port: port)

      begin
        client.model_list
      ensure
        client.disconnect
      end
    end
  end
end