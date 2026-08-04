// Ainos OS - Windows Service Wrapper
//
// This file provides a native Windows Service wrapper for the Ainos AI Daemon.
// It manages the Rust ai-daemon.exe as a child process and provides SCM integration.
//
// Service Name:  AinosAIDaemon
// Display Name:  Ainos OS AI Daemon
// Description:   Core AI service manager for Ainos OS
//
// Usage:
//   ainos_service.exe --install     Register the service with SCM
//   ainos_service.exe --uninstall   Remove the service from SCM
//   ainos_service.exe --start       Start the service manually
//   ainos_service.exe --stop        Stop the service manually
//   ainos_service.exe (no args)     Run as a service (called by SCM)

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <winsvc.h>
#include <tchar.h>
#include <strsafe.h>
#include <shellapi.h>
#include <accctrl.h>
#include <aclapi.h>
#include <process.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <stdlib.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <iostream>
#include <chrono>
#include <thread>
#include <mutex>
#include <atomic>
#include <memory>
#include <cwchar>
#include <cstring>

// ============================================================================
// Constants
// ============================================================================

// Service identities
const wchar_t* SERVICE_NAME = L"AinosAIDaemon";
const wchar_t* SERVICE_DISPLAY_NAME = L"Ainos OS AI Daemon";
const wchar_t* SERVICE_DESCRIPTION = L"Core AI service manager for Ainos OS. "
    L"Provides model lifecycle management, inference routing, context management, "
    L"and system resource monitoring.";

// Registry paths
const wchar_t* REGISTRY_ROOT = L"SOFTWARE\\AinosOS";
const wchar_t* REGISTRY_SETTINGS = L"SOFTWARE\\AinosOS\\Settings";
const wchar_t* REGISTRY_PATHS = L"SOFTWARE\\AinosOS\\Paths";

// Default paths
const wchar_t* DEFAULT_INSTALL_DIR = L"C:\\Program Files\\AinosOS";
const wchar_t* DEFAULT_BIN_DIR = L"C:\\Program Files\\AinosOS\\bin";
const wchar_t* DEFAULT_DAEMON_EXE = L"C:\\Program Files\\AinosOS\\bin\\ai-daemon.exe";
const wchar_t* DEFAULT_CONFIG_PATH = L"C:\\Program Files\\AinosOS\\configs\\ai-daemon.toml";
const wchar_t* DEFAULT_LOG_DIR = L"C:\\ProgramData\\AinosOS\\Logs";

// Service control
const DWORD SERVICE_START_TIMEOUT_MS = 30000;
const DWORD SERVICE_STOP_TIMEOUT_MS = 30000;
const DWORD SERVICE_PAUSE_TIMEOUT_MS = 10000;
const DWORD SERVICE_STATUS_CHECK_INTERVAL_MS = 1000;
const DWORD CHILD_PROCESS_MONITOR_INTERVAL_MS = 2000;
const DWORD CHILD_PROCESS_RESTART_DELAY_MS = 5000;

// Recovery
const DWORD RECOVERY_DELAYS[] = {30000, 60000, 120000}; // 30s, 60s, 120s
const int RECOVERY_DELAY_COUNT = 3;
const int MAX_RESTART_ATTEMPTS = 10;
const DWORD RESTART_COUNTER_RESET_SECONDS = 86400; // 24 hours

// Named pipe
const wchar_t* DAEMON_PIPE_NAME = L"\\\\.\\pipe\\ainos-daemon";

// Event IDs
const DWORD EVENT_INFO_BASE = 1000;
const DWORD EVENT_WARNING_BASE = 2000;
const DWORD EVENT_ERROR_BASE = 3000;
const DWORD EVENT_CRITICAL_BASE = 4000;

// ============================================================================
// Global State
// ============================================================================

// Service status
static SERVICE_STATUS g_ServiceStatus = {0};
static SERVICE_STATUS_HANDLE g_StatusHandle = NULL;
static HANDLE g_ServiceStopEvent = NULL;
static std::atomic<bool> g_ServiceRunning(false);
static std::atomic<bool> g_ServicePaused(false);
static std::atomic<int> g_RestartAttempts(0);

// Child process
static PROCESS_INFORMATION g_ChildProcessInfo = {0};
static HANDLE g_ChildProcessThread = NULL;
static std::atomic<bool> g_ChildProcessRunning(false);
static std::mutex g_ChildProcessMutex;

// Auto-restart
static std::atomic<bool> g_AutoRestartEnabled(true);
static std::chrono::steady_clock::time_point g_FirstRestartTime;

// Logging
static std::mutex g_LogMutex;
static HANDLE g_EventLog = NULL;

// ============================================================================
// Logging Helpers
// ============================================================================

/// Initialize the Windows Event Log.
static bool InitializeEventLog() {
    g_EventLog = RegisterEventSourceW(NULL, SERVICE_NAME);
    return (g_EventLog != NULL);
}

/// Report an event to the Windows Event Log.
static void ReportServiceEvent(WORD type, DWORD eventId, const wchar_t* message) {
    if (g_EventLog == NULL) {
        // Try to initialize
        InitializeEventLog();
        if (g_EventLog == NULL) return;
    }

    const wchar_t* strings[] = {message};

    ReportEventW(
        g_EventLog,
        type,
        0,          // category
        eventId,
        NULL,       // user sid
        1,          // string count
        0,          // data size
        strings,
        NULL        // raw data
    );
}

/// Log an informational message to the event log and debug output.
static void LogInfo(const wchar_t* format, ...) {
    wchar_t buffer[1024];
    va_list args;
    va_start(args, format);
    StringCchVPrintfW(buffer, 1024, format, args);
    va_end(args);

    OutputDebugStringW(buffer);
    OutputDebugStringW(L"\n");

    ReportServiceEvent(EVENTLOG_INFORMATION_TYPE, EVENT_INFO_BASE, buffer);
}

/// Log a warning message.
static void LogWarning(const wchar_t* format, ...) {
    wchar_t buffer[1024];
    va_list args;
    va_start(args, format);
    StringCchVPrintfW(buffer, 1024, format, args);
    va_end(args);

    OutputDebugStringW(buffer);
    OutputDebugStringW(L"\n");

    ReportServiceEvent(EVENTLOG_WARNING_TYPE, EVENT_WARNING_BASE, buffer);
}

/// Log an error message.
static void LogError(const wchar_t* format, ...) {
    wchar_t buffer[1024];
    va_list args;
    va_start(args, format);
    StringCchVPrintfW(buffer, 1024, format, args);
    va_end(args);

    OutputDebugStringW(buffer);
    OutputDebugStringW(L"\n");

    ReportServiceEvent(EVENTLOG_ERROR_TYPE, EVENT_ERROR_BASE, buffer);
}

/// Log a critical error message.
static void LogCritical(const wchar_t* format, ...) {
    wchar_t buffer[1024];
    va_list args;
    va_start(args, format);
    StringCchVPrintfW(buffer, 1024, format, args);
    va_end(args);

    OutputDebugStringW(buffer);
    OutputDebugStringW(L"\n");

    ReportServiceEvent(EVENTLOG_ERROR_TYPE, EVENT_CRITICAL_BASE, buffer);
}

/// Get the last error as a string.
static std::wstring GetLastErrorString(DWORD errorCode = 0) {
    if (errorCode == 0) {
        errorCode = GetLastError();
    }

    wchar_t* buffer = NULL;
    DWORD len = FormatMessageW(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL,
        errorCode,
        MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        (wchar_t*)&buffer,
        0,
        NULL
    );

    std::wstring result;
    if (buffer != NULL) {
        result = buffer;
        // Remove trailing CR/LF
        while (!result.empty() && (result.back() == L'\r' || result.back() == L'\n' || result.back() == L' ')) {
            result.pop_back();
        }
        LocalFree(buffer);
    } else {
        result = L"Unknown error";
    }

    return result;
}

// ============================================================================
// Registry Helpers
// ============================================================================

/// Read a string value from the registry.
static std::wstring RegistryGetString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, const wchar_t* defaultValue) {
    HKEY hKey = NULL;
    std::wstring result = defaultValue;

    LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_READ, &hKey);
    if (status == ERROR_SUCCESS) {
        wchar_t buffer[1024] = {0};
        DWORD bufferSize = sizeof(buffer);
        DWORD type = 0;

        status = RegQueryValueExW(hKey, valueName, NULL, &type, (LPBYTE)buffer, &bufferSize);
        if (status == ERROR_SUCCESS && type == REG_SZ) {
            result = buffer;
        }

        RegCloseKey(hKey);
    }

    return result;
}

/// Read a DWORD value from the registry.
static DWORD RegistryGetDword(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, DWORD defaultValue) {
    HKEY hKey = NULL;
    DWORD result = defaultValue;

    LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_READ, &hKey);
    if (status == ERROR_SUCCESS) {
        DWORD value = 0;
        DWORD valueSize = sizeof(value);
        DWORD type = 0;

        status = RegQueryValueExW(hKey, valueName, NULL, &type, (LPBYTE)&value, &valueSize);
        if (status == ERROR_SUCCESS && type == REG_DWORD) {
            result = value;
        }

        RegCloseKey(hKey);
    }

    return result;
}

/// Write a string value to the registry.
static bool RegistrySetString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, const wchar_t* value) {
    HKEY hKey = NULL;
    LONG status = RegCreateKeyExW(hRootKey, subKey, 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
    if (status != ERROR_SUCCESS) {
        return false;
    }

    status = RegSetValueExW(hKey, valueName, 0, REG_SZ, (const BYTE*)value, (DWORD)((wcslen(value) + 1) * sizeof(wchar_t)));
    RegCloseKey(hKey);

    return (status == ERROR_SUCCESS);
}

/// Write a DWORD value to the registry.
static bool RegistrySetDword(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, DWORD value) {
    HKEY hKey = NULL;
    LONG status = RegCreateKeyExW(hRootKey, subKey, 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
    if (status != ERROR_SUCCESS) {
        return false;
    }

    status = RegSetValueExW(hKey, valueName, 0, REG_DWORD, (const BYTE*)&value, sizeof(value));
    RegCloseKey(hKey);

    return (status == ERROR_SUCCESS);
}

/// Get the daemon executable path from registry or default.
static std::wstring GetDaemonExecutablePath() {
    std::wstring installDir = RegistryGetString(HKEY_LOCAL_MACHINE, REGISTRY_ROOT, L"InstallDir", DEFAULT_INSTALL_DIR);
    std::wstring daemonPath = installDir + L"\\bin\\ai-daemon.exe";

    // Check if the file exists
    DWORD attributes = GetFileAttributesW(daemonPath.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        // Fall back to default
        daemonPath = DEFAULT_DAEMON_EXE;
    }

    return daemonPath;
}

/// Get the config file path from registry or default.
static std::wstring GetConfigFilePath() {
    std::wstring installDir = RegistryGetString(HKEY_LOCAL_MACHINE, REGISTRY_ROOT, L"InstallDir", DEFAULT_INSTALL_DIR);
    std::wstring configPath = installDir + L"\\configs\\ai-daemon.toml";

    DWORD attributes = GetFileAttributesW(configPath.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        configPath = DEFAULT_CONFIG_PATH;
    }

    return configPath;
}

// ============================================================================
// Child Process Management
// ============================================================================

/// Build the command line for the daemon process.
static std::wstring BuildDaemonCommandLine() {
    std::wstring daemonPath = GetDaemonExecutablePath();
    std::wstring configPath = GetConfigFilePath();

    std::wstringstream cmdLine;
    cmdLine << L"\"" << daemonPath << L"\"";
    cmdLine << L" -c \"" << configPath << L"\"";

    // Add verbose flag if configured
    DWORD verbose = RegistryGetDword(HKEY_LOCAL_MACHINE, REGISTRY_SETTINGS, L"Verbose", 0);
    if (verbose) {
        cmdLine << L" -v";
    }

    return cmdLine.str();
}

/// Start the child daemon process.
static bool StartChildProcess() {
    std::lock_guard<std::mutex> lock(g_ChildProcessMutex);

    // If already running, don't start again
    if (g_ChildProcessRunning.load()) {
        LogInfo(L"Child process is already running");
        return true;
    }

    std::wstring cmdLine = BuildDaemonCommandLine();
    LogInfo(L"Starting daemon process: %s", cmdLine.c_str());

    // Set up process creation flags
    STARTUPINFOW si = {0};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    // Create the process
    BOOL success = CreateProcessW(
        NULL,                           // No application name (use command line)
        &cmdLine[0],                    // Command line
        NULL,                           // Process handle not inheritable
        NULL,                           // Thread handle not inheritable
        FALSE,                          // No handle inheritance
        CREATE_NO_WINDOW |              // No console window
        CREATE_UNICODE_ENVIRONMENT |
        HIGH_PRIORITY_CLASS,            // High priority for AI service
        NULL,                           // Use parent's environment
        NULL,                           // Use parent's current directory
        &si,
        &g_ChildProcessInfo
    );

    if (!success) {
        LogError(L"Failed to create daemon process: %s (error: %lu)",
            cmdLine.c_str(), GetLastError());
        return false;
    }

    g_ChildProcessRunning.store(true);
    g_RestartAttempts.store(0);
    g_FirstRestartTime = std::chrono::steady_clock::now();

    LogInfo(L"Daemon process started successfully (PID: %lu)",
        g_ChildProcessInfo.dwProcessId);

    // Ensure the process handle is not inherited
    SetHandleInformation(g_ChildProcessInfo.hProcess, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(g_ChildProcessInfo.hThread, HANDLE_FLAG_INHERIT, 0);

    return true;
}

/// Stop the child daemon process.
static bool StopChildProcess() {
    std::lock_guard<std::mutex> lock(g_ChildProcessMutex);

    if (!g_ChildProcessRunning.load()) {
        return true;
    }

    LogInfo(L"Stopping daemon process (PID: %lu)...", g_ChildProcessInfo.dwProcessId);

    // First, try graceful shutdown via named pipe
    // Send a shutdown message to the daemon
    HANDLE hPipe = CreateFileW(
        DAEMON_PIPE_NAME,
        GENERIC_WRITE,
        0,
        NULL,
        OPEN_EXISTING,
        0,
        NULL
    );

    if (hPipe != INVALID_HANDLE_VALUE) {
        // Send Ctrl-C-like signal by sending a close message
        const char* shutdownMsg = "{\"type\":\"Shutdown\"}\n";
        DWORD bytesWritten = 0;
        WriteFile(hPipe, shutdownMsg, (DWORD)strlen(shutdownMsg), &bytesWritten, NULL);
        CloseHandle(hPipe);

        // Wait for process to exit gracefully
        DWORD waitResult = WaitForSingleObject(g_ChildProcessInfo.hProcess, 15000);
        if (waitResult == WAIT_OBJECT_0) {
            LogInfo(L"Daemon process exited gracefully");
            g_ChildProcessRunning.store(false);
            CloseHandle(g_ChildProcessInfo.hProcess);
            CloseHandle(g_ChildProcessInfo.hThread);
            ZeroMemory(&g_ChildProcessInfo, sizeof(g_ChildProcessInfo));
            return true;
        }
    }

    // Graceful shutdown failed, terminate forcefully
    LogWarning(L"Forcing daemon process termination...");

    if (!TerminateProcess(g_ChildProcessInfo.hProcess, 0)) {
        LogError(L"Failed to terminate daemon process: %s", GetLastErrorString().c_str());
    }

    // Wait for process to exit
    WaitForSingleObject(g_ChildProcessInfo.hProcess, 5000);

    g_ChildProcessRunning.store(false);
    CloseHandle(g_ChildProcessInfo.hProcess);
    CloseHandle(g_ChildProcessInfo.hThread);
    ZeroMemory(&g_ChildProcessInfo, sizeof(g_ChildProcessInfo));

    LogInfo(L"Daemon process terminated");
    return true;
}

/// Check if the child process is still running.
static bool IsChildProcessRunning() {
    if (!g_ChildProcessRunning.load()) {
        return false;
    }

    DWORD exitCode = 0;
    if (!GetExitCodeProcess(g_ChildProcessInfo.hProcess, &exitCode)) {
        return false;
    }

    if (exitCode != STILL_ACTIVE) {
        g_ChildProcessRunning.store(false);
        return false;
    }

    return true;
}

/// Monitor the child process and restart if needed.
static DWORD WINAPI ChildProcessMonitorThread(LPVOID lpParam) {
    UNREFERENCED_PARAMETER(lpParam);

    LogInfo(L"Child process monitor thread started");

    while (g_ServiceRunning.load()) {
        if (g_ServicePaused.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(SERVICE_STATUS_CHECK_INTERVAL_MS));
            continue;
        }

        if (g_ChildProcessRunning.load()) {
            if (!IsChildProcessRunning()) {
                LogWarning(L"Daemon process has exited unexpectedly");

                // Check if auto-restart is enabled
                if (g_AutoRestartEnabled.load()) {
                    // Check restart limits
                    g_RestartAttempts.fetch_add(1);
                    int attempts = g_RestartAttempts.load();

                    // Reset counter if enough time has passed
                    auto now = std::chrono::steady_clock::now();
                    auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                        now - g_FirstRestartTime).count();
                    if (elapsed > RESTART_COUNTER_RESET_SECONDS) {
                        g_RestartAttempts.store(0);
                        g_FirstRestartTime = now;
                        attempts = 0;
                    }

                    if (attempts < MAX_RESTART_ATTEMPTS) {
                        LogInfo(L"Restarting daemon process (attempt %d/%d)...",
                            attempts, MAX_RESTART_ATTEMPTS);

                        // Wait before restart (with exponential backoff)
                        DWORD delay = RECOVERY_DELAYS[min(attempts - 1, RECOVERY_DELAY_COUNT - 1)];
                        std::this_thread::sleep_for(std::chrono::milliseconds(delay));

                        StartChildProcess();
                    } else {
                        LogCritical(L"Max restart attempts (%d) reached. Giving up.",
                            MAX_RESTART_ATTEMPTS);
                        g_AutoRestartEnabled.store(false);
                    }
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(CHILD_PROCESS_MONITOR_INTERVAL_MS));
    }

    LogInfo(L"Child process monitor thread stopped");
    return 0;
}

// ============================================================================
// Service Control Handler
// ============================================================================

/// Report the current service status to the SCM.
static void ReportServiceStatus(DWORD currentState, DWORD win32ExitCode, DWORD waitHint) {
    static DWORD checkPoint = 1;

    g_ServiceStatus.dwCurrentState = currentState;
    g_ServiceStatus.dwWin32ExitCode = win32ExitCode;
    g_ServiceStatus.dwWaitHint = waitHint;

    if (currentState == SERVICE_RUNNING) {
        g_ServiceStatus.dwControlsAccepted = SERVICE_ACCEPT_STOP |
            SERVICE_ACCEPT_PAUSE_CONTINUE |
            SERVICE_ACCEPT_SHUTDOWN |
            SERVICE_ACCEPT_POWEREVENT;
        g_ServiceStatus.dwCheckPoint = 0;
        g_ServiceStatus.dwWaitHint = 0;
    } else if (currentState == SERVICE_START_PENDING) {
        g_ServiceStatus.dwControlsAccepted = 0;
        g_ServiceStatus.dwCheckPoint = checkPoint++;
        g_ServiceStatus.dwWaitHint = waitHint;
    } else if (currentState == SERVICE_STOP_PENDING) {
        g_ServiceStatus.dwControlsAccepted = 0;
        g_ServiceStatus.dwCheckPoint = checkPoint++;
        g_ServiceStatus.dwWaitHint = waitHint;
    } else if (currentState == SERVICE_PAUSE_PENDING) {
        g_ServiceStatus.dwControlsAccepted = SERVICE_ACCEPT_STOP;
        g_ServiceStatus.dwCheckPoint = checkPoint++;
        g_ServiceStatus.dwWaitHint = waitHint;
    } else if (currentState == SERVICE_CONTINUE_PENDING) {
        g_ServiceStatus.dwControlsAccepted = SERVICE_ACCEPT_STOP;
        g_ServiceStatus.dwCheckPoint = checkPoint++;
        g_ServiceStatus.dwWaitHint = waitHint;
    } else {
        g_ServiceStatus.dwControlsAccepted = SERVICE_ACCEPT_STOP;
        g_ServiceStatus.dwCheckPoint = 0;
        g_ServiceStatus.dwWaitHint = 0;
    }

    SetServiceStatus(g_StatusHandle, &g_ServiceStatus);
}

/// Service control handler callback.
static DWORD WINAPI ServiceCtrlHandler(DWORD controlCode, DWORD eventType,
    LPVOID eventData, LPVOID context) {
    UNREFERENCED_PARAMETER(eventType);
    UNREFERENCED_PARAMETER(eventData);
    UNREFERENCED_PARAMETER(context);

    switch (controlCode) {
    case SERVICE_CONTROL_STOP:
        LogInfo(L"Service stop requested");
        ReportServiceStatus(SERVICE_STOP_PENDING, NO_ERROR, SERVICE_STOP_TIMEOUT_MS);
        g_ServiceRunning.store(false);
        SetEvent(g_ServiceStopEvent);
        return NO_ERROR;

    case SERVICE_CONTROL_PAUSE:
        LogInfo(L"Service pause requested");
        if (g_ServiceRunning.load() && !g_ServicePaused.load()) {
            ReportServiceStatus(SERVICE_PAUSE_PENDING, NO_ERROR, SERVICE_PAUSE_TIMEOUT_MS);
            g_ServicePaused.store(true);
            StopChildProcess();
            ReportServiceStatus(SERVICE_PAUSED, NO_ERROR, 0);
        }
        return NO_ERROR;

    case SERVICE_CONTROL_CONTINUE:
        LogInfo(L"Service continue requested");
        if (g_ServiceRunning.load() && g_ServicePaused.load()) {
            ReportServiceStatus(SERVICE_CONTINUE_PENDING, NO_ERROR, SERVICE_START_TIMEOUT_MS);
            g_ServicePaused.store(false);
            StartChildProcess();
            ReportServiceStatus(SERVICE_RUNNING, NO_ERROR, 0);
        }
        return NO_ERROR;

    case SERVICE_CONTROL_SHUTDOWN:
        LogInfo(L"System shutdown detected");
        g_ServiceRunning.store(false);
        g_AutoRestartEnabled.store(false); // Don't restart on shutdown
        SetEvent(g_ServiceStopEvent);
        return NO_ERROR;

    case SERVICE_CONTROL_INTERROGATE:
        SetServiceStatus(g_StatusHandle, &g_ServiceStatus);
        return NO_ERROR;

    case SERVICE_CONTROL_POWEREVENT:
        // Handle power events (no action needed for this service)
        return NO_ERROR;

    default:
        return ERROR_CALL_NOT_IMPLEMENTED;
    }
}

// ============================================================================
// Service Main
// ============================================================================

/// Service entry point - called by the SCM when starting the service.
static void WINAPI ServiceMain(DWORD argc, wchar_t* argv[]) {
    UNREFERENCED_PARAMETER(argc);
    UNREFERENCED_PARAMETER(argv);

    // Register the control handler
    g_StatusHandle = RegisterServiceCtrlHandlerExW(SERVICE_NAME, ServiceCtrlHandler, NULL);
    if (g_StatusHandle == NULL) {
        LogError(L"RegisterServiceCtrlHandlerExW failed: %s", GetLastErrorString().c_str());
        return;
    }

    // Initialize service status
    g_ServiceStatus.dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    g_ServiceStatus.dwServiceSpecificExitCode = 0;

    // Report initial status
    ReportServiceStatus(SERVICE_START_PENDING, NO_ERROR, SERVICE_START_TIMEOUT_MS);

    // Initialize event log
    InitializeEventLog();
    LogInfo(L"Ainos OS AI Daemon service starting...");

    // Create the stop event
    g_ServiceStopEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (g_ServiceStopEvent == NULL) {
        LogError(L"CreateEventW failed: %s", GetLastErrorString().c_str());
        ReportServiceStatus(SERVICE_STOPPED, GetLastError(), 0);
        return;
    }

    // Report running status
    ReportServiceStatus(SERVICE_RUNNING, NO_ERROR, 0);
    g_ServiceRunning.store(true);

    // Start the child process
    if (!StartChildProcess()) {
        LogCritical(L"Failed to start daemon process. Service will stop.");
        g_ServiceRunning.store(false);
        ReportServiceStatus(SERVICE_STOPPED, ERROR_SERVICE_SPECIFIC_ERROR, 0);
        CloseHandle(g_ServiceStopEvent);
        return;
    }

    // Start the child process monitor thread
    g_ChildProcessThread = CreateThread(
        NULL, 0,
        ChildProcessMonitorThread,
        NULL, 0, NULL
    );

    if (g_ChildProcessThread == NULL) {
        LogWarning(L"Failed to create monitor thread: %s", GetLastErrorString().c_str());
    }

    LogInfo(L"Ainos OS AI Daemon service started successfully");

    // Wait for stop signal
    while (g_ServiceRunning.load()) {
        DWORD waitResult = WaitForSingleObject(g_ServiceStopEvent, 1000);
        if (waitResult == WAIT_OBJECT_0) {
            break;
        }
    }

    // Service is stopping
    LogInfo(L"Ainos OS AI Daemon service stopping...");
    ReportServiceStatus(SERVICE_STOP_PENDING, NO_ERROR, SERVICE_STOP_TIMEOUT_MS);

    // Stop child process
    g_AutoRestartEnabled.store(false);
    StopChildProcess();

    // Wait for monitor thread
    if (g_ChildProcessThread != NULL) {
        WaitForSingleObject(g_ChildProcessThread, 5000);
        CloseHandle(g_ChildProcessThread);
    }

    // Clean up
    CloseHandle(g_ServiceStopEvent);

    // Clean up event log
    if (g_EventLog != NULL) {
        DeregisterEventSource(g_EventLog);
        g_EventLog = NULL;
    }

    // Report stopped status
    ReportServiceStatus(SERVICE_STOPPED, NO_ERROR, 0);

    LogInfo(L"Ainos OS AI Daemon service stopped");
}

// ============================================================================
// Service Installation / Uninstallation
// ============================================================================

/// Install the service with the Service Control Manager.
static bool InstallService() {
    LogInfo(L"Installing service '%s'...", SERVICE_NAME);

    // Open the SCM
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CREATE_SERVICE);
    if (scm == NULL) {
        DWORD error = GetLastError();
        LogError(L"Failed to open SCM: %s", GetLastErrorString(error).c_str());
        if (error == ERROR_ACCESS_DENIED) {
            wprintf(L"Access denied. Please run as Administrator.\n");
        }
        return false;
    }

    // Get the path to this executable
    wchar_t servicePath[MAX_PATH] = {0};
    GetModuleFileNameW(NULL, servicePath, MAX_PATH);

    std::wstring binaryPath = std::wstring(servicePath);

    // Create the service
    SC_HANDLE service = CreateServiceW(
        scm,
        SERVICE_NAME,
        SERVICE_DISPLAY_NAME,
        SERVICE_ALL_ACCESS,
        SERVICE_WIN32_OWN_PROCESS,
        SERVICE_AUTO_START,
        SERVICE_ERROR_NORMAL,
        binaryPath.c_str(),
        NULL,                               // load order group
        NULL,                               // tag ID
        L"",                                // dependencies (none)
        NULL,                               // local system account
        NULL                                // password
    );

    if (service == NULL) {
        DWORD error = GetLastError();
        if (error == ERROR_SERVICE_EXISTS) {
            LogWarning(L"Service already exists. Opening existing service...");
            // Open existing service for reconfiguration
            service = OpenServiceW(scm, SERVICE_NAME, SERVICE_ALL_ACCESS);
            if (service == NULL) {
                LogError(L"Failed to open existing service: %s", GetLastErrorString().c_str());
                CloseServiceHandle(scm);
                return false;
            }
        } else {
            LogError(L"Failed to create service: %s", GetLastErrorString(error).c_str());
            CloseServiceHandle(scm);
            return false;
        }
    }

    // Set service description
    SERVICE_DESCRIPTIONW description;
    description.lpDescription = const_cast<wchar_t*>(SERVICE_DESCRIPTION);
    ChangeServiceConfig2W(service, SERVICE_CONFIG_DESCRIPTION, &description);

    // Configure service recovery options
    SERVICE_FAILURE_ACTIONSW failureActions = {0};
    SERVICE_ACTION action1 = {SC_ACTION_RESTART, 30000}; // 30s
    SERVICE_ACTION action2 = {SC_ACTION_RESTART, 60000}; // 60s
    SERVICE_ACTION action3 = {SC_ACTION_RESTART, 120000}; // 120s
    SERVICE_ACTION action4 = {SC_ACTION_RUN_COMMAND, 0}; // final failure

    SC_ACTION actions[] = {action1, action2, action3, action4};

    failureActions.dwResetPeriod = INFINITE; // Never reset
    failureActions.lpCommand = const_cast<wchar_t*>(L"");
    failureActions.lpRebootMsg = NULL;
    failureActions.cActions = 4;
    failureActions.lpsaActions = actions;

    ChangeServiceConfig2W(service, SERVICE_CONFIG_FAILURE_ACTIONS, &failureActions);

    // Set failure actions flag for the first failure too
    SERVICE_FAILURE_ACTIONS_FLAG failureFlag;
    failureFlag.fFailureActionsOnNonCrashFailures = TRUE;
    ChangeServiceConfig2W(service, SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, &failureFlag);

    // Set preferred node (NUMA) - not critical
    SERVICE_PREFERRED_NODE_INFO preferredNode;
    preferredNode.uPreferredNode = 0;
    ChangeServiceConfig2W(service, SERVICE_CONFIG_PREFERRED_NODE, &preferredNode);

    // Set service SID type
    SERVICE_SID_INFO sidInfo;
    sidInfo.dwServiceSidType = SERVICE_SID_TYPE_UNRESTRICTED;
    ChangeServiceConfig2W(service, SERVICE_CONFIG_SERVICE_SID_INFO, &sidInfo);

    // Set service trigger info (optional)
    // SERVICE_TRIGGER_INFO triggerInfo = {0};
    // ChangeServiceConfig2W(service, SERVICE_CONFIG_TRIGGER_INFO, &triggerInfo);

    // Set launch protected
    SERVICE_LAUNCH_PROTECTED_INFO launchProtected;
    launchProtected.dwLaunchProtected = SERVICE_LAUNCH_PROTECTED_NONE;
    ChangeServiceConfig2W(service, SERVICE_CONFIG_LAUNCH_PROTECTED, &launchProtected);

    // Set required privileges
    SERVICE_REQUIRED_PRIVILEGES_INFOW requiredPrivileges;
    LPCWSTR privileges[] = {
        L"SeChangeNotifyPrivilege",
        L"SeCreateGlobalPrivilege",
        L"SeIncreaseQuotaPrivilege",
        L"SeAssignPrimaryTokenPrivilege",
        NULL
    };
    requiredPrivileges.pmszRequiredPrivileges = (LPCWSTR)privileges;
    // ChangeServiceConfig2W(service, SERVICE_CONFIG_REQUIRED_PRIVILEGES_INFO, &requiredPrivileges);

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    LogInfo(L"Service '%s' installed successfully.", SERVICE_NAME);
    wprintf(L"Service '%s' installed successfully.\n", SERVICE_DISPLAY_NAME);
    wprintf(L"Run 'sc start %s' to start the service.\n", SERVICE_NAME);

    return true;
}

/// Uninstall the service.
static bool UninstallService() {
    LogInfo(L"Uninstalling service '%s'...", SERVICE_NAME);

    // Open the SCM
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        LogError(L"Failed to open SCM: %s", GetLastErrorString().c_str());
        wprintf(L"Access denied. Please run as Administrator.\n");
        return false;
    }

    // Open the service
    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_STOP | SERVICE_QUERY_STATUS | DELETE);
    if (service == NULL) {
        DWORD error = GetLastError();
        if (error == ERROR_SERVICE_DOES_NOT_EXIST) {
            LogWarning(L"Service does not exist.");
            wprintf(L"Service '%s' is not installed.\n", SERVICE_NAME);
            CloseServiceHandle(scm);
            return true;
        }
        LogError(L"Failed to open service: %s", GetLastErrorString(error).c_str());
        CloseServiceHandle(scm);
        return false;
    }

    // Try to stop the service first
    SERVICE_STATUS status;
    if (ControlService(service, SERVICE_CONTROL_STOP, &status)) {
        LogInfo(L"Waiting for service to stop...");
        while (QueryServiceStatus(service, &status)) {
            if (status.dwCurrentState == SERVICE_STOPPED) {
                break;
            }
            Sleep(1000);
        }
        LogInfo(L"Service stopped successfully.");
    }

    // Delete the service
    if (!DeleteService(service)) {
        DWORD error = GetLastError();
        LogError(L"Failed to delete service: %s", GetLastErrorString(error).c_str());
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return false;
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    LogInfo(L"Service '%s' uninstalled successfully.", SERVICE_NAME);
    wprintf(L"Service '%s' uninstalled successfully.\n", SERVICE_DISPLAY_NAME);

    return true;
}

// ============================================================================
// Manual Start/Stop
// ============================================================================

/// Start the service manually.
static bool StartServiceManually() {
    LogInfo(L"Starting service '%s' manually...", SERVICE_NAME);

    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        LogError(L"Failed to open SCM: %s", GetLastErrorString().c_str());
        wprintf(L"Access denied. Please run as Administrator.\n");
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_START | SERVICE_QUERY_STATUS);
    if (service == NULL) {
        LogError(L"Failed to open service: %s", GetLastErrorString().c_str());
        wprintf(L"Service '%s' is not installed.\n", SERVICE_NAME);
        CloseServiceHandle(scm);
        return false;
    }

    // Query current status
    SERVICE_STATUS status;
    if (QueryServiceStatus(service, &status)) {
        if (status.dwCurrentState == SERVICE_RUNNING) {
            LogInfo(L"Service is already running.");
            wprintf(L"Service '%s' is already running.\n", SERVICE_DISPLAY_NAME);
            CloseServiceHandle(service);
            CloseServiceHandle(scm);
            return true;
        }
    }

    // Start the service
    if (!StartServiceW(service, 0, NULL)) {
        DWORD error = GetLastError();
        LogError(L"Failed to start service: %s", GetLastErrorString(error).c_str());
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return false;
    }

    // Wait for service to start
    LogInfo(L"Waiting for service to start...");
    while (QueryServiceStatus(service, &status)) {
        if (status.dwCurrentState == SERVICE_RUNNING) {
            break;
        }
        if (status.dwCurrentState == SERVICE_STOPPED) {
            LogError(L"Service failed to start.");
            CloseServiceHandle(service);
            CloseServiceHandle(scm);
            return false;
        }
        Sleep(1000);
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    LogInfo(L"Service started successfully.");
    wprintf(L"Service '%s' started successfully.\n", SERVICE_DISPLAY_NAME);

    return true;
}

/// Stop the service manually.
static bool StopServiceManually() {
    LogInfo(L"Stopping service '%s' manually...", SERVICE_NAME);

    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        LogError(L"Failed to open SCM: %s", GetLastErrorString().c_str());
        wprintf(L"Access denied. Please run as Administrator.\n");
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_STOP | SERVICE_QUERY_STATUS);
    if (service == NULL) {
        LogError(L"Failed to open service: %s", GetLastErrorString().c_str());
        wprintf(L"Service '%s' is not installed.\n", SERVICE_NAME);
        CloseServiceHandle(scm);
        return false;
    }

    SERVICE_STATUS status;
    if (!ControlService(service, SERVICE_CONTROL_STOP, &status)) {
        DWORD error = GetLastError();
        if (error == ERROR_SERVICE_NOT_ACTIVE) {
            LogInfo(L"Service is not running.");
            wprintf(L"Service '%s' is not running.\n", SERVICE_DISPLAY_NAME);
            CloseServiceHandle(service);
            CloseServiceHandle(scm);
            return true;
        }
        LogError(L"Failed to stop service: %s", GetLastErrorString(error).c_str());
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return false;
    }

    // Wait for service to stop
    LogInfo(L"Waiting for service to stop...");
    while (QueryServiceStatus(service, &status)) {
        if (status.dwCurrentState == SERVICE_STOPPED) {
            break;
        }
        Sleep(1000);
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    LogInfo(L"Service stopped successfully.");
    wprintf(L"Service '%s' stopped successfully.\n", SERVICE_DISPLAY_NAME);

    return true;
}

/// Query the service status.
static bool QueryServiceStatusManually() {
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        wprintf(L"Failed to open SCM (access denied).\n");
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_QUERY_STATUS);
    if (service == NULL) {
        wprintf(L"Service '%s' is not installed.\n", SERVICE_NAME);
        CloseServiceHandle(scm);
        return false;
    }

    SERVICE_STATUS status;
    if (QueryServiceStatus(service, &status)) {
        const wchar_t* stateText = L"Unknown";
        switch (status.dwCurrentState) {
        case SERVICE_STOPPED:          stateText = L"Stopped"; break;
        case SERVICE_START_PENDING:    stateText = L"Start Pending"; break;
        case SERVICE_STOP_PENDING:     stateText = L"Stop Pending"; break;
        case SERVICE_RUNNING:          stateText = L"Running"; break;
        case SERVICE_CONTINUE_PENDING: stateText = L"Continue Pending"; break;
        case SERVICE_PAUSE_PENDING:    stateText = L"Pause Pending"; break;
        case SERVICE_PAUSED:           stateText = L"Paused"; break;
        }

        wprintf(L"Service '%s': %s\n", SERVICE_DISPLAY_NAME, stateText);
        wprintf(L"  Process ID: %lu\n", status.dwProcessId);
        wprintf(L"  Exit Code: %lu\n", status.dwWin32ExitCode);
        wprintf(L"  Service Specific Code: %lu\n", status.dwServiceSpecificExitCode);
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    return true;
}

// ============================================================================
// Main Entry Point
// ============================================================================

/// Display command-line usage information.
static void ShowUsage() {
    wprintf(L"Ainos OS AI Daemon Service Manager\n");
    wprintf(L"\n");
    wprintf(L"Usage:\n");
    wprintf(L"  ainos_service.exe --install         Install the service\n");
    wprintf(L"  ainos_service.exe --uninstall       Uninstall the service\n");
    wprintf(L"  ainos_service.exe --start           Start the service manually\n");
    wprintf(L"  ainos_service.exe --stop            Stop the service manually\n");
    wprintf(L"  ainos_service.exe --status          Query service status\n");
    wprintf(L"  ainos_service.exe (no args)         Run as a service (SCM)\n");
    wprintf(L"\n");
    wprintf(L"Service name: %s\n", SERVICE_NAME);
    wprintf(L"Display name: %s\n", SERVICE_DISPLAY_NAME);
}

/// Parse command-line arguments and dispatch.
int wmain(int argc, wchar_t* argv[]) {
    // Initialize logging
    InitializeEventLog();

    // Check for command-line arguments
    if (argc > 1) {
        std::wstring arg = argv[1];

        if (arg == L"--install" || arg == L"-i" || arg == L"/install") {
            // Install the service
            bool success = InstallService();
            return success ? 0 : 1;
        }
        else if (arg == L"--uninstall" || arg == L"-u" || arg == L"/uninstall") {
            // Uninstall the service
            bool success = UninstallService();
            return success ? 0 : 1;
        }
        else if (arg == L"--start" || arg == L"-s" || arg == L"/start") {
            // Start the service manually
            bool success = StartServiceManually();
            return success ? 0 : 1;
        }
        else if (arg == L"--stop" || arg == L"-t" || arg == L"/stop") {
            // Stop the service manually
            bool success = StopServiceManually();
            return success ? 0 : 1;
        }
        else if (arg == L"--status" || arg == L"-q" || arg == L"/status") {
            // Query service status
            QueryServiceStatusManually();
            return 0;
        }
        else if (arg == L"--help" || arg == L"-h" || arg == L"/?" || arg == L"/help") {
            ShowUsage();
            return 0;
        }
        else {
            wprintf(L"Unknown argument: %s\n", arg.c_str());
            ShowUsage();
            return 1;
        }
    }

    // No arguments - run as a service
    LogInfo(L"Running as a service...");

    SERVICE_TABLE_ENTRYW serviceTable[] = {
        {const_cast<wchar_t*>(SERVICE_NAME), (LPSERVICE_MAIN_FUNCTIONW)ServiceMain},
        {NULL, NULL}
    };

    if (!StartServiceCtrlDispatcherW(serviceTable)) {
        DWORD error = GetLastError();
        if (error == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT) {
            // This is expected when running from command line
            LogWarning(L"Not running as a service (SCM not detected).");
            wprintf(L"This program is meant to run as a Windows service.\n");
            wprintf(L"Use --install, --start, --stop, or --uninstall to manage the service.\n");
            ShowUsage();
        } else {
            LogError(L"StartServiceCtrlDispatcherW failed: %s", GetLastErrorString(error).c_str());
        }
        return 1;
    }

    return 0;
}