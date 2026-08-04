// Ainos OS - Event Tracing for Windows (ETW) Provider
//
// This file implements the ETW logging provider for AinosOS.
// It provides structured event tracing with info, warning, error, and critical levels.
//
// Provider GUID: {A1N0S-0000-0000-0000-000000000001}
// Provider Name: AinosOS-AI-Daemon
//
// ETW events can be captured with:
//   xperf -start AinosSession -on A1N0S-0000-0000-0000-000000000001
//   ... run workload ...
//   xperf -stop AinosSession
//   xperf -merge AinosSession.etl output.etl
//
// Or with logman:
//   logman create trace AinosOS -o c:\temp\ainos.etl -p "{A1N0S-0000-0000-0000-000000000001}" 0xFFFFFFFF 255
//   logman start AinosOS
//   logman stop AinosOS

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <evntprov.h>
#include <evntrace.h>
#include <tchar.h>
#include <strsafe.h>
#include <stdlib.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <atomic>
#include <chrono>
#include <cwchar>
#include <cstring>
#include <ctime>
#include <iomanip>

// ============================================================================
// Constants
// ============================================================================

// Provider GUID: {A1N0S-0000-0000-0000-000000000001}
const GUID PROVIDER_GUID = {
    0xA1N0S000, 0x0000, 0x0000, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01}
};

// Provider name
const wchar_t* PROVIDER_NAME = L"AinosOS-AI-Daemon";

// ETW event levels (matching Windows standards)
const UCHAR ETW_LEVEL_ALWAYS      = 0x00;
const UCHAR ETW_LEVEL_CRITICAL    = 0x01;
const UCHAR ETW_LEVEL_ERROR       = 0x02;
const UCHAR ETW_LEVEL_WARNING     = 0x03;
const UCHAR ETW_LEVEL_INFO        = 0x04;
const UCHAR ETW_LEVEL_VERBOSE     = 0x05;

// ETW event keywords (bitmask)
const ULONGLONG KEYWORD_DAEMON         = 0x0000000000000001;
const ULONGLONG KEYWORD_INFERENCE      = 0x0000000000000002;
const ULONGLONG KEYWORD_MODEL          = 0x0000000000000004;
const ULONGLONG KEYWORD_CONTEXT        = 0x0000000000000008;
const ULONGLONG KEYWORD_AUTH           = 0x0000000000000010;
const ULONGLONG KEYWORD_NETWORK        = 0x0000000000000020;
const ULONGLONG KEYWORD_PERFORMANCE    = 0x0000000000000040;
const ULONGLONG KEYWORD_SECURITY       = 0x0000000000000080;
const ULONGLONG KEYWORD_ALL            = 0xFFFFFFFFFFFFFFFF;

// Event IDs
const DWORD EVENT_ID_DAEMON_START      = 1000;
const DWORD EVENT_ID_DAEMON_STOP       = 1001;
const DWORD EVENT_ID_DAEMON_CRASH      = 1002;
const DWORD EVENT_ID_DAEMON_RESTART    = 1003;
const DWORD EVENT_ID_INFERENCE_START   = 2000;
const DWORD EVENT_ID_INFERENCE_END     = 2001;
const DWORD EVENT_ID_INFERENCE_ERROR   = 2002;
const DWORD EVENT_ID_MODEL_LOAD        = 3000;
const DWORD EVENT_ID_MODEL_UNLOAD      = 3001;
const DWORD EVENT_ID_MODEL_ERROR       = 3002;
const DWORD EVENT_ID_AUTH_SUCCESS      = 4000;
const DWORD EVENT_ID_AUTH_FAILURE      = 4001;
const DWORD EVENT_ID_AUTH_RATELIMIT    = 4002;
const DWORD EVENT_ID_NETWORK_STATUS    = 5000;
const DWORD EVENT_ID_CONFIG_CHANGE     = 6000;
const DWORD EVENT_ID_PERFORMANCE       = 7000;
const DWORD EVENT_ID_ERROR_GENERIC     = 9000;
const DWORD EVENT_ID_CRITICAL          = 9999;

// Max event data size (ETW limit is 64KB minus headers)
const size_t MAX_EVENT_DATA_SIZE = 60000;

// ============================================================================
// AinosEtwProvider Class
// ============================================================================

class AinosEtwProvider {
public:
    /// Initialize the ETW provider.
    /// Registers the provider with the Windows ETW system.
    /// Returns true if successful, false otherwise.
    static bool Initialize() {
        if (s_Initialized.load()) {
            return true;
        }

        // Register the ETW provider
        UINT32 result = EventRegister(
            &PROVIDER_GUID,
            nullptr,   // EnableCallback (optional)
            nullptr,   // CallbackContext
            &s_ProviderHandle
        );

        if (result != ERROR_SUCCESS) {
            s_ProviderHandle = NULL;
            return false;
        }

        s_Initialized.store(true);
        return true;
    }

    /// Shutdown the ETW provider.
    /// Unregisters the provider and flushes any pending events.
    static void Shutdown() {
        if (!s_Initialized.load()) {
            return;
        }

        EventUnregister(s_ProviderHandle);
        s_ProviderHandle = NULL;
        s_Initialized.store(false);
    }

    /// Check if the provider is enabled (registered).
    static bool IsEnabled() {
        return s_Initialized.load() && s_ProviderHandle != NULL;
    }

    /// Check if a specific level/keyword is enabled for this provider.
    static bool IsEnabled(UCHAR level, ULONGLONG keyword) {
        if (!IsEnabled()) return false;
        return EventEnabled(s_ProviderHandle, level, keyword) != FALSE;
    }

    // ========================================================================
    // Info Events
    // ========================================================================

    /// Write an informational event with an ANSI string message.
    static bool WriteInfo(const char* message, const char* component = nullptr) {
        return WriteEvent(ETW_LEVEL_INFO, KEYWORD_DAEMON, EVENT_ID_DAEMON_START,
            message, component);
    }

    /// Write an informational event with a wide string message.
    static bool WriteInfo(const wchar_t* message, const wchar_t* component = nullptr) {
        return WriteEvent(ETW_LEVEL_INFO, KEYWORD_DAEMON, EVENT_ID_DAEMON_START,
            message, component);
    }

    // ========================================================================
    // Warning Events
    // ========================================================================

    /// Write a warning event with an ANSI string message.
    static bool WriteWarning(const char* message, const char* component = nullptr) {
        return WriteEvent(ETW_LEVEL_WARNING, KEYWORD_DAEMON, EVENT_ID_DAEMON_RESTART,
            message, component);
    }

    /// Write a warning event with a wide string message.
    static bool WriteWarning(const wchar_t* message, const wchar_t* component = nullptr) {
        return WriteEvent(ETW_LEVEL_WARNING, KEYWORD_DAEMON, EVENT_ID_DAEMON_RESTART,
            message, component);
    }

    // ========================================================================
    // Error Events
    // ========================================================================

    /// Write an error event with an ANSI string message.
    static bool WriteError(const char* message, const char* component = nullptr) {
        return WriteEvent(ETW_LEVEL_ERROR, KEYWORD_DAEMON, EVENT_ID_ERROR_GENERIC,
            message, component);
    }

    /// Write an error event with a wide string message.
    static bool WriteError(const wchar_t* message, const wchar_t* component = nullptr) {
        return WriteEvent(ETW_LEVEL_ERROR, KEYWORD_DAEMON, EVENT_ID_ERROR_GENERIC,
            message, component);
    }

    // ========================================================================
    // Critical Events
    // ========================================================================

    /// Write a critical event with an ANSI string message.
    static bool WriteCritical(const char* message, const char* component = nullptr) {
        return WriteEvent(ETW_LEVEL_CRITICAL, KEYWORD_DAEMON, EVENT_ID_CRITICAL,
            message, component);
    }

    /// Write a critical event with a wide string message.
    static bool WriteCritical(const wchar_t* message, const wchar_t* component = nullptr) {
        return WriteEvent(ETW_LEVEL_CRITICAL, KEYWORD_DAEMON, EVENT_ID_CRITICAL,
            message, component);
    }

    // ========================================================================
    // Structured Event Writing
    // ========================================================================

    /// Write a structured JSON event.
    /// The jsonPayload should be a valid JSON string.
    /// level: ETW event level (ETW_LEVEL_INFO, etc.)
    /// opcode: Event opcode (0 = default)
    static bool WriteJsonEvent(const char* jsonPayload, UCHAR level, UCHAR opcode = 0) {
        if (!IsEnabled()) return false;

        // Build the event descriptor
        EVENT_DESCRIPTOR descriptor;
        EventDescCreate(&descriptor, EVENT_ID_DAEMON_START, 0x00, 0x00, level, opcode, KEYWORD_DAEMON);

        size_t payloadLen = strlen(jsonPayload);
        if (payloadLen > MAX_EVENT_DATA_SIZE) {
            payloadLen = MAX_EVENT_DATA_SIZE;
        }

        // Write the event with the JSON payload as raw data
        UINT32 result = EventWrite(
            s_ProviderHandle,
            &descriptor,
            1,              // UserDataCount
            (EVENT_DATA_DESCRIPTOR*)&(EVENT_DATA_DESCRIPTOR{
                (ULONGLONG)jsonPayload,
                (ULONG)payloadLen
            })
        );

        return (result == ERROR_SUCCESS);
    }

    /// Write a performance counter event.
    static bool WritePerformanceCounter(const char* counterName, double value, const char* unit = nullptr) {
        if (!IsEnabled()) return false;

        // Build a JSON payload for the performance counter
        char buffer[1024];
        if (unit != nullptr) {
            snprintf(buffer, sizeof(buffer),
                "{\"type\":\"performance\",\"counter\":\"%s\",\"value\":%f,\"unit\":\"%s\",\"timestamp\":%lld}",
                counterName, value, unit,
                (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count());
        } else {
            snprintf(buffer, sizeof(buffer),
                "{\"type\":\"performance\",\"counter\":\"%s\",\"value\":%f,\"timestamp\":%lld}",
                counterName, value,
                (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count());
        }

        EVENT_DESCRIPTOR descriptor;
        EventDescCreate(&descriptor, EVENT_ID_PERFORMANCE, 0x00, 0x00,
            ETW_LEVEL_INFO, 0, KEYWORD_PERFORMANCE);

        UINT32 result = EventWrite(
            s_ProviderHandle,
            &descriptor,
            1,
            (EVENT_DATA_DESCRIPTOR*)&(EVENT_DATA_DESCRIPTOR{
                (ULONGLONG)buffer,
                (ULONG)strlen(buffer)
            })
        );

        return (result == ERROR_SUCCESS);
    }

    /// Write a daemon lifecycle event.
    static bool WriteDaemonEvent(const char* eventType, const char* detail = nullptr) {
        if (!IsEnabled()) return false;

        char buffer[2048];
        if (detail != nullptr) {
            snprintf(buffer, sizeof(buffer),
                "{\"type\":\"daemon\",\"event\":\"%s\",\"detail\":\"%s\",\"timestamp\":%lld}",
                eventType, detail,
                (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count());
        } else {
            snprintf(buffer, sizeof(buffer),
                "{\"type\":\"daemon\",\"event\":\"%s\",\"timestamp\":%lld}",
                eventType,
                (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count());
        }

        DWORD eventId = EVENT_ID_DAEMON_START;
        UCHAR level = ETW_LEVEL_INFO;

        if (strcmp(eventType, "start") == 0) {
            eventId = EVENT_ID_DAEMON_START;
            level = ETW_LEVEL_INFO;
        } else if (strcmp(eventType, "stop") == 0) {
            eventId = EVENT_ID_DAEMON_STOP;
            level = ETW_LEVEL_INFO;
        } else if (strcmp(eventType, "crash") == 0) {
            eventId = EVENT_ID_DAEMON_CRASH;
            level = ETW_LEVEL_CRITICAL;
        } else if (strcmp(eventType, "restart") == 0) {
            eventId = EVENT_ID_DAEMON_RESTART;
            level = ETW_LEVEL_WARNING;
        }

        EVENT_DESCRIPTOR descriptor;
        EventDescCreate(&descriptor, eventId, 0x00, 0x00, level, 0, KEYWORD_DAEMON);

        UINT32 result = EventWrite(
            s_ProviderHandle,
            &descriptor,
            1,
            (EVENT_DATA_DESCRIPTOR*)&(EVENT_DATA_DESCRIPTOR{
                (ULONGLONG)buffer,
                (ULONG)strlen(buffer)
            })
        );

        return (result == ERROR_SUCCESS);
    }

    /// Flush any pending events.
    static void Flush() {
        if (!IsEnabled()) return;
        EventWrite(s_ProviderHandle, nullptr, 0, nullptr);
    }

private:
    // ========================================================================
    // Private Data
    // ========================================================================

    static REGHANDLE s_ProviderHandle;
    static std::atomic<bool> s_Initialized;
    static std::mutex s_Mutex;

    // ========================================================================
    // Private Helper Methods
    // ========================================================================

    /// Write an event with an ANSI string message.
    static bool WriteEvent(UCHAR level, ULONGLONG keyword, DWORD eventId,
        const char* message, const char* component) {
        if (!IsEnabled()) return false;

        // Build JSON payload
        char buffer[4096];
        DWORD timestamp = (DWORD)std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();

        if (component != nullptr && component[0] != '\0') {
            snprintf(buffer, sizeof(buffer),
                "{\"level\":%u,\"eventId\":%lu,\"component\":\"%s\",\"message\":\"%s\",\"timestamp\":%lu}",
                level, eventId, component, EscapeJsonString(message).c_str(), timestamp);
        } else {
            snprintf(buffer, sizeof(buffer),
                "{\"level\":%u,\"eventId\":%lu,\"message\":\"%s\",\"timestamp\":%lu}",
                level, eventId, EscapeJsonString(message).c_str(), timestamp);
        }

        EVENT_DESCRIPTOR descriptor;
        EventDescCreate(&descriptor, eventId, 0x00, 0x00, level, 0, keyword);

        UINT32 result = EventWrite(
            s_ProviderHandle,
            &descriptor,
            1,
            (EVENT_DATA_DESCRIPTOR*)&(EVENT_DATA_DESCRIPTOR{
                (ULONGLONG)buffer,
                (ULONG)strlen(buffer)
            })
        );

        return (result == ERROR_SUCCESS);
    }

    /// Write an event with a wide string message.
    static bool WriteEvent(UCHAR level, ULONGLONG keyword, DWORD eventId,
        const wchar_t* message, const wchar_t* component) {
        // Convert wide strings to UTF-8
        std::string msgUtf8 = WideToUtf8(message);
        std::string compUtf8;
        if (component != nullptr) {
            compUtf8 = WideToUtf8(component);
        }

        return WriteEvent(level, keyword, eventId,
            msgUtf8.c_str(),
            compUtf8.empty() ? nullptr : compUtf8.c_str());
    }

    /// Escape a string for JSON output.
    static std::string EscapeJsonString(const char* input) {
        std::string result;
        result.reserve(strlen(input) + 16);

        for (const char* p = input; *p; p++) {
            unsigned char c = (unsigned char)*p;
            switch (c) {
            case '"':  result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\b': result += "\\b"; break;
            case '\f': result += "\\f"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    result += buf;
                } else {
                    result += c;
                }
                break;
            }
        }

        return result;
    }

    /// Convert a wide string to UTF-8.
    static std::string WideToUtf8(const wchar_t* wide) {
        if (wide == nullptr || wide[0] == L'\0') return std::string();

        int len = WideCharToMultiByte(
            CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr
        );

        if (len <= 0) return std::string();

        std::vector<char> buffer(len);
        WideCharToMultiByte(
            CP_UTF8, 0, wide, -1, buffer.data(), len, nullptr, nullptr
        );

        // The result includes the null terminator; remove it
        return std::string(buffer.data(), len - 1);
    }
};

// Static member initialization
REGHANDLE AinosEtwProvider::s_ProviderHandle = NULL;
std::atomic<bool> AinosEtwProvider::s_Initialized(false);
std::mutex AinosEtwProvider::s_Mutex;

// ============================================================================
// AinosEventLog Class (Windows Event Log)
// ============================================================================

class AinosEventLog {
public:
    /// Initialize the event log with a source name.
    /// Creates the event source if it doesn't exist.
    static bool Initialize(const wchar_t* sourceName = L"AinosOS") {
        std::lock_guard<std::mutex> lock(s_Mutex);

        if (s_EventLog != NULL) {
            return true;
        }

        // Register the event source
        s_EventLog = RegisterEventSourceW(NULL, sourceName);
        if (s_EventLog == NULL) {
            // Try to create the event source in the registry
            if (!CreateEventSource(sourceName)) {
                return false;
            }
            // Retry
            s_EventLog = RegisterEventSourceW(NULL, sourceName);
        }

        if (s_EventLog != NULL) {
            if (s_SourceName) free(s_SourceName);
            s_SourceName = _wcsdup(sourceName);
        }

        return (s_EventLog != NULL);
    }

    /// Shutdown the event log.
    static void Shutdown() {
        std::lock_guard<std::mutex> lock(s_Mutex);

        if (s_EventLog != NULL) {
            DeregisterEventSource(s_EventLog);
            s_EventLog = NULL;
        }

        if (s_SourceName != NULL) {
            free(s_SourceName);
            s_SourceName = NULL;
        }
    }

    /// Report an informational event.
    static void ReportInfo(const wchar_t* message, DWORD eventId = 1000) {
        ReportEvent(EVENTLOG_INFORMATION_TYPE, eventId, message);
    }

    /// Report a warning event.
    static void ReportWarning(const wchar_t* message, DWORD eventId = 1001) {
        ReportEvent(EVENTLOG_WARNING_TYPE, eventId, message);
    }

    /// Report an error event.
    static void ReportError(const wchar_t* message, DWORD eventId = 1002) {
        ReportEvent(EVENTLOG_ERROR_TYPE, eventId, message);
    }

    /// Report a critical error event.
    static void ReportCritical(const wchar_t* message, DWORD eventId = 1003) {
        ReportEvent(EVENTLOG_ERROR_TYPE, eventId, message);
    }

    /// Report a structured event with additional data.
    static void ReportStructured(WORD type, DWORD eventId, const wchar_t* message,
        const wchar_t* data = nullptr) {
        std::lock_guard<std::mutex> lock(s_Mutex);

        if (s_EventLog == NULL) {
            return;
        }

        const wchar_t* strings[] = { message, data };

        ReportEventW(
            s_EventLog,
            type,
            0,          // category
            eventId,
            NULL,       // user sid
            data ? 2 : 1, // string count
            0,          // data size
            strings,
            NULL        // raw data
        );
    }

private:
    static HANDLE s_EventLog;
    static wchar_t* s_SourceName;
    static std::mutex s_Mutex;

    /// Report an event to the Windows Event Log.
    static void ReportEvent(WORD type, DWORD eventId, const wchar_t* message) {
        std::lock_guard<std::mutex> lock(s_Mutex);

        if (s_EventLog == NULL) {
            return;
        }

        const wchar_t* strings[] = { message };

        ReportEventW(
            s_EventLog,
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

    /// Create the event source in the registry if it doesn't exist.
    /// This allows the event log to display messages properly.
    static bool CreateEventSource(const wchar_t* sourceName) {
        HKEY hKey = NULL;
        wchar_t keyPath[512];

        // Build the event source registry path
        swprintf_s(keyPath, 512,
            L"SYSTEM\\CurrentControlSet\\Services\\EventLog\\Application\\%s",
            sourceName);

        LONG status = RegCreateKeyExW(
            HKEY_LOCAL_MACHINE,
            keyPath,
            0, NULL,
            REG_OPTION_NON_VOLATILE,
            KEY_WRITE,
            NULL,
            &hKey,
            NULL
        );

        if (status != ERROR_SUCCESS) {
            return false;
        }

        // Set the EventMessageFile to this executable (or a message DLL)
        wchar_t modulePath[MAX_PATH];
        GetModuleFileNameW(NULL, modulePath, MAX_PATH);

        RegSetValueExW(hKey, L"EventMessageFile", 0, REG_SZ,
            (const BYTE*)modulePath,
            (DWORD)((wcslen(modulePath) + 1) * sizeof(wchar_t)));

        // Set the types supported
        DWORD typesSupported = EVENTLOG_INFORMATION_TYPE |
            EVENTLOG_WARNING_TYPE |
            EVENTLOG_ERROR_TYPE;
        RegSetValueExW(hKey, L"TypesSupported", 0, REG_DWORD,
            (const BYTE*)&typesSupported, sizeof(typesSupported));

        RegCloseKey(hKey);
        return true;
    }
};

// Static member initialization
HANDLE AinosEventLog::s_EventLog = NULL;
wchar_t* AinosEventLog::s_SourceName = NULL;
std::mutex AinosEventLog::s_Mutex;

// ============================================================================
// Console Application Entry Point
// ============================================================================

/// Display usage information.
static void ShowUsage() {
    wprintf(L"Ainos OS ETW Logging Provider\n");
    wprintf(L"\n");
    wprintf(L"Usage:\n");
    wprintf(L"  ainos_etw.exe --init          Initialize the ETW provider\n");
    wprintf(L"  ainos_etw.exe --test          Run a self-test of all event levels\n");
    wprintf(L"  ainos_etw.exe --info <msg>    Write an info event\n");
    wprintf(L"  ainos_etw.exe --warn <msg>    Write a warning event\n");
    wprintf(L"  ainos_etw.exe --error <msg>   Write an error event\n");
    wprintf(L"  ainos_etw.exe --critical <msg> Write a critical event\n");
    wprintf(L"\n");
    wprintf(L"Provider GUID: {A1N0S-0000-0000-0000-000000000001}\n");
    wprintf(L"Provider Name: %s\n", PROVIDER_NAME);
    wprintf(L"\n");
    wprintf(L"To capture events:\n");
    wprintf(L"  logman create trace AinosOS -o c:\\temp\\ainos.etl -p \"{A1N0S-0000-0000-0000-000000000001}\" 0xFFFFFFFF 255\n");
    wprintf(L"  logman start AinosOS\n");
    wprintf(L"  logman stop AinosOS\n");
}

/// Run a self-test of all event levels.
static void RunSelfTest() {
    wprintf(L"Ainos ETW Provider Self-Test\n");
    wprintf(L"============================\n");

    if (!AinosEtwProvider::Initialize()) {
        wprintf(L"FAILED to initialize ETW provider.\n");
        return;
    }

    wprintf(L"ETW provider initialized successfully.\n");
    wprintf(L"Provider handle: 0x%p\n", (void*)AinosEtwProvider::IsEnabled());

    // Write test events
    wprintf(L"\nWriting test events...\n");

    AinosEtwProvider::WriteInfo(L"ETW self-test: info event", L"self-test");
    wprintf(L"  Info event written.\n");

    AinosEtwProvider::WriteWarning(L"ETW self-test: warning event", L"self-test");
    wprintf(L"  Warning event written.\n");

    AinosEtwProvider::WriteError(L"ETW self-test: error event", L"self-test");
    wprintf(L"  Error event written.\n");

    AinosEtwProvider::WriteCritical(L"ETW self-test: critical event", L"self-test");
    wprintf(L"  Critical event written.\n");

    AinosEtwProvider::WriteDaemonEvent("start", "ETW self-test");
    wprintf(L"  Daemon start event written.\n");

    AinosEtwProvider::WritePerformanceCounter("test.counter", 42.0, "units");
    wprintf(L"  Performance counter event written.\n");

    AinosEtwProvider::WriteJsonEvent("{\"test\":true,\"value\":123}", ETW_LEVEL_INFO);
    wprintf(L"  JSON event written.\n");

    // Flush
    AinosEtwProvider::Flush();
    wprintf(L"  Events flushed.\n");

    // Test Event Log
    if (AinosEventLog::Initialize(L"AinosOS-Test")) {
        wprintf(L"\nEvent log initialized.\n");
        AinosEventLog::ReportInfo(L"ETW self-test completed successfully", 1000);
        AinosEventLog::ReportWarning(L"This is a test warning", 1001);
        AinosEventLog::ReportError(L"This is a test error", 1002);
        wprintf(L"Event log entries written.\n");
        AinosEventLog::Shutdown();
    }

    AinosEtwProvider::Shutdown();
    wprintf(L"\nSelf-test completed.\n");
}

int wmain(int argc, wchar_t* argv[]) {
    if (argc < 2) {
        ShowUsage();
        return 1;
    }

    std::wstring arg = argv[1];

    if (arg == L"--init" || arg == L"/init") {
        if (AinosEtwProvider::Initialize()) {
            wprintf(L"ETW provider initialized.\n");
            wprintf(L"Provider GUID: {A1N0S-0000-0000-0000-000000000001}\n");
            return 0;
        } else {
            wprintf(L"Failed to initialize ETW provider.\n");
            return 1;
        }
    }
    else if (arg == L"--test" || arg == L"/test") {
        RunSelfTest();
        return 0;
    }
    else if (arg == L"--info" || arg == L"/info") {
        if (argc < 3) { wprintf(L"Usage: ainos_etw.exe --info <message>\n"); return 1; }
        if (!AinosEtwProvider::Initialize()) { wprintf(L"Failed to initialize ETW provider.\n"); return 1; }
        // Convert to wide string if needed
        char msg[4096];
        wcstombs(msg, argv[2], 4096);
        AinosEtwProvider::WriteInfo(msg);
        AinosEventLog::ReportInfo(argv[2]);
        AinosEtwProvider::Shutdown();
        return 0;
    }
    else if (arg == L"--warn" || arg == L"/warn") {
        if (argc < 3) { wprintf(L"Usage: ainos_etw.exe --warn <message>\n"); return 1; }
        if (!AinosEtwProvider::Initialize()) { wprintf(L"Failed to initialize ETW provider.\n"); return 1; }
        char msg[4096];
        wcstombs(msg, argv[2], 4096);
        AinosEtwProvider::WriteWarning(msg);
        AinosEventLog::ReportWarning(argv[2]);
        AinosEtwProvider::Shutdown();
        return 0;
    }
    else if (arg == L"--error" || arg == L"/error") {
        if (argc < 3) { wprintf(L"Usage: ainos_etw.exe --error <message>\n"); return 1; }
        if (!AinosEtwProvider::Initialize()) { wprintf(L"Failed to initialize ETW provider.\n"); return 1; }
        char msg[4096];
        wcstombs(msg, argv[2], 4096);
        AinosEtwProvider::WriteError(msg);
        AinosEventLog::ReportError(argv[2]);
        AinosEtwProvider::Shutdown();
        return 0;
    }
    else if (arg == L"--critical" || arg == L"/critical") {
        if (argc < 3) { wprintf(L"Usage: ainos_etw.exe --critical <message>\n"); return 1; }
        if (!AinosEtwProvider::Initialize()) { wprintf(L"Failed to initialize ETW provider.\n"); return 1; }
        char msg[4096];
        wcstombs(msg, argv[2], 4096);
        AinosEtwProvider::WriteCritical(msg);
        AinosEventLog::ReportCritical(argv[2]);
        AinosEtwProvider::Shutdown();
        return 0;
    }
    else if (arg == L"--help" || arg == L"/?" || arg == L"/help") {
        ShowUsage();
        return 0;
    }
    else {
        wprintf(L"Unknown argument: %s\n", arg.c_str());
        ShowUsage();
        return 1;
    }
}