// Ainos OS - Windows Registry Configuration
//
// This file provides read/write access to the AinosOS configuration stored in
// the Windows Registry. It supports migration from TOML config files and
// provides default values for all settings.
//
// Registry Root: HKEY_LOCAL_MACHINE\SOFTWARE\AinosOS
// Also supports: HKEY_CURRENT_USER\SOFTWARE\AinosOS (for user-specific settings)
//
// Hierarchy:
//   SOFTWARE\AinosOS
//   ├── InstallDir (REG_SZ)
//   ├── ConfigVersion (REG_DWORD)
//   ├── Settings
//   │   ├── LogLevel, EnableLocal, EnableCloud, EnableTLS, etc.
//   ├── Models
//   │   ├── DefaultModel, ModelsDir, LocalEngine
//   ├── Paths
//   │   ├── SocketPath, ContextDir, AuditLog, CertPath, KeyPath
//   ├── Cloud
//   │   ├── ApiUrl, ApiKey, CloudModel
//   ├── Auth
//   │   ├── Enabled, TokenPath, SessionTTLSeconds, DefaultPermissions
//   ├── RateLimit
//   │   ├── Enabled, InferRPS, InferBurst, ModelRPS, etc.
//   └── Logs
//       ├── LogDir, MaxLogSizeMB

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <tchar.h>
#include <strsafe.h>
#include <stdlib.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <map>
#include <sstream>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <memory>
#include <algorithm>
#include <cwchar>
#include <cstring>
#include <cctype>

// ============================================================================
// Constants
// ============================================================================

// Registry root path
const wchar_t* REG_ROOT = L"SOFTWARE\\AinosOS";
const wchar_t* REG_ROOT_USER = L"SOFTWARE\\AinosOS";

// Subkey paths
const wchar_t* REG_SETTINGS = L"SOFTWARE\\AinosOS\\Settings";
const wchar_t* REG_MODELS = L"SOFTWARE\\AinosOS\\Models";
const wchar_t* REG_PATHS = L"SOFTWARE\\AinosOS\\Paths";
const wchar_t* REG_CLOUD = L"SOFTWARE\\AinosOS\\Cloud";
const wchar_t* REG_AUTH = L"SOFTWARE\\AinosOS\\Auth";
const wchar_t* REG_RATELIMIT = L"SOFTWARE\\AinosOS\\RateLimit";
const wchar_t* REG_LOGS = L"SOFTWARE\\AinosOS\\Logs";

// Current config version
const DWORD CONFIG_VERSION = 1;

// ============================================================================
// AinosRegistry Class
// ============================================================================

class AinosRegistry {
public:
    /// Initialize the registry with default values.
    static bool Initialize() {
        if (!IsConfigured()) {
            return CreateDefaultConfiguration();
        }
        return true;
    }

    /// Check if the registry has been initialized.
    static bool IsConfigured() {
        HKEY hKey = NULL;
        LONG status = RegOpenKeyExW(HKEY_LOCAL_MACHINE, REG_ROOT, 0, KEY_READ, &hKey);
        if (status == ERROR_SUCCESS) {
            DWORD value = 0;
            DWORD valueSize = sizeof(value);
            DWORD type = 0;
            status = RegQueryValueExW(hKey, L"ConfigVersion", NULL, &type, (LPBYTE)&value, &valueSize);
            RegCloseKey(hKey);
            return (status == ERROR_SUCCESS && type == REG_DWORD);
        }
        return false;
    }

    /// Create default configuration in the registry.
    static bool CreateDefaultConfiguration() {
        // Create main key
        HKEY hKey = NULL;
        LONG status = RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_ROOT, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
        if (status != ERROR_SUCCESS) {
            // Try HKCU
            status = RegCreateKeyExW(HKEY_CURRENT_USER, REG_ROOT_USER, 0, NULL,
                REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
            if (status != ERROR_SUCCESS) {
                return false;
            }
        }

        // Set version
        RegSetValueExW(hKey, L"ConfigVersion", 0, REG_DWORD, (const BYTE*)&CONFIG_VERSION, sizeof(CONFIG_VERSION));

        // Set InstallDir
        const wchar_t* defaultInstallDir = L"C:\\Program Files\\AinosOS";
        RegSetValueExW(hKey, L"InstallDir", 0, REG_SZ,
            (const BYTE*)defaultInstallDir, (DWORD)((wcslen(defaultInstallDir) + 1) * sizeof(wchar_t)));
        RegCloseKey(hKey);

        // Create subkeys with defaults
        CreateSettingsDefaults();
        CreateModelsDefaults();
        CreatePathsDefaults();
        CreateCloudDefaults();
        CreateAuthDefaults();
        CreateRateLimitDefaults();
        CreateLogsDefaults();

        return true;
    }

    /// Reset all configuration to defaults.
    static bool ResetToDefaults() {
        // Delete existing keys
        DeleteKey(HKEY_LOCAL_MACHINE, REG_ROOT);
        DeleteKey(HKEY_CURRENT_USER, REG_ROOT_USER);

        // Recreate
        return CreateDefaultConfiguration();
    }

    /// Delete a registry key and all its subkeys recursively.
    static bool DeleteKey(HKEY hRootKey, const wchar_t* subKey) {
        // Use RegDeleteTree for Windows Vista+
        // This deletes the key and all subkeys recursively
        HKEY hKey = NULL;
        LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_WRITE | KEY_READ, &hKey);
        if (status != ERROR_SUCCESS) {
            return true; // Key doesn't exist, nothing to delete
        }

        // Enumerate and delete all subkeys first
        while (true) {
            wchar_t subKeyName[256] = {0};
            DWORD subKeyNameLen = 256;
            LONG enumStatus = RegEnumKeyExW(hKey, 0, subKeyName, &subKeyNameLen, NULL, NULL, NULL, NULL);
            if (enumStatus == ERROR_NO_MORE_ITEMS) {
                break;
            }
            if (enumStatus == ERROR_SUCCESS) {
                // Build full path
                std::wstring fullPath = subKey;
                fullPath += L"\\";
                fullPath += subKeyName;
                DeleteKey(hRootKey, fullPath.c_str());
            }
        }
        RegCloseKey(hKey);

        // Now delete the key itself
        status = RegDeleteTreeW(hRootKey, subKey);
        if (status == ERROR_SUCCESS || status == ERROR_FILE_NOT_FOUND) {
            return true;
        }

        // Fallback for older Windows
        if (status == ERROR_INVALID_PARAMETER || status == ERROR_NOT_SUPPORTED) {
            // Manual recursive deletion
            status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_WRITE | KEY_READ, &hKey);
            if (status != ERROR_SUCCESS) return true;

            // Delete all values
            while (true) {
                wchar_t valueName[256] = {0};
                DWORD valueNameLen = 256;
                LONG enumStatus = RegEnumValueW(hKey, 0, valueName, &valueNameLen, NULL, NULL, NULL, NULL);
                if (enumStatus == ERROR_NO_MORE_ITEMS) break;
                if (enumStatus == ERROR_SUCCESS) {
                    RegDeleteValueW(hKey, valueName);
                }
            }
            RegCloseKey(hKey);

            // Delete the key
            status = RegDeleteKeyW(hRootKey, subKey);
            return (status == ERROR_SUCCESS || status == ERROR_FILE_NOT_FOUND);
        }

        return (status == ERROR_SUCCESS || status == ERROR_FILE_NOT_FOUND);
    }

    /// Delete a specific value.
    static bool DeleteValue(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName) {
        HKEY hKey = NULL;
        LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_WRITE, &hKey);
        if (status != ERROR_SUCCESS) {
            return false;
        }

        status = RegDeleteValueW(hKey, valueName);
        RegCloseKey(hKey);

        return (status == ERROR_SUCCESS);
    }

    // ========================================================================
    // Read Methods
    // ========================================================================

    /// Read a string value from the registry.
    static std::wstring GetString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, const wchar_t* defaultValue) {
        HKEY hKey = NULL;
        std::wstring result = defaultValue;

        LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_READ, &hKey);
        if (status == ERROR_SUCCESS) {
            wchar_t buffer[4096] = {0};
            DWORD bufferSize = sizeof(buffer);
            DWORD type = 0;

            status = RegQueryValueExW(hKey, valueName, NULL, &type, (LPBYTE)buffer, &bufferSize);
            if (status == ERROR_SUCCESS && (type == REG_SZ || type == REG_EXPAND_SZ)) {
                result = buffer;
            }

            RegCloseKey(hKey);
        }

        return result;
    }

    /// Read a DWORD value from the registry.
    static DWORD GetDword(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, DWORD defaultValue) {
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

    /// Read a boolean value (stored as DWORD: 0=false, 1=true).
    static bool GetBool(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, bool defaultValue) {
        return GetDword(hRootKey, subKey, valueName, defaultValue ? 1 : 0) != 0;
    }

    /// Read a multi-string value (REG_MULTI_SZ).
    static std::vector<std::wstring> GetMultiString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName) {
        std::vector<std::wstring> result;
        HKEY hKey = NULL;

        LONG status = RegOpenKeyExW(hRootKey, subKey, 0, KEY_READ, &hKey);
        if (status == ERROR_SUCCESS) {
            // First call to get size
            DWORD bufferSize = 0;
            DWORD type = 0;
            status = RegQueryValueExW(hKey, valueName, NULL, &type, NULL, &bufferSize);

            if (status == ERROR_SUCCESS && type == REG_MULTI_SZ && bufferSize > 0) {
                std::vector<wchar_t> buffer(bufferSize / sizeof(wchar_t) + 1, 0);
                status = RegQueryValueExW(hKey, valueName, NULL, &type, (LPBYTE)buffer.data(), &bufferSize);

                if (status == ERROR_SUCCESS) {
                    // Parse multi-string (null-separated, double-null terminated)
                    const wchar_t* p = buffer.data();
                    while (*p != L'\0') {
                        result.push_back(std::wstring(p));
                        p += wcslen(p) + 1;
                    }
                }
            }

            RegCloseKey(hKey);
        }

        return result;
    }

    // ========================================================================
    // Write Methods
    // ========================================================================

    /// Write a string value to the registry.
    static bool SetString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, const wchar_t* value) {
        HKEY hKey = NULL;
        LONG status = RegCreateKeyExW(hRootKey, subKey, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
        if (status != ERROR_SUCCESS) {
            return false;
        }

        status = RegSetValueExW(hKey, valueName, 0, REG_SZ,
            (const BYTE*)value, (DWORD)((wcslen(value) + 1) * sizeof(wchar_t)));
        RegCloseKey(hKey);

        return (status == ERROR_SUCCESS);
    }

    /// Write a DWORD value to the registry.
    static bool SetDword(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, DWORD value) {
        HKEY hKey = NULL;
        LONG status = RegCreateKeyExW(hRootKey, subKey, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
        if (status != ERROR_SUCCESS) {
            return false;
        }

        status = RegSetValueExW(hKey, valueName, 0, REG_DWORD, (const BYTE*)&value, sizeof(value));
        RegCloseKey(hKey);

        return (status == ERROR_SUCCESS);
    }

    /// Write a boolean value (stored as DWORD).
    static bool SetBool(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, bool value) {
        return SetDword(hRootKey, subKey, valueName, value ? 1 : 0);
    }

    /// Write a multi-string value (REG_MULTI_SZ).
    static bool SetMultiString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName,
        const std::vector<std::wstring>& values) {
        HKEY hKey = NULL;
        LONG status = RegCreateKeyExW(hRootKey, subKey, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL);
        if (status != ERROR_SUCCESS) {
            return false;
        }

        // Build multi-string buffer: each string null-terminated, double-null at end
        size_t totalLen = 1; // For final null
        for (const auto& s : values) {
            totalLen += s.length() + 1;
        }

        std::vector<wchar_t> buffer(totalLen, 0);
        size_t offset = 0;
        for (const auto& s : values) {
            wcscpy_s(&buffer[offset], totalLen - offset, s.c_str());
            offset += s.length() + 1;
        }
        buffer[totalLen - 1] = L'\0'; // Double null terminate

        status = RegSetValueExW(hKey, valueName, 0, REG_MULTI_SZ,
            (const BYTE*)buffer.data(), (DWORD)(totalLen * sizeof(wchar_t)));
        RegCloseKey(hKey);

        return (status == ERROR_SUCCESS);
    }

    // ========================================================================
    // Convenience Methods (HKEY_LOCAL_MACHINE)
    // ========================================================================

    static std::wstring Get_InstallDir() {
        return GetString(HKEY_LOCAL_MACHINE, REG_ROOT, L"InstallDir", L"C:\\Program Files\\AinosOS");
    }

    static bool Set_InstallDir(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_ROOT, L"InstallDir", path);
    }

    // Settings
    static std::wstring Get_LogLevel() {
        return GetString(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"LogLevel", L"info");
    }

    static bool Set_LogLevel(const wchar_t* level) {
        return SetString(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"LogLevel", level);
    }

    static bool Get_EnableLocal() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableLocal", true);
    }

    static bool Set_EnableLocal(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableLocal", enable);
    }

    static bool Get_EnableCloud() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableCloud", true);
    }

    static bool Set_EnableCloud(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableCloud", enable);
    }

    static bool Get_EnableTLS() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableTLS", false);
    }

    static bool Set_EnableTLS(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"EnableTLS", enable);
    }

    static DWORD Get_NetworkCheckInterval() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"NetworkCheckInterval", 30);
    }

    static bool Set_NetworkCheckInterval(DWORD seconds) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"NetworkCheckInterval", seconds);
    }

    static DWORD Get_CloudFallbackConfidence() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"CloudFallbackConfidence", 60);
    }

    static bool Set_CloudFallbackConfidence(DWORD percent) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"CloudFallbackConfidence", percent);
    }

    static DWORD Get_MaxConcurrentInferences() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"MaxConcurrentInferences", 2);
    }

    static bool Set_MaxConcurrentInferences(DWORD count) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"MaxConcurrentInferences", count);
    }

    static DWORD Get_ModelCacheSizeMB() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"ModelCacheSizeMB", 4096);
    }

    static bool Set_ModelCacheSizeMB(DWORD mb) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"ModelCacheSizeMB", mb);
    }

    static DWORD Get_InferenceTimeoutSecs() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"InferenceTimeoutSecs", 120);
    }

    static bool Set_InferenceTimeoutSecs(DWORD seconds) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"InferenceTimeoutSecs", seconds);
    }

    static bool Get_AuditAllRequests() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"AuditAllRequests", false);
    }

    static bool Set_AuditAllRequests(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_SETTINGS, L"AuditAllRequests", enable);
    }

    // Models
    static std::wstring Get_DefaultModel() {
        return GetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"DefaultModel", L"qwen2.5-0.5b-instruct-q4.gguf");
    }

    static bool Set_DefaultModel(const wchar_t* modelName) {
        return SetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"DefaultModel", modelName);
    }

    static std::wstring Get_ModelsDir() {
        return GetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"ModelsDir", L"C:\\ProgramData\\AinosOS\\Models");
    }

    static bool Set_ModelsDir(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"ModelsDir", path);
    }

    static std::wstring Get_LocalEngine() {
        return GetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"LocalEngine", L"ggml");
    }

    static bool Set_LocalEngine(const wchar_t* engine) {
        return SetString(HKEY_LOCAL_MACHINE, REG_MODELS, L"LocalEngine", engine);
    }

    // Paths
    static std::wstring Get_SocketPath() {
        return GetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"SocketPath", L"\\\\.\\pipe\\ainos-daemon");
    }

    static bool Set_SocketPath(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"SocketPath", path);
    }

    static std::wstring Get_ContextDir() {
        return GetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"ContextDir", L"C:\\ProgramData\\AinosOS\\Data\\Contexts");
    }

    static bool Set_ContextDir(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"ContextDir", path);
    }

    static std::wstring Get_AuditLog() {
        return GetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"AuditLog", L"C:\\ProgramData\\AinosOS\\Logs\\audit.log");
    }

    static bool Set_AuditLog(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"AuditLog", path);
    }

    static std::wstring Get_CertPath() {
        return GetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"CertPath", L"C:\\ProgramData\\AinosOS\\Certs\\server.crt");
    }

    static bool Set_CertPath(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"CertPath", path);
    }

    static std::wstring Get_KeyPath() {
        return GetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"KeyPath", L"C:\\ProgramData\\AinosOS\\Certs\\server.key");
    }

    static bool Set_KeyPath(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"KeyPath", path);
    }

    // Cloud
    static std::wstring Get_CloudApiUrl() {
        return GetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"ApiUrl", L"https://api.weelinking.com/v1");
    }

    static bool Set_CloudApiUrl(const wchar_t* url) {
        return SetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"ApiUrl", url);
    }

    static std::wstring Get_CloudApiKey() {
        return GetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"ApiKey", L"");
    }

    static bool Set_CloudApiKey(const wchar_t* key) {
        return SetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"ApiKey", key);
    }

    static std::wstring Get_CloudModel() {
        return GetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"CloudModel", L"gpt-5.6-sol");
    }

    static bool Set_CloudModel(const wchar_t* model) {
        return SetString(HKEY_LOCAL_MACHINE, REG_CLOUD, L"CloudModel", model);
    }

    // Auth
    static bool Get_AuthEnabled() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_AUTH, L"Enabled", true);
    }

    static bool Set_AuthEnabled(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_AUTH, L"Enabled", enable);
    }

    static std::wstring Get_TokenPath() {
        return GetString(HKEY_LOCAL_MACHINE, REG_AUTH, L"TokenPath", L"C:\\ProgramData\\AinosOS\\Configs\\auth_token.txt");
    }

    static bool Set_TokenPath(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_AUTH, L"TokenPath", path);
    }

    static DWORD Get_SessionTTLSeconds() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_AUTH, L"SessionTTLSeconds", 3600);
    }

    static bool Set_SessionTTLSeconds(DWORD seconds) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_AUTH, L"SessionTTLSeconds", seconds);
    }

    static std::vector<std::wstring> Get_DefaultPermissions() {
        return GetMultiString(HKEY_LOCAL_MACHINE, REG_AUTH, L"DefaultPermissions");
    }

    static bool Set_DefaultPermissions(const std::vector<std::wstring>& permissions) {
        return SetMultiString(HKEY_LOCAL_MACHINE, REG_AUTH, L"DefaultPermissions", permissions);
    }

    // RateLimit
    static bool Get_RateLimitEnabled() {
        return GetBool(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"Enabled", true);
    }

    static bool Set_RateLimitEnabled(bool enable) {
        return SetBool(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"Enabled", enable);
    }

    static DWORD Get_RateLimitInferRPS() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"InferRPS", 100);
    }

    static DWORD Get_RateLimitInferBurst() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"InferBurst", 200);
    }

    static DWORD Get_RateLimitModelRPS() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"ModelRPS", 10);
    }

    static DWORD Get_RateLimitModelBurst() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"ModelBurst", 20);
    }

    static DWORD Get_RateLimitStatusRPS() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"StatusRPS", 1000);
    }

    static DWORD Get_RateLimitStatusBurst() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"StatusBurst", 2000);
    }

    static DWORD Get_RateLimitAdminRPS() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"AdminRPS", 5);
    }

    static DWORD Get_RateLimitAdminBurst() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"AdminBurst", 10);
    }

    static DWORD Get_RateLimitMaxClients() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"MaxClients", 1000);
    }

    // Logs
    static std::wstring Get_LogDir() {
        return GetString(HKEY_LOCAL_MACHINE, REG_LOGS, L"LogDir", L"C:\\ProgramData\\AinosOS\\Logs");
    }

    static bool Set_LogDir(const wchar_t* path) {
        return SetString(HKEY_LOCAL_MACHINE, REG_LOGS, L"LogDir", path);
    }

    static DWORD Get_MaxLogSizeMB() {
        return GetDword(HKEY_LOCAL_MACHINE, REG_LOGS, L"MaxLogSizeMB", 100);
    }

    static bool Set_MaxLogSizeMB(DWORD mb) {
        return SetDword(HKEY_LOCAL_MACHINE, REG_LOGS, L"MaxLogSizeMB", mb);
    }

    // ========================================================================
    // TOML Export / Import
    // ========================================================================

    /// Export registry configuration to TOML format.
    static std::wstring ExportToToml() {
        std::wstringstream ss;

        ss << L"# Ainos AI Daemon Configuration\n";
        ss << L"# Generated from Windows Registry\n";
        ss << L"# ============================================\n\n";

        // Basic settings
        ss << L"models_dir = \"" << EscapeTomlString(Get_ModelsDir()) << L"\"\n";
        ss << L"default_model = \"" << EscapeTomlString(Get_DefaultModel()) << L"\"\n";
        ss << L"socket_path = \"" << EscapeTomlString(Get_SocketPath()) << L"\"\n\n";

        // Local inference
        ss << L"# Local inference\n";
        ss << L"enable_local = " << (Get_EnableLocal() ? L"true" : L"false") << L"\n";
        ss << L"local_engine = \"" << EscapeTomlString(Get_LocalEngine()) << L"\"\n";
        ss << L"max_concurrent_inferences = " << Get_MaxConcurrentInferences() << L"\n";
        ss << L"model_cache_size_mb = " << Get_ModelCacheSizeMB() << L"\n";
        ss << L"inference_timeout_secs = " << Get_InferenceTimeoutSecs() << L"\n\n";

        // Cloud fallback
        ss << L"# Cloud fallback\n";
        ss << L"enable_cloud = " << (Get_EnableCloud() ? L"true" : L"false") << L"\n";
        ss << L"cloud_api_url = \"" << EscapeTomlString(Get_CloudApiUrl()) << L"\"\n";
        ss << L"cloud_api_key = \"" << EscapeTomlString(Get_CloudApiKey()) << L"\"\n";
        ss << L"cloud_model = \"" << EscapeTomlString(Get_CloudModel()) << L"\"\n";
        ss << L"network_check_interval = " << Get_NetworkCheckInterval() << L"\n";
        ss << L"cloud_fallback_confidence = " << std::fixed << std::setprecision(1)
            << (Get_CloudFallbackConfidence() / 100.0) << L"\n\n";

        // Context management
        ss << L"# Context management\n";
        ss << L"context_dir = \"" << EscapeTomlString(Get_ContextDir()) << L"\"\n";
        ss << L"max_contexts = 1000\n";
        ss << L"context_ttl_days = 30\n\n";

        // Logging
        ss << L"# Logging\n";
        ss << L"log_level = \"" << EscapeTomlString(Get_LogLevel()) << L"\"\n";
        ss << L"audit_log = \"" << EscapeTomlString(Get_AuditLog()) << L"\"\n";
        ss << L"audit_all_requests = " << (Get_AuditAllRequests() ? L"true" : L"false") << L"\n\n";

        // TLS
        ss << L"# Legacy TLS settings (deprecated, use [tls] section)\n";
        ss << L"enable_tls = " << (Get_EnableTLS() ? L"true" : L"false") << L"\n";
        ss << L"tls_cert_path = \"" << EscapeTomlString(Get_CertPath()) << L"\"\n";
        ss << L"tls_key_path = \"" << EscapeTomlString(Get_KeyPath()) << L"\"\n\n";

        // Auth section
        ss << L"# ============================================\n";
        ss << L"# Authentication\n";
        ss << L"# ============================================\n";
        ss << L"[auth]\n";
        ss << L"enabled = " << (Get_AuthEnabled() ? L"true" : L"false") << L"\n";
        ss << L"token = \"\"\n";  // Token is not stored in registry for security
        ss << L"token_path = \"" << EscapeTomlString(Get_TokenPath()) << L"\"\n";
        ss << L"session_ttl_seconds = " << Get_SessionTTLSeconds() << L"\n";
        ss << L"permissions_file = \"\"\n";

        // Default permissions
        auto permissions = Get_DefaultPermissions();
        if (!permissions.empty()) {
            ss << L"default_permissions = [";
            for (size_t i = 0; i < permissions.size(); i++) {
                if (i > 0) ss << L", ";
                ss << L"\"" << EscapeTomlString(permissions[i]) << L"\"";
            }
            ss << L"]\n";
        }

        ss << L"audit_log_path = \"" << EscapeTomlString(Get_AuditLog()) << L"\"\n";
        ss << L"audit_all_requests = " << (Get_AuditAllRequests() ? L"true" : L"false") << L"\n\n";

        // RateLimit section
        ss << L"# ============================================\n";
        ss << L"# Rate Limiting\n";
        ss << L"# ============================================\n";
        ss << L"[ratelimit]\n";
        ss << L"enabled = " << (Get_RateLimitEnabled() ? L"true" : L"false") << L"\n";
        ss << L"infer_rps = " << Get_RateLimitInferRPS() << L".0\n";
        ss << L"infer_burst = " << Get_RateLimitInferBurst() << L".0\n";
        ss << L"model_rps = " << Get_RateLimitModelRPS() << L".0\n";
        ss << L"model_burst = " << Get_RateLimitModelBurst() << L".0\n";
        ss << L"status_rps = " << Get_RateLimitStatusRPS() << L".0\n";
        ss << L"status_burst = " << Get_RateLimitStatusBurst() << L".0\n";
        ss << L"admin_rps = " << Get_RateLimitAdminRPS() << L".0\n";
        ss << L"admin_burst = " << Get_RateLimitAdminBurst() << L".0\n";
        ss << L"max_clients = " << Get_RateLimitMaxClients() << L"\n";
        ss << L"cleanup_interval_secs = 300\n\n";

        // TLS section
        ss << L"# ============================================\n";
        ss << L"# TLS / Transport Security\n";
        ss << L"# ============================================\n";
        ss << L"[tls]\n";
        ss << L"enabled = " << (Get_EnableTLS() ? L"true" : L"false") << L"\n";
        ss << L"cert_path = \"" << EscapeTomlString(Get_CertPath()) << L"\"\n";
        ss << L"key_path = \"" << EscapeTomlString(Get_KeyPath()) << L"\"\n";
        ss << L"verify_client = false\n";

        return ss.str();
    }

    /// Import configuration from a TOML file.
    static bool ImportFromToml(const wchar_t* filePath) {
        // Read the TOML file
        std::wifstream file(filePath);
        if (!file.is_open()) {
            return false;
        }

        // Read the file content
        std::wstringstream buffer;
        buffer << file.rdbuf();
        std::wstring content = buffer.str();
        file.close();

        // Parse the TOML content (simple line-by-line parser)
        // This is a basic parser that handles the AinosOS config format
        std::wstring currentSection;
        std::wistringstream stream(content);
        std::wstring line;

        while (std::getline(stream, line)) {
            // Trim whitespace
            line = Trim(line);

            // Skip comments and empty lines
            if (line.empty() || line[0] == L'#') {
                continue;
            }

            // Check for section header
            if (line[0] == L'[') {
                size_t end = line.find(L']');
                if (end != std::wstring::npos) {
                    currentSection = line.substr(1, end - 1);
                }
                continue;
            }

            // Parse key = value
            size_t eqPos = line.find(L'=');
            if (eqPos == std::wstring::npos) {
                continue;
            }

            std::wstring key = Trim(line.substr(0, eqPos));
            std::wstring value = Trim(line.substr(eqPos + 1));

            // Remove quotes from string values
            if (value.size() >= 2 && value[0] == L'"' && value.back() == L'"') {
                value = value.substr(1, value.size() - 2);
            }

            // Dispatch based on section and key
            if (currentSection.empty()) {
                // Root-level keys
                if (key == L"models_dir") Set_ModelsDir(value.c_str());
                else if (key == L"default_model") Set_DefaultModel(value.c_str());
                else if (key == L"socket_path") Set_SocketPath(value.c_str());
                else if (key == L"enable_local") Set_EnableLocal(value == L"true");
                else if (key == L"local_engine") Set_LocalEngine(value.c_str());
                else if (key == L"enable_cloud") Set_EnableCloud(value == L"true");
                else if (key == L"cloud_api_url") Set_CloudApiUrl(value.c_str());
                else if (key == L"cloud_api_key") Set_CloudApiKey(value.c_str());
                else if (key == L"cloud_model") Set_CloudModel(value.c_str());
                else if (key == L"network_check_interval") Set_NetworkCheckInterval((DWORD)_wtoi(value.c_str()));
                else if (key == L"context_dir") SetString(HKEY_LOCAL_MACHINE, REG_PATHS, L"ContextDir", value.c_str());
                else if (key == L"log_level") Set_LogLevel(value.c_str());
                else if (key == L"audit_log") Set_AuditLog(value.c_str());
                else if (key == L"enable_tls") Set_EnableTLS(value == L"true");
                else if (key == L"tls_cert_path") Set_CertPath(value.c_str());
                else if (key == L"tls_key_path") Set_KeyPath(value.c_str());
                else if (key == L"max_concurrent_inferences") Set_MaxConcurrentInferences((DWORD)_wtoi(value.c_str()));
                else if (key == L"model_cache_size_mb") Set_ModelCacheSizeMB((DWORD)_wtoi(value.c_str()));
                else if (key == L"inference_timeout_secs") Set_InferenceTimeoutSecs((DWORD)_wtoi(value.c_str()));
                else if (key == L"audit_all_requests") Set_AuditAllRequests(value == L"true");
            }
            else if (currentSection == L"auth") {
                if (key == L"enabled") Set_AuthEnabled(value == L"true");
                else if (key == L"token_path") Set_TokenPath(value.c_str());
                else if (key == L"session_ttl_seconds") Set_SessionTTLSeconds((DWORD)_wtoi(value.c_str()));
                else if (key == L"audit_log_path") Set_AuditLog(value.c_str());
                else if (key == L"audit_all_requests") Set_AuditAllRequests(value == L"true");
            }
            else if (currentSection == L"ratelimit") {
                if (key == L"enabled") Set_RateLimitEnabled(value == L"true");
                else if (key == L"infer_rps") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"InferRPS", (DWORD)_wtoi(value.c_str()));
                else if (key == L"infer_burst") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"InferBurst", (DWORD)_wtoi(value.c_str()));
                else if (key == L"model_rps") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"ModelRPS", (DWORD)_wtoi(value.c_str()));
                else if (key == L"model_burst") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"ModelBurst", (DWORD)_wtoi(value.c_str()));
                else if (key == L"status_rps") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"StatusRPS", (DWORD)_wtoi(value.c_str()));
                else if (key == L"status_burst") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"StatusBurst", (DWORD)_wtoi(value.c_str()));
                else if (key == L"admin_rps") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"AdminRPS", (DWORD)_wtoi(value.c_str()));
                else if (key == L"admin_burst") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"AdminBurst", (DWORD)_wtoi(value.c_str()));
                else if (key == L"max_clients") SetDword(HKEY_LOCAL_MACHINE, REG_RATELIMIT, L"MaxClients", (DWORD)_wtoi(value.c_str()));
            }
            else if (currentSection == L"tls") {
                if (key == L"enabled") Set_EnableTLS(value == L"true");
                else if (key == L"cert_path") Set_CertPath(value.c_str());
                else if (key == L"key_path") Set_KeyPath(value.c_str());
            }
        }

        return true;
    }

    // ========================================================================
    // PowerShell Script Generation
    // ========================================================================

    /// Generate a PowerShell script for editing the registry configuration.
    static std::wstring GeneratePowerShellEditScript() {
        std::wstringstream ss;

        ss << L"<#\n";
        ss << L".SYNOPSIS\n";
        ss << L"    Ainos OS Configuration Editor\n";
        ss << L".DESCRIPTION\n";
        ss << L"    Edit the AinosOS configuration stored in the Windows Registry.\n";
        ss << L"    This script requires Administrator privileges.\n";
        ss << L"#>\n\n";

        ss << L"#Requires -RunAsAdministrator\n\n";

        ss << L"# Registry paths\n";
        ss << L"$RegRoot = \"HKLM:\\SOFTWARE\\AinosOS\"\n";
        ss << L"$RegSettings = \"HKLM:\\SOFTWARE\\AinosOS\\Settings\"\n";
        ss << L"$RegModels = \"HKLM:\\SOFTWARE\\AinosOS\\Models\"\n";
        ss << L"$RegPaths = \"HKLM:\\SOFTWARE\\AinosOS\\Paths\"\n";
        ss << L"$RegCloud = \"HKLM:\\SOFTWARE\\AinosOS\\Cloud\"\n";
        ss << L"$RegAuth = \"HKLM:\\SOFTWARE\\AinosOS\\Auth\"\n";
        ss << L"$RegRateLimit = \"HKLM:\\SOFTWARE\\AinosOS\\RateLimit\"\n";
        ss << L"$RegLogs = \"HKLM:\\SOFTWARE\\AinosOS\\Logs\"\n\n";

        ss << L"# Ensure registry paths exist\n";
        ss << L"$paths = @($RegRoot, $RegSettings, $RegModels, $RegPaths, $RegCloud, $RegAuth, $RegRateLimit, $RegLogs)\n";
        ss << L"foreach ($p in $paths) {\n";
        ss << L"    if (-not (Test-Path $p)) {\n";
        ss << L"        New-Item -Path $p -Force | Out-Null\n";
        ss << L"    }\n";
        ss << L"}\n\n";

        ss << L"# Helper function to get or set registry value\n";
        ss << L"function Get-RegValue {\n";
        ss << L"    param([string]$Path, [string]$Name, $Default)\n";
        ss << L"    $value = Get-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue\n";
        ss << L"    if ($null -eq $value) { return $Default }\n";
        ss << L"    return $value.$Name\n";
        ss << L"}\n\n";

        ss << L"# ====================================================================\n";
        ss << L"# Display current configuration\n";
        ss << L"# ====================================================================\n";
        ss << L"\n";
        ss << L"Write-Host \"========================================\" -ForegroundColor Cyan\n";
        ss << L"Write-Host \"  Ainos OS Configuration Editor\" -ForegroundColor Cyan\n";
        ss << L"Write-Host \"========================================\" -ForegroundColor Cyan\n";
        ss << L"Write-Host \"\"\n\n";

        ss << L"# Display current values\n";
        ss << L"Write-Host \"Current Configuration:\" -ForegroundColor Yellow\n";
        ss << L"Write-Host \"\"\n\n";

        // Add all current values
        ss << L"# General Settings\n";
        ss << L"Write-Host \"[Settings]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  LogLevel               = \" (Get-RegValue $RegSettings LogLevel 'info')\n";
        ss << L"Write-Host \"  EnableLocal            = \" (Get-RegValue $RegSettings EnableLocal 1)\n";
        ss << L"Write-Host \"  EnableCloud            = \" (Get-RegValue $RegSettings EnableCloud 1)\n";
        ss << L"Write-Host \"  EnableTLS              = \" (Get-RegValue $RegSettings EnableTLS 0)\n";
        ss << L"Write-Host \"  NetworkCheckInterval   = \" (Get-RegValue $RegSettings NetworkCheckInterval 30)\n";
        ss << L"Write-Host \"  MaxConcurrentInferences= \" (Get-RegValue $RegSettings MaxConcurrentInferences 2)\n";
        ss << L"Write-Host \"  ModelCacheSizeMB       = \" (Get-RegValue $RegSettings ModelCacheSizeMB 4096)\n";
        ss << L"Write-Host \"  InferenceTimeoutSecs   = \" (Get-RegValue $RegSettings InferenceTimeoutSecs 120)\n";
        ss << L"Write-Host \"  AuditAllRequests       = \" (Get-RegValue $RegSettings AuditAllRequests 0)\n\n";

        ss << L"# Models\n";
        ss << L"Write-Host \"[Models]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  DefaultModel           = \" (Get-RegValue $RegModels DefaultModel 'qwen2.5-0.5b-instruct-q4.gguf')\n";
        ss << L"Write-Host \"  ModelsDir              = \" (Get-RegValue $RegModels ModelsDir 'C:\\ProgramData\\AinosOS\\Models')\n";
        ss << L"Write-Host \"  LocalEngine            = \" (Get-RegValue $RegModels LocalEngine 'ggml')\n\n";

        ss << L"# Paths\n";
        ss << L"Write-Host \"[Paths]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  SocketPath             = \" (Get-RegValue $RegPaths SocketPath '\\\\.\\pipe\\ainos-daemon')\n";
        ss << L"Write-Host \"  ContextDir             = \" (Get-RegValue $RegPaths ContextDir 'C:\\ProgramData\\AinosOS\\Data\\Contexts')\n\n";

        ss << L"# Cloud\n";
        ss << L"Write-Host \"[Cloud]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  ApiUrl                 = \" (Get-RegValue $RegCloud ApiUrl 'https://api.weelinking.com/v1')\n";
        ss << L"Write-Host \"  CloudModel             = \" (Get-RegValue $RegCloud CloudModel 'gpt-5.6-sol')\n\n";

        ss << L"# Auth\n";
        ss << L"Write-Host \"[Auth]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  Enabled                = \" (Get-RegValue $RegAuth Enabled 1)\n";
        ss << L"Write-Host \"  SessionTTLSeconds      = \" (Get-RegValue $RegAuth SessionTTLSeconds 3600)\n\n";

        ss << L"# Rate Limit\n";
        ss << L"Write-Host \"[RateLimit]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  Enabled                = \" (Get-RegValue $RegRateLimit Enabled 1)\n";
        ss << L"Write-Host \"  InferRPS               = \" (Get-RegValue $RegRateLimit InferRPS 100)\n\n";

        ss << L"# Logs\n";
        ss << L"Write-Host \"[Logs]\" -ForegroundColor Green\n";
        ss << L"Write-Host \"  LogDir                 = \" (Get-RegValue $RegLogs LogDir 'C:\\ProgramData\\AinosOS\\Logs')\n";
        ss << L"Write-Host \"  MaxLogSizeMB           = \" (Get-RegValue $RegLogs MaxLogSizeMB 100)\n\n";

        ss << L"# ====================================================================\n";
        ss << L"# Example: How to modify values\n";
        ss << L"# ====================================================================\n";
        ss << L"#\n";
        ss << L"# Uncomment and modify the lines below to change configuration:\n";
        ss << L"#\n";
        ss << L"# Set-ItemProperty -Path $RegSettings -Name LogLevel -Value 'debug'\n";
        ss << L"# Set-ItemProperty -Path $RegModels -Name DefaultModel -Value 'phi-3-mini-4k-instruct-q4.gguf'\n";
        ss << L"# Set-ItemProperty -Path $RegCloud -Name ApiKey -Value 'your-api-key-here'\n";
        ss << L"# Set-ItemProperty -Path $RegSettings -Name EnableLocal -Value 0\n";
        ss << L"#\n";
        ss << L"# After editing, restart the Ainos service:\n";
        ss << L"# Restart-Service -Name AinosAIDaemon\n";
        ss << L"#\n";

        return ss.str();
    }

private:
    // ========================================================================
    // Private Helper Methods
    // ========================================================================

    /// Escape a string for TOML output.
    static std::wstring EscapeTomlString(const std::wstring& input) {
        std::wstring result;
        result.reserve(input.size());
        for (wchar_t c : input) {
            switch (c) {
            case L'\\': result += L"\\\\"; break;
            case L'"':  result += L"\\\""; break;
            case L'\n': result += L"\\n"; break;
            case L'\r': result += L"\\r"; break;
            case L'\t': result += L"\\t"; break;
            default:    result += c; break;
            }
        }
        return result;
    }

    /// Trim whitespace from a string.
    static std::wstring Trim(const std::wstring& str) {
        size_t start = str.find_first_not_of(L" \t\r\n");
        if (start == std::wstring::npos) return L"";
        size_t end = str.find_last_not_of(L" \t\r\n");
        return str.substr(start, end - start + 1);
    }

    /// Create default settings subkey.
    static void CreateSettingsDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_SETTINGS, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            DWORD val;
            val = 1; RegSetValueExW(hKey, L"EnableLocal", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 1; RegSetValueExW(hKey, L"EnableCloud", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 0; RegSetValueExW(hKey, L"EnableTLS", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 30; RegSetValueExW(hKey, L"NetworkCheckInterval", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 60; RegSetValueExW(hKey, L"CloudFallbackConfidence", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 2; RegSetValueExW(hKey, L"MaxConcurrentInferences", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 4096; RegSetValueExW(hKey, L"ModelCacheSizeMB", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 120; RegSetValueExW(hKey, L"InferenceTimeoutSecs", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 0; RegSetValueExW(hKey, L"AuditAllRequests", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 0; RegSetValueExW(hKey, L"Verbose", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            RegSetValueExW(hKey, L"LogLevel", 0, REG_SZ, (const BYTE*)L"info", (DWORD)((wcslen(L"info") + 1) * sizeof(wchar_t)));
            RegCloseKey(hKey);
        }
    }

    /// Create default models subkey.
    static void CreateModelsDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_MODELS, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExW(hKey, L"DefaultModel", 0, REG_SZ,
                (const BYTE*)L"qwen2.5-0.5b-instruct-q4.gguf",
                (DWORD)((wcslen(L"qwen2.5-0.5b-instruct-q4.gguf") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"ModelsDir", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Models",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Models") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"LocalEngine", 0, REG_SZ,
                (const BYTE*)L"ggml",
                (DWORD)((wcslen(L"ggml") + 1) * sizeof(wchar_t)));
            RegCloseKey(hKey);
        }
    }

    /// Create default paths subkey.
    static void CreatePathsDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_PATHS, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExW(hKey, L"SocketPath", 0, REG_SZ,
                (const BYTE*)L"\\\\.\\pipe\\ainos-daemon",
                (DWORD)((wcslen(L"\\\\.\\pipe\\ainos-daemon") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"ContextDir", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Data\\Contexts",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Data\\Contexts") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"AuditLog", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Logs\\audit.log",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Logs\\audit.log") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"CertPath", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Certs\\server.crt",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Certs\\server.crt") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"KeyPath", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Certs\\server.key",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Certs\\server.key") + 1) * sizeof(wchar_t)));
            RegCloseKey(hKey);
        }
    }

    /// Create default cloud subkey.
    static void CreateCloudDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_CLOUD, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExW(hKey, L"ApiUrl", 0, REG_SZ,
                (const BYTE*)L"https://api.weelinking.com/v1",
                (DWORD)((wcslen(L"https://api.weelinking.com/v1") + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"ApiKey", 0, REG_SZ,
                (const BYTE*)L"",
                (DWORD)((0 + 1) * sizeof(wchar_t)));
            RegSetValueExW(hKey, L"CloudModel", 0, REG_SZ,
                (const BYTE*)L"gpt-5.6-sol",
                (DWORD)((wcslen(L"gpt-5.6-sol") + 1) * sizeof(wchar_t)));
            RegCloseKey(hKey);
        }
    }

    /// Create default auth subkey.
    static void CreateAuthDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_AUTH, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            DWORD val;
            val = 1; RegSetValueExW(hKey, L"Enabled", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 3600; RegSetValueExW(hKey, L"SessionTTLSeconds", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            RegSetValueExW(hKey, L"TokenPath", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Configs\\auth_token.txt",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Configs\\auth_token.txt") + 1) * sizeof(wchar_t)));

            // Default permissions multi-string
            const wchar_t* permissions = L"infer\0status\0context\0";
            RegSetValueExW(hKey, L"DefaultPermissions", 0, REG_MULTI_SZ,
                (const BYTE*)permissions,
                (DWORD)((wcslen(L"infer") + 1 + wcslen(L"status") + 1 + wcslen(L"context") + 1 + 1) * sizeof(wchar_t)));

            RegCloseKey(hKey);
        }
    }

    /// Create default ratelimit subkey.
    static void CreateRateLimitDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_RATELIMIT, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            DWORD val;
            val = 1; RegSetValueExW(hKey, L"Enabled", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 100; RegSetValueExW(hKey, L"InferRPS", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 200; RegSetValueExW(hKey, L"InferBurst", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 10; RegSetValueExW(hKey, L"ModelRPS", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 20; RegSetValueExW(hKey, L"ModelBurst", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 1000; RegSetValueExW(hKey, L"StatusRPS", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 2000; RegSetValueExW(hKey, L"StatusBurst", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 5; RegSetValueExW(hKey, L"AdminRPS", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 10; RegSetValueExW(hKey, L"AdminBurst", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            val = 1000; RegSetValueExW(hKey, L"MaxClients", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            RegCloseKey(hKey);
        }
    }

    /// Create default logs subkey.
    static void CreateLogsDefaults() {
        HKEY hKey = NULL;
        if (RegCreateKeyExW(HKEY_LOCAL_MACHINE, REG_LOGS, 0, NULL,
            REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
            RegSetValueExW(hKey, L"LogDir", 0, REG_SZ,
                (const BYTE*)L"C:\\ProgramData\\AinosOS\\Logs",
                (DWORD)((wcslen(L"C:\\ProgramData\\AinosOS\\Logs") + 1) * sizeof(wchar_t)));
            DWORD val = 100;
            RegSetValueExW(hKey, L"MaxLogSizeMB", 0, REG_DWORD, (const BYTE*)&val, sizeof(val));
            RegCloseKey(hKey);
        }
    }
};

// ============================================================================
// Console Application Entry Point
// ============================================================================

/// Display usage information.
static void ShowUsage() {
    wprintf(L"Ainos OS Registry Configuration Tool\n");
    wprintf(L"\n");
    wprintf(L"Usage:\n");
    wprintf(L"  ainos_registry_config.exe --init            Initialize registry with defaults\n");
    wprintf(L"  ainos_registry_config.exe --reset           Reset registry to defaults\n");
    wprintf(L"  ainos_registry_config.exe --export          Export configuration as TOML\n");
    wprintf(L"  ainos_registry_config.exe --import <file>   Import configuration from TOML\n");
    wprintf(L"  ainos_registry_config.exe --show            Display current configuration\n");
    wprintf(L"  ainos_registry_config.exe --ps-script       Generate PowerShell edit script\n");
    wprintf(L"  ainos_registry_config.exe --help            Show this help\n");
}

/// Display the current configuration.
static void ShowConfiguration() {
    wprintf(L"Ainos OS Configuration (from Registry)\n");
    wprintf(L"========================================\n");
    wprintf(L"InstallDir: %s\n", AinosRegistry::Get_InstallDir().c_str());
    wprintf(L"\n");

    wprintf(L"[Settings]\n");
    wprintf(L"  LogLevel:               %s\n", AinosRegistry::Get_LogLevel().c_str());
    wprintf(L"  EnableLocal:            %s\n", AinosRegistry::Get_EnableLocal() ? L"true" : L"false");
    wprintf(L"  EnableCloud:            %s\n", AinosRegistry::Get_EnableCloud() ? L"true" : L"false");
    wprintf(L"  EnableTLS:              %s\n", AinosRegistry::Get_EnableTLS() ? L"true" : L"false");
    wprintf(L"  NetworkCheckInterval:   %lu\n", AinosRegistry::Get_NetworkCheckInterval());
    wprintf(L"  CloudFallbackConfidence: %lu%%\n", AinosRegistry::Get_CloudFallbackConfidence());
    wprintf(L"  MaxConcurrentInferences: %lu\n", AinosRegistry::Get_MaxConcurrentInferences());
    wprintf(L"  ModelCacheSizeMB:       %lu\n", AinosRegistry::Get_ModelCacheSizeMB());
    wprintf(L"  InferenceTimeoutSecs:   %lu\n", AinosRegistry::Get_InferenceTimeoutSecs());
    wprintf(L"  AuditAllRequests:       %s\n", AinosRegistry::Get_AuditAllRequests() ? L"true" : L"false");
    wprintf(L"\n");

    wprintf(L"[Models]\n");
    wprintf(L"  DefaultModel:           %s\n", AinosRegistry::Get_DefaultModel().c_str());
    wprintf(L"  ModelsDir:              %s\n", AinosRegistry::Get_ModelsDir().c_str());
    wprintf(L"  LocalEngine:            %s\n", AinosRegistry::Get_LocalEngine().c_str());
    wprintf(L"\n");

    wprintf(L"[Paths]\n");
    wprintf(L"  SocketPath:             %s\n", AinosRegistry::Get_SocketPath().c_str());
    wprintf(L"  ContextDir:             %s\n", AinosRegistry::Get_ContextDir().c_str());
    wprintf(L"  AuditLog:               %s\n", AinosRegistry::Get_AuditLog().c_str());
    wprintf(L"  CertPath:               %s\n", AinosRegistry::Get_CertPath().c_str());
    wprintf(L"  KeyPath:                %s\n", AinosRegistry::Get_KeyPath().c_str());
    wprintf(L"\n");

    wprintf(L"[Cloud]\n");
    wprintf(L"  ApiUrl:                 %s\n", AinosRegistry::Get_CloudApiUrl().c_str());
    wprintf(L"  ApiKey:                 %s\n", AinosRegistry::Get_CloudApiKey().empty() ? L"(not set)" : L"********");
    wprintf(L"  CloudModel:             %s\n", AinosRegistry::Get_CloudModel().c_str());
    wprintf(L"\n");

    wprintf(L"[Auth]\n");
    wprintf(L"  Enabled:                %s\n", AinosRegistry::Get_AuthEnabled() ? L"true" : L"false");
    wprintf(L"  TokenPath:              %s\n", AinosRegistry::Get_TokenPath().c_str());
    wprintf(L"  SessionTTLSeconds:      %lu\n", AinosRegistry::Get_SessionTTLSeconds());
    wprintf(L"\n");

    wprintf(L"[RateLimit]\n");
    wprintf(L"  Enabled:                %s\n", AinosRegistry::Get_RateLimitEnabled() ? L"true" : L"false");
    wprintf(L"  InferRPS:               %lu\n", AinosRegistry::Get_RateLimitInferRPS());
    wprintf(L"  InferBurst:             %lu\n", AinosRegistry::Get_RateLimitInferBurst());
    wprintf(L"  ModelRPS:               %lu\n", AinosRegistry::Get_RateLimitModelRPS());
    wprintf(L"  StatusRPS:              %lu\n", AinosRegistry::Get_RateLimitStatusRPS());
    wprintf(L"  MaxClients:             %lu\n", AinosRegistry::Get_RateLimitMaxClients());
    wprintf(L"\n");

    wprintf(L"[Logs]\n");
    wprintf(L"  LogDir:                 %s\n", AinosRegistry::Get_LogDir().c_str());
    wprintf(L"  MaxLogSizeMB:           %lu\n", AinosRegistry::Get_MaxLogSizeMB());
}

int wmain(int argc, wchar_t* argv[]) {
    if (argc < 2) {
        ShowUsage();
        return 1;
    }

    std::wstring arg = argv[1];

    if (arg == L"--init" || arg == L"/init") {
        if (AinosRegistry::Initialize()) {
            wprintf(L"Registry initialized with default values.\n");
            return 0;
        } else {
            wprintf(L"Failed to initialize registry.\n");
            return 1;
        }
    }
    else if (arg == L"--reset" || arg == L"/reset") {
        if (AinosRegistry::ResetToDefaults()) {
            wprintf(L"Registry reset to default values.\n");
            return 0;
        } else {
            wprintf(L"Failed to reset registry.\n");
            return 1;
        }
    }
    else if (arg == L"--export" || arg == L"/export") {
        std::wstring toml = AinosRegistry::ExportToToml();
        fputws(toml.c_str(), stdout);
        return 0;
    }
    else if (arg == L"--import" || arg == L"/import") {
        if (argc < 3) {
            wprintf(L"Usage: ainos_registry_config.exe --import <file.toml>\n");
            return 1;
        }
        if (AinosRegistry::ImportFromToml(argv[2])) {
            wprintf(L"Configuration imported from %s.\n", argv[2]);
            return 0;
        } else {
            wprintf(L"Failed to import configuration from %s.\n", argv[2]);
            return 1;
        }
    }
    else if (arg == L"--show" || arg == L"/show") {
        ShowConfiguration();
        return 0;
    }
    else if (arg == L"--ps-script" || arg == L"/ps-script") {
        std::wstring script = AinosRegistry::GeneratePowerShellEditScript();
        fputws(script.c_str(), stdout);
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