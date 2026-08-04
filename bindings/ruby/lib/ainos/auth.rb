# frozen_string_literal: true

require 'securerandom'

module Ainos
  # Manages Bearer token authentication for the Ainos daemon.
  #
  # Provides token validation, storage, and refresh capabilities.
  # The token is sent as a Bearer token in the Authorization header
  # of each request to the daemon.
  #
  # @example Basic usage
  #   auth = Ainos::Auth.new('my-token-12345')
  #   auth.token  # => "my-token-12345"
  #   auth.header_value  # => "Bearer my-token-12345"
  #
  # @example Token from environment variable
  #   auth = Ainos::Auth.from_env('AINOS_TOKEN')
  class Auth
    # @return [String] the current Bearer token
    attr_reader :token

    # @return [Time, nil] when the token was set
    attr_reader :set_at

    # @return [Time, nil] when the token expires
    attr_reader :expires_at

    # @return [String, nil] the token source (e.g., 'env', 'file', 'manual')
    attr_reader :source

    # Create a new Auth instance with a Bearer token.
    #
    # @param token [String] the Bearer token
    # @param expires_at [Time, String, nil] optional token expiry time
    # @param source [String, nil] the token source description
    #
    # @raise [Ainos::InvalidTokenError] if the token is invalid
    #
    # @example
    #   auth = Ainos::Auth.new('sk-abc123def456')
    def initialize(token, expires_at: nil, source: nil)
      @token = validate_token(token)
      @set_at = Time.now
      @expires_at = parse_expiry(expires_at)
      @source = source
    end

    # Create an Auth instance from an environment variable.
    #
    # @param env_var [String] the environment variable name
    # @param required [Boolean] whether to raise if the variable is not set
    #
    # @return [Auth] a new Auth instance
    #
    # @raise [Ainos::InvalidTokenError] if the env var is not set and required
    #
    # @example
    #   auth = Ainos::Auth.from_env('AINOS_API_TOKEN')
    def self.from_env(env_var = 'AINOS_TOKEN', required: true)
      token = ENV[env_var]

      if token.nil? || token.strip.empty?
        if required
          raise InvalidTokenError.new(
            "Environment variable #{env_var} is not set or empty"
          )
        end

        return nil
      end

      new(token.strip, source: "env:#{env_var}")
    end

    # Create an Auth instance from a token file.
    #
    # @param path [String] the path to the token file
    #
    # @return [Auth] a new Auth instance
    #
    # @raise [Ainos::InvalidTokenError] if the file cannot be read
    #
    # @example
    #   auth = Ainos::Auth.from_file('/etc/ainos/token')
    def self.from_file(path)
      token = File.read(path).strip

      if token.empty?
        raise InvalidTokenError.new("Token file #{path} is empty")
      end

      new(token, source: "file:#{path}")
    rescue Errno::ENOENT => e
      raise InvalidTokenError.new(
        "Token file not found: #{path}",
        cause: e
      )
    rescue Errno::EACCES => e
      raise InvalidTokenError.new(
        "Permission denied reading token file: #{path}",
        cause: e
      )
    end

    # Create an Auth instance with a random token for testing.
    #
    # @return [Auth] a new Auth instance with a random token
    #
    # @api private
    def self.random
      new("test-#{SecureRandom.hex(24)}", source: 'random')
    end

    # Update the token.
    #
    # @param new_token [String] the new token
    # @param expires_at [Time, String, nil] optional expiry
    #
    # @raise [Ainos::InvalidTokenError] if the new token is invalid
    #
    # @example
    #   auth.token = 'new-token-abc'
    def token=(new_token)
      @token = validate_token(new_token)
      @set_at = Time.now
      @expires_at = nil
    end

    # Get the Authorization header value.
    #
    # @return [String] the full Authorization header value
    #
    # @example
    #   auth.header_value  # => "Bearer sk-abc123..."
    def header_value
      "Bearer #{@token}"
    end

    # Check if the token has expired.
    #
    # @return [Boolean] true if the token has expired
    #
    # @example
    #   auth.expired?  # => false
    def expired?
      return false unless @expires_at

      Time.now >= @expires_at
    end

    # Check if the token is still valid.
    #
    # @return [Boolean] true if the token is valid and not expired
    def valid?
      !expired?
    end

    # Get the time until the token expires.
    #
    # @return [Float, nil] seconds until expiry, or nil if no expiry
    def time_to_expiry
      return nil unless @expires_at

      @expires_at - Time.now
    end

    # Get the time since the token was set.
    #
    # @return [Float] seconds since the token was set
    def age
      Time.now - @set_at
    end

    # Mask the token for display, showing only the last 4 characters.
    #
    # @return [String] the masked token
    #
    # @example
    #   auth.masked_token  # => "****...f456"
    def masked_token
      return @token if @token.length <= 8

      "#{'*' * (@token.length - 4)}#{@token.slice(-4, 4)}"
    end

    # Convert to a hash suitable for server requests.
    #
    # @return [Hash] the auth hash
    def to_h
      { token: @token, type: 'bearer' }
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} token=#{masked_token.inspect} " \
        "expired=#{expired?} source=#{@source.inspect}>"
    end

    # @return [String] a short string representation
    def to_s
      "Auth(token: #{masked_token})"
 end

    private

    # Validate the token format.
    #
    # @param token [String] the token to validate
    # @return [String] the validated token
    # @raise [Ainos::InvalidTokenError] if the token is invalid
    def validate_token(token)
      raise InvalidTokenError.new('Token is nil') if token.nil?

      token = token.to_s.strip

      if token.empty?
        raise InvalidTokenError.new('Token is empty')
      end

      if token.length < 8
        raise InvalidTokenError.new(
          "Token is too short (#{token.length} chars, minimum 8)"
        )
      end

      if token.include?("\n") || token.include?("\r")
        raise InvalidTokenError.new('Token contains newline characters')
      end

      if token.include?(' ')
        raise InvalidTokenError.new('Token contains whitespace')
      end

      token
    end

    # Parse the expiry time.
    #
    # @param expires_at [Time, String, nil] the expiry time
    # @return [Time, nil] the parsed time
    def parse_expiry(expires_at)
      case expires_at
      when Time then expires_at
      when String then Time.parse(expires_at)
      when Integer then Time.at(expires_at)
      else nil
      end
    rescue ArgumentError => e
      raise InvalidTokenError.new("Invalid expiry time format: #{e.message}")
    end
  end

  # Manages authentication for multiple tokens or token rotation.
  #
  # @example
  #   provider = Ainos::TokenProvider.new
  #   provider.add_token('primary', 'token-123')
  #   provider.add_token('backup', 'token-456')
  #   provider.current_token  # => "token-123"
  class TokenProvider
    # @return [Hash<String, String>] the token store
    attr_reader :tokens

    # @return [String] the key of the current token
    attr_reader :current_key

    # Create a new token provider.
    #
    # @param tokens [Hash<String, String>] initial tokens
    # @param default_key [String] the default token key
    def initialize(tokens = {}, default_key = nil)
      @tokens = tokens.dup
      @mutex = Mutex.new
      @current_key = default_key || tokens.keys.first
    end

    # Add a token.
    #
    # @param key [String] the token key
    # @param token [String] the token value
    def add_token(key, token)
      @mutex.synchronize do
        @tokens[key] = token
        @current_key ||= key
      end
    end

    # Remove a token.
    #
    # @param key [String] the token key
    # @return [String, nil] the removed token
    def remove_token(key)
      @mutex.synchronize { @tokens.delete(key) }
    end

    # Switch to a different token.
    #
    # @param key [String] the token key to switch to
    # @raise [KeyError] if the key doesn't exist
    def switch_to(key)
      @mutex.synchronize do
        raise KeyError, "Token '#{key}' not found" unless @tokens.key?(key)

        @current_key = key
      end
    end

    # Get the current token.
    #
    # @return [String, nil] the current token
    def current_token
      @mutex.synchronize { @tokens[@current_key] }
    end

    # Get the current Auth instance.
    #
    # @return [Auth, nil] an Auth instance for the current token
    def current_auth
      token = current_token
      return nil unless token

      Auth.new(token, source: "provider:#{@current_key}")
    end

    # Rotate to the next token.
    #
    # @return [String, nil] the new current token
    def rotate
      @mutex.synchronize do
        return nil if @tokens.empty?

        keys = @tokens.keys
        idx = keys.index(@current_key) || 0
        @current_key = keys[(idx + 1) % keys.length]
        @tokens[@current_key]
      end
    end

    # @return [Integer] the number of tokens
    def size
      @tokens.size
    end

    # @return [String] human-readable representation
    def inspect
      "#<#{self.class.name} tokens=#{@tokens.size} current=#{@current_key.inspect}>"
    end
  end
end