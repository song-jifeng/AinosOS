// Ainos OS - Windows System Tray Tool
//
// This file implements a Windows system tray application for managing the
// Ainos AI Daemon service. It provides a tray icon with a context menu for
// starting/stopping the service, opening the dashboard, and configuring settings.
//
// The application is a Win32 GUI application (SUBSYSTEM:WINDOWS).
// It uses a hidden window with a message loop for tray icon management.
//
// Features:
//   - System tray icon with green/red status indicator
//   - Context menu: Start/Stop Service, Open Dashboard, Settings, About, Exit
//   - Balloon notifications for service events
//   - Service status polling every 5 seconds
//   - Auto-start with Windows registration

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <shellapi.h>
#include <commctrl.h>
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
#include <atomic>
#include <chrono>
#include <thread>
#include <cwchar>
#include <cstring>

// ============================================================================
// Constants
// ============================================================================

// Application
const wchar_t* APP_TITLE = L"Ainos OS";
const wchar_t* WINDOW_CLASS = L"AinosOSTrayWindow";
const wchar_t* TRAY_TOOLTIP_RUNNING = L"Ainos OS - Running";
const wchar_t* TRAY_TOOLTIP_STOPPED = L"Ainos OS - Stopped";

// Registry
const wchar_t* REG_AUTOSTART = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const wchar_t* REG_AUTOSTART_VALUE = L"AinosOSTray";
const wchar_t* REG_AINOS_ROOT = L"SOFTWARE\\AinosOS";

// Named pipe
const wchar_t* PIPE_NAME = L"\\\\.\\pipe\\ainos-daemon";

// Service
const wchar_t* SERVICE_NAME = L"AinosAIDaemon";

// Timer
const UINT_PTR POLL_TIMER_ID = 1;
const UINT POLL_INTERVAL_MS = 5000;

// Icon
const UINT WM_TRAY_ICON = WM_USER + 100;
const DWORD TRAY_ICON_ID = 1;

// Menu IDs
const UINT IDM_START_SERVICE = 1000;
const UINT IDM_STOP_SERVICE = 1001;
const UINT IDM_OPEN_DASHBOARD = 1002;
const UINT IDM_SETTINGS = 1003;
const UINT IDM_AUTOSTART = 1004;
const UINT IDM_ABOUT = 1005;
const UINT IDM_EXIT = 1006;
const UINT IDM_STATUS = 1007;

// Window dimensions (hidden window)
const int HIDDEN_WINDOW_WIDTH = 0;
const int HIDDEN_WINDOW_HEIGHT = 0;

// ============================================================================
// Global State
// ============================================================================

static HINSTANCE g_Instance = NULL;
static HWND g_HiddenWindow = NULL;
static NOTIFYICONDATAW g_TrayIcon = {0};
static HICON g_IconRunning = NULL;
static HICON g_IconStopped = NULL;
static HMENU g_ContextMenu = NULL;
static std::atomic<bool> g_ServiceRunning(false);
static std::atomic<bool> g_AutoStartEnabled(false);
static bool g_Exiting = false;

// ============================================================================
// Forward Declarations
// ============================================================================

LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);
bool InitTrayIcon(HWND hWnd);
void UpdateTrayIcon(bool running);
void ShowContextMenu(HWND hWnd);
void ShowBalloonNotification(const wchar_t* title, const wchar_t* message, DWORD flags);
bool CheckServiceStatus();
bool StartAinosService();
bool StopAinosService();
bool CheckDaemonPipe();
bool ToggleAutoStart();
bool GetAutoStartState();
void OpenDashboard();
void OpenSettings();
void ShowAboutDialog(HWND hWnd);
void CleanupResources();

// ============================================================================
// Icon Creation
// ============================================================================

/// Create a simple colored icon (16x16) for the tray.
/// We create a green icon for "running" and a red icon for "stopped".
static HICON CreateSimpleIcon(COLORREF color) {
    // Create a 16x16 bitmap and draw a filled circle
    HDC hdc = GetDC(NULL);
    HDC hdcMem = CreateCompatibleDC(hdc);

    // Create 16x16 32-bit bitmap
    BITMAPV5HEADER bi = {0};
    bi.bV5Size = sizeof(BITMAPV5HEADER);
    bi.bV5Width = 16;
    bi.bV5Height = 16;
    bi.bV5Planes = 1;
    bi.bV5BitCount = 32;
    bi.bV5Compression = BI_BITFIELDS;
    bi.bV5RedMask = 0x00FF0000;
    bi.bV5GreenMask = 0x0000FF00;
    bi.bV5BlueMask = 0x000000FF;
    bi.bV5AlphaMask = 0xFF000000;

    VOID* bits = NULL;
    HBITMAP hBitmap = CreateDIBSection(hdc, (BITMAPINFO*)&bi, DIB_RGB_COLORS, &bits, NULL, 0);
    if (hBitmap == NULL) {
        ReleaseDC(NULL, hdc);
        return NULL;
    }

    // Draw the icon
    HBITMAP hOldBitmap = (HBITMAP)SelectObject(hdcMem, hBitmap);

    // Fill with transparent
    RECT rect = {0, 0, 16, 16};
    HBRUSH hBrush = CreateSolidBrush(RGB(0, 0, 0));
    FillRect(hdcMem, &rect, hBrush);
    DeleteObject(hBrush);

    // Draw a filled circle with the specified color
    hBrush = CreateSolidBrush(color);
    SelectObject(hdcMem, hBrush);

    // Draw anti-aliased-like circle
    for (int y = 0; y < 16; y++) {
        for (int x = 0; x < 16; x++) {
            int dx = x - 8;
            int dy = y - 8;
            int dist = dx * dx + dy * dy;
            if (dist <= 49) { // radius 7
                SetPixel(hdcMem, x, y, color);
            }
        }
    }

    // Draw a border
    HPEN hPen = CreatePen(PS_SOLID, 1, RGB(0, 0, 0));
    SelectObject(hdcMem, hPen);
    SelectObject(hdcMem, GetStockObject(NULL_BRUSH));
    Ellipse(hdcMem, 1, 1, 15, 15);
    DeleteObject(hPen);

    DeleteObject(hBrush);
    SelectObject(hdcMem, hOldBitmap);

    // Create the icon from the bitmap
    ICONINFO iconInfo = {0};
    iconInfo.fIcon = TRUE;
    iconInfo.hbmMask = hBitmap;
    iconInfo.hbmColor = hBitmap;

    HICON hIcon = CreateIconIndirect(&iconInfo);

    DeleteObject(hBitmap);
    DeleteDC(hdcMem);
    ReleaseDC(NULL, hdc);

    return hIcon;
}

// ============================================================================
// Registry Helpers
// ============================================================================

/// Read a string value from the registry.
static std::wstring RegGetString(HKEY hRootKey, const wchar_t* subKey, const wchar_t* valueName, const wchar_t* defaultValue) {
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

// ============================================================================
// Named Pipe Communication
// ============================================================================

/// Check if the daemon is running by attempting to connect to the named pipe.
static bool CheckDaemonPipe() {
    HANDLE hPipe = CreateFileW(
        PIPE_NAME,
        GENERIC_READ | GENERIC_WRITE,
        0,              // No sharing
        NULL,           // Default security
        OPEN_EXISTING,
        0,              // No overlapped
        NULL            // No template
    );

    if (hPipe == INVALID_HANDLE_VALUE) {
        return false;
    }

    // Set pipe to message read mode
    DWORD pipeMode = PIPE_READMODE_MESSAGE;
    SetNamedPipeHandleState(hPipe, &pipeMode, NULL, NULL);

    // Send status request
    const char* request = "{\"type\":\"Status\"}\n";
    DWORD bytesWritten = 0;
    BOOL success = WriteFile(hPipe, request, (DWORD)strlen(request), &bytesWritten, NULL);

    CloseHandle(hPipe);

    return (success != FALSE && bytesWritten > 0);
}

/// Send a shutdown command to the daemon via named pipe.
static bool SendDaemonShutdown() {
    HANDLE hPipe = CreateFileW(
        PIPE_NAME,
        GENERIC_WRITE,
        0, NULL, OPEN_EXISTING, 0, NULL
    );

    if (hPipe == INVALID_HANDLE_VALUE) {
        return false;
    }

    const char* shutdownMsg = "{\"type\":\"Shutdown\"}\n";
    DWORD bytesWritten = 0;
    WriteFile(hPipe, shutdownMsg, (DWORD)strlen(shutdownMsg), &bytesWritten, NULL);
    CloseHandle(hPipe);

    return true;
}

// ============================================================================
// Service Control
// ============================================================================

/// Check if the Ainos service is running via SCM.
static bool CheckServiceStatus() {
    // First try the named pipe (more accurate)
    if (CheckDaemonPipe()) {
        return true;
    }

    // Fall back to SCM query
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_QUERY_STATUS);
    if (service == NULL) {
        CloseServiceHandle(scm);
        return false;
    }

    SERVICE_STATUS status;
    bool running = false;
    if (QueryServiceStatus(service, &status)) {
        running = (status.dwCurrentState == SERVICE_RUNNING);
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    return running;
}

/// Start the Ainos service.
static bool StartAinosService() {
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_START | SERVICE_QUERY_STATUS);
    if (service == NULL) {
        CloseServiceHandle(scm);
        return false;
    }

    // Check if already running
    SERVICE_STATUS status;
    if (QueryServiceStatus(service, &status) && status.dwCurrentState == SERVICE_RUNNING) {
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return true;
    }

    // Start the service
    if (!StartServiceW(service, 0, NULL)) {
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return false;
    }

    // Wait for service to start (up to 15 seconds)
    for (int i = 0; i < 15; i++) {
        Sleep(1000);
        if (QueryServiceStatus(service, &status) && status.dwCurrentState == SERVICE_RUNNING) {
            CloseServiceHandle(service);
            CloseServiceHandle(scm);
            return true;
        }
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    // Fall back to check if the process is responsive
    return CheckDaemonPipe();
}

/// Stop the Ainos service.
static bool StopAinosService() {
    // First try graceful shutdown via named pipe
    SendDaemonShutdown();

    // Then try SCM stop
    SC_HANDLE scm = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (scm == NULL) {
        return false;
    }

    SC_HANDLE service = OpenServiceW(scm, SERVICE_NAME, SERVICE_STOP | SERVICE_QUERY_STATUS);
    if (service == NULL) {
        CloseServiceHandle(scm);
        // Check if the pipe is still active
        if (CheckDaemonPipe()) {
            return false;
        }
        return true;
    }

    SERVICE_STATUS status;
    if (!ControlService(service, SERVICE_CONTROL_STOP, &status)) {
        DWORD error = GetLastError();
        if (error == ERROR_SERVICE_NOT_ACTIVE) {
            CloseHandle(service);
            CloseServiceHandle(scm);
            return true;
        }
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return false;
    }

    // Wait for service to stop
    for (int i = 0; i < 15; i++) {
        Sleep(1000);
        if (QueryServiceStatus(service, &status) && status.dwCurrentState == SERVICE_STOPPED) {
            CloseServiceHandle(service);
            CloseServiceHandle(scm);
            return true;
        }
    }

    CloseServiceHandle(service);
    CloseServiceHandle(scm);

    return !CheckDaemonPipe();
}

// ============================================================================
// Auto-Start Management
// ============================================================================

/// Check if auto-start with Windows is enabled.
static bool GetAutoStartState() {
    HKEY hKey = NULL;
    LONG status = RegOpenKeyExW(HKEY_CURRENT_USER, REG_AUTOSTART, 0, KEY_READ, &hKey);
    if (status != ERROR_SUCCESS) {
        return false;
    }

    wchar_t value[1024] = {0};
    DWORD valueSize = sizeof(value);
    DWORD type = 0;

    status = RegQueryValueExW(hKey, REG_AUTOSTART_VALUE, NULL, &type, (LPBYTE)value, &valueSize);
    RegCloseKey(hKey);

    return (status == ERROR_SUCCESS && type == REG_SZ && value[0] != L'\0');
}

/// Toggle auto-start with Windows.
static bool ToggleAutoStart() {
    HKEY hKey = NULL;
    LONG status = RegOpenKeyExW(HKEY_CURRENT_USER, REG_AUTOSTART, 0, KEY_SET_VALUE, &hKey);
    if (status != ERROR_SUCCESS) {
        return false;
    }

    bool currentlyEnabled = GetAutoStartState();

    if (currentlyEnabled) {
        // Remove auto-start
        status = RegDeleteValueW(hKey, REG_AUTOSTART_VALUE);
        g_AutoStartEnabled.store(false);
    } else {
        // Add auto-start
        wchar_t modulePath[MAX_PATH];
        GetModuleFileNameW(NULL, modulePath, MAX_PATH);

        // Build the command line with --minimized flag
        std::wstring command = std::wstring(L"\"") + modulePath + L"\" --minimized";

        status = RegSetValueExW(hKey, REG_AUTOSTART_VALUE, 0, REG_SZ,
            (const BYTE*)command.c_str(),
            (DWORD)((command.length() + 1) * sizeof(wchar_t)));
        g_AutoStartEnabled.store(true);
    }

    RegCloseKey(hKey);
    return (status == ERROR_SUCCESS);
}

// ============================================================================
// Dashboard & Settings
// ============================================================================

/// Open the web dashboard in the default browser.
static void OpenDashboard() {
    ShellExecuteW(NULL, L"open", L"http://127.0.0.1:9501", NULL, NULL, SW_SHOWNORMAL);
}

/// Open the settings (registry editor or config file).
static void OpenSettings() {
    // Try to open the config file in notepad, or the registry editor
    std::wstring installDir = RegGetString(HKEY_LOCAL_MACHINE, REG_AINOS_ROOT, L"InstallDir", L"C:\\Program Files\\AinosOS");
    std::wstring configPath = installDir + L"\\configs\\ai-daemon.toml";

    // Check if the config file exists
    DWORD attributes = GetFileAttributesW(configPath.c_str());
    if (attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        // Open with notepad
        ShellExecuteW(NULL, L"open", L"notepad.exe", configPath.c_str(), NULL, SW_SHOWNORMAL);
    } else {
        // Fall back to PowerShell script
        std::wstring psScript = L"powershell.exe -NoProfile -Command \"";
        psScript += L"Write-Host 'Ainos OS Configuration' -ForegroundColor Cyan; ";
        psScript += L"Write-Host 'To edit, run: regedit.exe'";
        psScript += L"\"";

        ShellExecuteW(NULL, L"open", L"powershell.exe",
            (std::wstring(L"-NoProfile -Command \"")
                + L"Write-Host 'Ainos OS Configuration' -ForegroundColor Cyan; "
                + L"Write-Host 'Navigate to: HKLM\\SOFTWARE\\AinosOS'; "
                + L"Write-Host 'Or edit the config file at: ' + '" + configPath + L"'; "
                + L"Start-Process regedit.exe"
                + L"\"").c_str(),
            NULL, SW_SHOWNORMAL);
    }
}

// ============================================================================
// About Dialog
// ============================================================================

/// Show the About dialog.
static void ShowAboutDialog(HWND hWnd) {
    const wchar_t* aboutText =
        L"Ainos OS - AI Native Operating System\n"
        L"\n"
        L"Version: 0.1.0\n"
        L"Platform: Windows\n"
        L"\n"
        L"Ainos OS is an AI-native operating system that integrates\n"
        L"AI capabilities directly into the system kernel and service layer.\n"
        L"\n"
        L"Features:\n"
        L"  - AI daemon service\n"
        L"  - Model lifecycle management\n"
        L"  - Local and cloud inference\n"
        L"  - Context management\n"
        L"  - Semantic caching\n"
        L"  - Thermal-aware power scheduling\n"
        L"\n"
        L"System Tray Tool v1.0";

    MessageBoxW(hWnd, aboutText, L"About Ainos OS", MB_OK | MB_ICONINFORMATION);
}

// ============================================================================
// Tray Icon Management
// ============================================================================

/// Initialize the system tray icon.
static bool InitTrayIcon(HWND hWnd) {
    ZeroMemory(&g_TrayIcon, sizeof(NOTIFYICONDATAW));
    g_TrayIcon.cbSize = sizeof(NOTIFYICONDATAW);
    g_TrayIcon.hWnd = hWnd;
    g_TrayIcon.uID = TRAY_ICON_ID;
    g_TrayIcon.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP;
    g_TrayIcon.uCallbackMessage = WM_TRAY_ICON;
    g_TrayIcon.hIcon = g_IconStopped;

    // Set tooltip
    StringCchCopyW(g_TrayIcon.szTip, 128, TRAY_TOOLTIP_STOPPED);

    // Add the icon
    return Shell_NotifyIconW(NIM_ADD, &g_TrayIcon) != FALSE;
}

/// Update the tray icon based on service status.
static void UpdateTrayIcon(bool running) {
    g_TrayIcon.hIcon = running ? g_IconRunning : g_IconStopped;
    g_TrayIcon.uFlags = NIF_ICON | NIF_TIP | NIF_SHOWTIP;

    StringCchCopyW(g_TrayIcon.szTip, 128,
        running ? TRAY_TOOLTIP_RUNNING : TRAY_TOOLTIP_STOPPED);

    Shell_NotifyIconW(NIM_MODIFY, &g_TrayIcon);
}

/// Show a balloon notification.
static void ShowBalloonNotification(const wchar_t* title, const wchar_t* message, DWORD flags) {
    g_TrayIcon.uFlags = NIF_INFO;
    g_TrayIcon.dwInfoFlags = flags;
    g_TrayIcon.uTimeout = 5000; // 5 seconds

    StringCchCopyW(g_TrayIcon.szInfoTitle, 64, title);
    StringCchCopyW(g_TrayIcon.szInfo, 256, message);

    Shell_NotifyIconW(NIM_MODIFY, &g_TrayIcon);

    // Reset flags
    g_TrayIcon.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP;
}

/// Show the context menu.
static void ShowContextMenu(HWND hWnd) {
    POINT pt;
    GetCursorPos(&pt);

    // Create the popup menu if not already created
    if (g_ContextMenu == NULL) {
        g_ContextMenu = CreatePopupMenu();

        AppendMenuW(g_ContextMenu, MF_STRING, IDM_START_SERVICE, L"Start Ainos Daemon");
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_STOP_SERVICE, L"Stop Ainos Daemon");
        AppendMenuW(g_ContextMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuW(g_ContextMenu, MF_STRING | MF_GRAYED, IDM_STATUS, L"Status: Unknown");
        AppendMenuW(g_ContextMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_OPEN_DASHBOARD, L"Open Dashboard");
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_SETTINGS, L"Settings");
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_AUTOSTART, L"Auto-start with Windows");
        AppendMenuW(g_ContextMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_ABOUT, L"About AinosOS");
        AppendMenuW(g_ContextMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuW(g_ContextMenu, MF_STRING, IDM_EXIT, L"Exit");
    }

    // Update menu items based on current state
    bool running = CheckServiceStatus();
    g_ServiceRunning.store(running);

    // Enable/disable start/stop
    EnableMenuItem(g_ContextMenu, IDM_START_SERVICE, running ? MF_GRAYED : MF_ENABLED);
    EnableMenuItem(g_ContextMenu, IDM_STOP_SERVICE, running ? MF_ENABLED : MF_GRAYED);

    // Update status text
    std::wstring statusText = running ? L"Status: Running" : L"Status: Stopped";
    ModifyMenuW(g_ContextMenu, IDM_STATUS, MF_STRING | MF_GRAYED, IDM_STATUS, statusText.c_str());

    // Update auto-start checkmark
    g_AutoStartEnabled.store(GetAutoStartState());
    CheckMenuItem(g_ContextMenu, IDM_AUTOSTART, g_AutoStartEnabled.load() ? MF_CHECKED : MF_UNCHECKED);

    // Update the tray icon
    UpdateTrayIcon(running);

    // Show the menu
    SetForegroundWindow(hWnd);
    TrackPopupMenu(g_ContextMenu, TPM_LEFTALIGN | TPM_BOTTOMALIGN, pt.x, pt.y, 0, hWnd, NULL);
    PostMessageW(hWnd, WM_NULL, 0, 0);
}

// ============================================================================
// Resource Cleanup
// ============================================================================

/// Clean up all resources.
static void CleanupResources() {
    // Remove the tray icon
    Shell_NotifyIconW(NIM_DELETE, &g_TrayIcon);

    // Destroy the context menu
    if (g_ContextMenu != NULL) {
        DestroyMenu(g_ContextMenu);
        g_ContextMenu = NULL;
    }

    // Destroy icons
    if (g_IconRunning != NULL) {
        DestroyIcon(g_IconRunning);
        g_IconRunning = NULL;
    }
    if (g_IconStopped != NULL) {
        DestroyIcon(g_IconStopped);
        g_IconStopped = NULL;
    }
}

// ============================================================================
// Window Procedure
// ============================================================================

/// Window procedure for the hidden application window.
LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
    case WM_CREATE:
        // Initialize the tray icon
        if (!InitTrayIcon(hWnd)) {
            return -1;
        }

        // Set the polling timer
        SetTimer(hWnd, POLL_TIMER_ID, POLL_INTERVAL_MS, NULL);

        // Check initial service status
        g_ServiceRunning.store(CheckServiceStatus());
        UpdateTrayIcon(g_ServiceRunning.load());

        // Show welcome notification
        if (g_ServiceRunning.load()) {
            ShowBalloonNotification(L"Ainos OS",
                L"Daemon is running",
                NIIF_INFO);
        }

        // Check if we should start minimized (no welcome notification)
        // This is handled by checking command line args in WinMain
        return 0;

    case WM_DESTROY:
        CleanupResources();
        PostQuitMessage(0);
        return 0;

    case WM_TIMER:
        if (wParam == POLL_TIMER_ID) {
            // Poll service status
            bool running = CheckServiceStatus();
            bool wasRunning = g_ServiceRunning.exchange(running);

            if (running != wasRunning) {
                // Service status changed
                UpdateTrayIcon(running);

                if (running) {
                    ShowBalloonNotification(L"Ainos OS",
                        L"Daemon has started",
                        NIIF_INFO);
                } else {
                    ShowBalloonNotification(L"Ainos OS",
                        L"Daemon has stopped",
                        NIIF_WARNING);
                }
            }
        }
        return 0;

    case WM_TRAY_ICON:
        switch (LOWORD(lParam)) {
        case WM_LBUTTONDBLCLK:
            // Double-click: open dashboard
            OpenDashboard();
            break;

        case WM_RBUTTONUP:
        case WM_CONTEXTMENU:
            // Right-click: show context menu
            ShowContextMenu(hWnd);
            break;

        case NIN_BALLOONUSERCLICK:
            // Balloon notification clicked: open dashboard
            OpenDashboard();
            break;
        }
        return 0;

    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDM_START_SERVICE:
            if (StartAinosService()) {
                g_ServiceRunning.store(true);
                UpdateTrayIcon(true);
                ShowBalloonNotification(L"Ainos OS",
                    L"Daemon started successfully",
                    NIIF_INFO);
            } else {
                ShowBalloonNotification(L"Ainos OS",
                    L"Failed to start daemon",
                    NIIF_ERROR);
            }
            break;

        case IDM_STOP_SERVICE:
            if (StopAinosService()) {
                g_ServiceRunning.store(false);
                UpdateTrayIcon(false);
                ShowBalloonNotification(L"Ainos OS",
                    L"Daemon stopped successfully",
                    NIIF_INFO);
            } else {
                ShowBalloonNotification(L"Ainos OS",
                    L"Failed to stop daemon",
                    NIIF_ERROR);
            }
            break;

        case IDM_OPEN_DASHBOARD:
            OpenDashboard();
            break;

        case IDM_SETTINGS:
            OpenSettings();
            break;

        case IDM_AUTOSTART:
            ToggleAutoStart();
            // The menu will be updated next time it's opened
            break;

        case IDM_ABOUT:
            ShowAboutDialog(hWnd);
            break;

        case IDM_EXIT:
            g_Exiting = true;
            DestroyWindow(hWnd);
            break;
        }
        return 0;

    case WM_CLOSE:
        if (!g_Exiting) {
            // Just hide the window instead of closing
            ShowWindow(hWnd, SW_HIDE);
            return 0;
        }
        break;
    }

    return DefWindowProcW(hWnd, message, wParam, lParam);
}

// ============================================================================
// Main Entry Point
// ============================================================================

/// WinMain entry point for the GUI application.
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    UNREFERENCED_PARAMETER(hPrevInstance);
    UNREFERENCED_PARAMETER(lpCmdLine);
    UNREFERENCED_PARAMETER(nCmdShow);

    g_Instance = hInstance;

    // Parse command line for --minimized flag
    bool startMinimized = false;
    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv != NULL) {
        for (int i = 1; i < argc; i++) {
            if (wcscmp(argv[i], L"--minimized") == 0) {
                startMinimized = true;
            }
            else if (wcscmp(argv[i], L"--start-service") == 0) {
                // Start the service and exit
                StartAinosService();
                LocalFree(argv);
                return 0;
            }
            else if (wcscmp(argv[i], L"--stop-service") == 0) {
                // Stop the service and exit
                StopAinosService();
                LocalFree(argv);
                return 0;
            }
            else if (wcscmp(argv[i], L"--status") == 0) {
                // Check status and print to console
                bool running = CheckServiceStatus();
                wprintf(L"Ainos OS Daemon: %s\n", running ? L"Running" : L"Stopped");
                LocalFree(argv);
                return running ? 0 : 1;
            }
        }
        LocalFree(argv);
    }

    // Initialize common controls
    INITCOMMONCONTROLSEX icex = {0};
    icex.dwSize = sizeof(INITCOMMONCONTROLSEX);
    icex.dwICC = ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&icex);

    // Create icons
    g_IconRunning = CreateSimpleIcon(RGB(0, 204, 68));   // Green
    g_IconStopped = CreateSimpleIcon(RGB(204, 68, 68));  // Red

    if (g_IconRunning == NULL || g_IconStopped == NULL) {
        MessageBoxW(NULL, L"Failed to create tray icons", L"Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // Register the window class
    WNDCLASSW wc = {0};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = WINDOW_CLASS;
    wc.hbrBackground = (HBRUSH)GetStockObject(NULL_BRUSH);

    if (!RegisterClassW(&wc)) {
        CleanupResources();
        MessageBoxW(NULL, L"Failed to register window class", L"Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // Create the hidden window
    g_HiddenWindow = CreateWindowExW(
        0,
        WINDOW_CLASS,
        APP_TITLE,
        WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT,
        HIDDEN_WINDOW_WIDTH, HIDDEN_WINDOW_HEIGHT,
        NULL, NULL,
        hInstance,
        NULL
    );

    if (g_HiddenWindow == NULL) {
        CleanupResources();
        MessageBoxW(NULL, L"Failed to create hidden window", L"Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // Show the window (hidden)
    ShowWindow(g_HiddenWindow, SW_HIDE);

    // If not starting minimized, show a welcome
    if (!startMinimized) {
        // The welcome notification will be shown in WM_CREATE
    }

    // Message loop
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    // Cleanup
    CleanupResources();

    return (int)msg.wParam;
}