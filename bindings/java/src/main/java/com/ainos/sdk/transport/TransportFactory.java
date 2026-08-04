package com.ainos.sdk.transport;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;

/**
 * Factory for creating {@link TcpTransport} instances.
 * <p>
 * Provides convenience methods for creating transports with common
 * configurations. Custom transport implementations can be created
 * by implementing the {@link TcpTransport} interface directly.
 */
public final class TransportFactory {

    private TransportFactory() {
        // utility class
    }

    /**
     * Creates a default TCP transport to {@code 127.0.0.1:9500}.
     *
     * @return a new TcpTransport instance
     */
    public static TcpTransport createDefault() {
        return create("127.0.0.1", 9500);
    }

    /**
     * Creates a TCP transport with the specified host and port.
     *
     * @param host the daemon hostname or IP
     * @param port the daemon TCP port
     * @return a new TcpTransport instance
     */
    public static TcpTransport create(String host, int port) {
        return new TcpTransportImpl(host, port);
    }

    /**
     * Creates a TCP transport with full configuration.
     *
     * @param host             the daemon hostname or IP
     * @param port             the daemon TCP port
     * @param connectTimeoutMs connection timeout in milliseconds
     * @param readTimeoutMs    read timeout in milliseconds
     * @param tcpNoDelay       whether to enable TCP_NODELAY
     * @return a new TcpTransport instance
     */
    public static TcpTransport create(String host, int port,
                                      int connectTimeoutMs, int readTimeoutMs,
                                      boolean tcpNoDelay) {
        return new TcpTransportImpl(host, port, connectTimeoutMs, readTimeoutMs, tcpNoDelay);
    }

    /**
     * Creates a transport and immediately connects it.
     *
     * @param host the daemon hostname or IP
     * @param port the daemon TCP port
     * @return a connected TcpTransport instance
     * @throws AinosConnectionException if the connection cannot be established
     * @throws AinosTimeoutException    if the connection times out
     */
    public static TcpTransport connect(String host, int port)
            throws AinosConnectionException, AinosTimeoutException {
        TcpTransport transport = create(host, port);
        transport.connect();
        return transport;
    }

    /**
     * Creates a default transport and immediately connects it.
     *
     * @return a connected TcpTransport instance
     * @throws AinosConnectionException if the connection cannot be established
     * @throws AinosTimeoutException    if the connection times out
     */
    public static TcpTransport connectDefault()
            throws AinosConnectionException, AinosTimeoutException {
        return connect("127.0.0.1", 9500);
    }
}