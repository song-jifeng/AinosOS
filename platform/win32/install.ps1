<#
.SYNOPSIS
    Ainos OS Windows Installer
.DESCRIPTION
    Installs the Ainos OS AI Daemon on Windows, including:
    - Service installation
    - Registry configuration
    - Firewall rules
    - PATH environment variable
    - Desktop shortcut
    - Uninstall support
.NOTES
    Requires Administrator privileges.
    Version: 1.0
#>

#Requires -RunAsAdministrator

param(
    [switch]$Uninstall,
    [switch]$Silent,
    [string]$InstallDir = "C:\Program Files\AinosOS",
    [string]$DataDir = "C:\ProgramData\AinosOS",
    [string]$ConfigSource = ""
)

# ============================================================================
# Configuration
# ============================================================================

$Script:ProductName = "Ainos OS"
$Script:ServiceName = "AinosAIDaemon"
$Script:ServiceDisplayName = "Ainos OS AI Daemon"
$Script:RegistryRoot = "HKLM:\SOFTWARE\AinosOS"
$Script:UninstallKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\AinosOS"
$Script:StartMenuDir = [Environment]::GetFolderPath("CommonStartMenu") + "\Programs\AinosOS"
$Script:DesktopDir = [Environment]::GetFolderPath("CommonDesktop")

# Component paths
$Script:BinDir = "$InstallDir\bin"
$Script:ConfigDir = "$InstallDir\configs"
$Script:ModelsDir = "$DataDir\Models"
$Script:LogsDir = "$DataDir\Logs"
$Script:DataDirPath = "$DataDir\Data"
$Script:ContextsDir = "$DataDir\Data\Contexts"
$Script:CertsDir = "$DataDir\Certs"
$Script:ConfigsDir = "$DataDir\Configs"

# ============================================================================
# Helper Functions
# ============================================================================

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = @{
        "INFO" = "Green"
        "WARN" = "Yellow"
        "ERROR" = "Red"
        "STEP" = "Cyan"
    }
    $c = $color[$Level]
    if (-not $c) { $c = "White" }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $c
}

function Exit-WithError {
    param([string]$Message)
    Write-Log -Message $Message -Level "ERROR"
    if (-not $Silent) {
        Write-Host "Press any key to exit..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
    exit 1
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ScriptPath {
    if ($MyInvocation.MyCommand.Path) {
        return Split-Path $MyInvocation.MyCommand.Path -Parent
    }
    return $PSScriptRoot
}

function New-DirectoryIfNotExist {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
        Write-Log -Message "Created directory: $Path" -Level "INFO"
    }
}

# ============================================================================
# Installation Functions
# ============================================================================

function Install-Directories {
    Write-Log -Message "Creating directories..." -Level "STEP"

    $directories = @(
        $InstallDir,
        $BinDir,
        $ConfigDir,
        $DataDir,
        $ModelsDir,
        $LogsDir,
        $DataDirPath,
        $ContextsDir,
        $CertsDir,
        $ConfigsDir
    )

    foreach ($dir in $directories) {
        New-DirectoryIfNotExist -Path $dir
    }
}

function Install-Files {
    param([string]$SourcePath)

    Write-Log -Message "Installing files..." -Level "STEP"

    $scriptRoot = Get-ScriptPath

    # If no source path specified, try to find files relative to the script
    if ([string]::IsNullOrEmpty($SourcePath)) {
        # Try typical locations
        $possiblePaths = @(
            "$scriptRoot\..\..",  # Two levels up from platform/win32
            "$scriptRoot\..",     # One level up from win32
            "$env:USERPROFILE\Ainos",
            "D:\Ainos"
        )

        foreach ($p in $possiblePaths) {
            $resolved = Resolve-Path $p -ErrorAction SilentlyContinue
            if ($resolved -and (Test-Path "$resolved\system-services\ai-daemon\target\release\ai-daemon.exe")) {
                $SourcePath = $resolved
                break
            }
        }

        if ([string]::IsNullOrEmpty($SourcePath)) {
            Write-Log -Message "Could not find Ainos source files. Please specify -ConfigSource <path>." -Level "WARN"
            Write-Log -Message "You will need to manually copy the daemon binary to $BinDir" -Level "WARN"
            return
        }
    }

    Write-Log -Message "Using source path: $SourcePath" -Level "INFO"

    # Copy the daemon binary
    $daemonExe = "$SourcePath\system-services\ai-daemon\target\release\ai-daemon.exe"
    if (Test-Path $daemonExe) {
        Copy-Item -Path $daemonExe -Destination "$BinDir\ai-daemon.exe" -Force
        Write-Log -Message "Installed ai-daemon.exe" -Level "INFO"
    } else {
        Write-Log -Message "ai-daemon.exe not found at $daemonExe. Build it first: cd system-services/ai-daemon && cargo build --release" -Level "WARN"
    }

    # Copy the service wrapper
    $serviceExe = "$SourcePath\platform\win32\build\ainos_service.exe"
    if (Test-Path $serviceExe) {
        Copy-Item -Path $serviceExe -Destination "$BinDir\ainos_service.exe" -Force
        Write-Log -Message "Installed ainos_service.exe" -Level "INFO"
    }

    # Copy the tray tool
    $trayExe = "$SourcePath\platform\win32\build\ainos_tray.exe"
    if (Test-Path $trayExe) {
        Copy-Item -Path $trayExe -Destination "$BinDir\ainos_tray.exe" -Force
        Write-Log -Message "Installed ainos_tray.exe" -Level "INFO"
    }

    # Copy the registry config tool
    $regConfigExe = "$SourcePath\platform\win32\build\ainos_registry_config.exe"
    if (Test-Path $regConfigExe) {
        Copy-Item -Path $regConfigExe -Destination "$BinDir\ainos_registry_config.exe" -Force
        Write-Log -Message "Installed ainos_registry_config.exe" -Level "INFO"
    }

    # Copy the config file
    $configFile = "$SourcePath\configs\ai-daemon.toml"
    if (Test-Path $configFile) {
        Copy-Item -Path $configFile -Destination "$ConfigDir\ai-daemon.toml" -Force

        # Update the config file paths for Windows
        $config = Get-Content "$ConfigDir\ai-daemon.toml" -Raw
        $config = $config -replace 'models_dir = ".*"', "models_dir = `"$ModelsDir`""
        $config = $config -replace 'socket_path = ".*"', 'socket_path = "\\.\pipe\ainos-daemon"'
        $config = $config -replace 'context_dir = ".*"', "context_dir = `"$ContextsDir`""
        $config = $config -replace 'audit_log = ".*"', "audit_log = `"$LogsDir\audit.log`""
        $config = $config -replace 'tls_cert_path = ".*"', "tls_cert_path = `"$CertsDir\server.crt`""
        $config = $config -replace 'tls_key_path = ".*"', "tls_key_path = `"$CertsDir\server.key`""
        $config = $config -replace 'token_path = ".*"', "token_path = `"$ConfigsDir\auth_token.txt`""
        $config = $config -replace 'audit_log_path = ".*"', "audit_log_path = `"$LogsDir\audit.log`""

        $config | Set-Content "$ConfigDir\ai-daemon.toml" -Force
        Write-Log -Message "Installed and configured ai-daemon.toml" -Level "INFO"
    } else {
        Write-Log -Message "Config file not found at $configFile. Creating default config..." -Level "WARN"
        Create-DefaultConfig
    }

    # Copy the Python scripts
    $trayPy = "$SourcePath\scripts\ainos_tray.py"
    if (Test-Path $trayPy) {
        Copy-Item -Path $trayPy -Destination "$BinDir\ainos_tray.py" -Force
        Write-Log -Message "Installed ainos_tray.py" -Level "INFO"
    }

    # Copy the PowerShell edit script
    $psScript = @"
<#
.SYNOPSIS
    Edit Ainos OS configuration
#>
#Requires -RunAsAdministrator
`$RegRoot = "HKLM:\SOFTWARE\AinosOS"
Write-Host "Ainos OS Configuration Editor" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current Configuration:" -ForegroundColor Yellow
Get-ChildItem -Path `$RegRoot -Recurse | ForEach-Object {
    Write-Host "[`$(`$_.PSPath)]" -ForegroundColor Green
    Get-ItemProperty -Path `$_.PSPath | ForEach-Object {
        `$_.PSObject.Properties | Where-Object { `$_.Name -notlike "PS*" } | ForEach-Object {
            Write-Host "  `$(`$_.Name) = `$(`$_.Value)"
        }
    }
}
"@
    $psScript | Out-File -FilePath "$BinDir\edit-config.ps1" -Encoding utf8 -Force
}

function Create-DefaultConfig {
    $defaultConfig = @"
# Ainos AI Daemon Configuration
# Auto-generated by Windows Installer

models_dir = "$ModelsDir"
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
socket_path = "\\.\pipe\ainos-daemon"

# Local inference
enable_local = true
local_engine = "ggml"
max_concurrent_inferences = 2
model_cache_size_mb = 4096
inference_timeout_secs = 120

# Cloud fallback (Weelink Platform)
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = ""
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6

# Context management
context_dir = "$ContextsDir"
max_contexts = 1000
context_ttl_days = 30

# Logging
log_level = "debug"
audit_log = "$LogsDir\audit.log"
audit_all_requests = true

# Legacy TLS settings (deprecated, use [tls] section)
enable_tls = false
tls_cert_path = "$CertsDir\server.crt"
tls_key_path = "$CertsDir\server.key"

[auth]
enabled = true
token = ""
token_path = "$ConfigsDir\auth_token.txt"
session_ttl_seconds = 3600
permissions_file = ""
default_permissions = ["infer", "status", "context"]
audit_log_path = "$LogsDir\audit.log"
audit_all_requests = true

[ratelimit]
enabled = true
infer_rps = 100.0
infer_burst = 200.0
model_rps = 10.0
model_burst = 20.0
status_rps = 1000.0
status_burst = 2000.0
admin_rps = 5.0
admin_burst = 10.0
max_clients = 1000
cleanup_interval_secs = 300

[tls]
enabled = false
cert_path = "$CertsDir\server.crt"
key_path = "$CertsDir\server.key"
verify_client = false
"@

    $defaultConfig | Out-File -FilePath "$ConfigDir\ai-daemon.toml" -Encoding utf8 -Force
    Write-Log -Message "Created default config file" -Level "INFO"
}

function Install-Service {
    Write-Log -Message "Installing Windows service..." -Level "STEP"

    $servicePath = "$BinDir\ainos_service.exe"
    if (-not (Test-Path $servicePath)) {
        Write-Log -Message "Service executable not found at $servicePath. Will register a direct service for ai-daemon.exe." -Level "WARN"

        # Install the daemon directly as a service
        $daemonPath = "$BinDir\ai-daemon.exe"
        if (-not (Test-Path $daemonPath)) {
            Exit-WithError "ai-daemon.exe not found. Cannot install service."
        }

        $binaryPath = "`"$daemonPath`" -c `"$ConfigDir\ai-daemon.toml`""

        # Check if service already exists
        $existingService = Get-Service -Name $Script:ServiceName -ErrorAction SilentlyContinue
        if ($existingService) {
            Write-Log -Message "Service already exists. Stopping and reconfiguring..." -Level "WARN"
            Stop-Service -Name $Script:ServiceName -Force -ErrorAction SilentlyContinue
            sc.exe delete $Script:ServiceName | Out-Null
            Start-Sleep -Seconds 2
        }

        # Create the service
        sc.exe create $Script:ServiceName `
            binPath= $binaryPath `
            displayName= $Script:ServiceDisplayName `
            type= own `
            start= auto `
            error= normal

        if ($LASTEXITCODE -ne 0) {
            Exit-WithError "Failed to create service (sc.exe returned $LASTEXITCODE)"
        }

        # Set description
        sc.exe description $Script:ServiceName "Core AI service manager for Ainos OS. Provides model lifecycle management, inference routing, context management, and system resource monitoring."

        # Set recovery options
        sc.exe failure $Script:ServiceName reset= 86400 actions= restart/30000/restart/60000/restart/120000

        Write-Log -Message "Service installed directly for ai-daemon.exe" -Level "INFO"
    } else {
        # Use the service wrapper
        & $servicePath --install
        if ($LASTEXITCODE -ne 0) {
            Exit-WithError "Failed to install service via wrapper"
        }
        Write-Log -Message "Service installed via wrapper" -Level "INFO"
    }
}

function Install-Registry {
    Write-Log -Message "Configuring registry..." -Level "STEP"

    # Create registry structure
    $regPaths = @(
        $Script:RegistryRoot,
        "$Script:RegistryRoot\Settings",
        "$Script:RegistryRoot\Models",
        "$Script:RegistryRoot\Paths",
        "$Script:RegistryRoot\Cloud",
        "$Script:RegistryRoot\Auth",
        "$Script:RegistryRoot\RateLimit",
        "$Script:RegistryRoot\Logs"
    )

    foreach ($path in $regPaths) {
        if (-not (Test-Path $path)) {
            New-Item -Path $path -Force | Out-Null
        }
    }

    # Set values
    Set-ItemProperty -Path $Script:RegistryRoot -Name "InstallDir" -Value $InstallDir -Type String
    Set-ItemProperty -Path $Script:RegistryRoot -Name "ConfigVersion" -Value 1 -Type DWord

    # Settings
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "LogLevel" -Value "debug" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "EnableLocal" -Value 1 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "EnableCloud" -Value 1 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "EnableTLS" -Value 0 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "NetworkCheckInterval" -Value 30 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "CloudFallbackConfidence" -Value 60 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "MaxConcurrentInferences" -Value 2 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "ModelCacheSizeMB" -Value 4096 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "InferenceTimeoutSecs" -Value 120 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "AuditAllRequests" -Value 1 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Settings" -Name "Verbose" -Value 0 -Type DWord

    # Models
    Set-ItemProperty -Path "$Script:RegistryRoot\Models" -Name "DefaultModel" -Value "qwen2.5-0.5b-instruct-q4.gguf" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Models" -Name "ModelsDir" -Value $ModelsDir -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Models" -Name "LocalEngine" -Value "ggml" -Type String

    # Paths
    Set-ItemProperty -Path "$Script:RegistryRoot\Paths" -Name "SocketPath" -Value "\\.\pipe\ainos-daemon" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Paths" -Name "ContextDir" -Value $ContextsDir -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Paths" -Name "AuditLog" -Value "$LogsDir\audit.log" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Paths" -Name "CertPath" -Value "$CertsDir\server.crt" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Paths" -Name "KeyPath" -Value "$CertsDir\server.key" -Type String

    # Cloud
    Set-ItemProperty -Path "$Script:RegistryRoot\Cloud" -Name "ApiUrl" -Value "https://api.weelinking.com/v1" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Cloud" -Name "ApiKey" -Value "" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Cloud" -Name "CloudModel" -Value "gpt-5.6-sol" -Type String

    # Auth
    Set-ItemProperty -Path "$Script:RegistryRoot\Auth" -Name "Enabled" -Value 1 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Auth" -Name "TokenPath" -Value "$ConfigsDir\auth_token.txt" -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Auth" -Name "SessionTTLSeconds" -Value 3600 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\Auth" -Name "DefaultPermissions" -Value @("infer", "status", "context") -Type MultiString

    # RateLimit
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "Enabled" -Value 1 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "InferRPS" -Value 100 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "InferBurst" -Value 200 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "ModelRPS" -Value 10 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "ModelBurst" -Value 20 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "StatusRPS" -Value 1000 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "StatusBurst" -Value 2000 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "AdminRPS" -Value 5 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "AdminBurst" -Value 10 -Type DWord
    Set-ItemProperty -Path "$Script:RegistryRoot\RateLimit" -Name "MaxClients" -Value 1000 -Type DWord

    # Logs
    Set-ItemProperty -Path "$Script:RegistryRoot\Logs" -Name "LogDir" -Value $LogsDir -Type String
    Set-ItemProperty -Path "$Script:RegistryRoot\Logs" -Name "MaxLogSizeMB" -Value 100 -Type DWord

    Write-Log -Message "Registry configured successfully" -Level "INFO"
}

function Install-FirewallRules {
    Write-Log -Message "Configuring firewall rules..." -Level "STEP"

    # Check if the rule already exists
    $existingRule = Get-NetFirewallRule -DisplayName "Ainos OS AI Daemon" -ErrorAction SilentlyContinue
    if ($existingRule) {
        Write-Log -Message "Firewall rule already exists" -Level "INFO"
        return
    }

    try {
        # Allow inbound TCP on port 9500 (for TCP fallback)
        New-NetFirewallRule -DisplayName "Ainos OS AI Daemon" `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort 9500 `
            -Action Allow `
            -Profile Any `
            -Description "Allow inbound TCP connections to the Ainos OS AI Daemon" `
            -ErrorAction SilentlyContinue

        Write-Log -Message "Firewall rule added for TCP port 9500" -Level "INFO"
    } catch {
        Write-Log -Message "Failed to add firewall rule: $_" -Level "WARN"
        Write-Log -Message "You may need to add it manually or run the installer as Administrator" -Level "WARN"
    }
}

function Install-EnvironmentPath {
    Write-Log -Message "Adding to PATH environment variable..." -Level "STEP"

    try {
        $currentPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($currentPath -notlike "*$BinDir*") {
            $newPath = $currentPath + ";$BinDir"
            [Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
            Write-Log -Message "Added $BinDir to system PATH" -Level "INFO"

            # Also update current session
            $env:Path = $env:Path + ";$BinDir"
        } else {
            Write-Log -Message "$BinDir already in PATH" -Level "INFO"
        }
    } catch {
        Write-Log -Message "Failed to update PATH: $_" -Level "WARN"
    }
}

function Install-Shortcuts {
    Write-Log -Message "Creating shortcuts..." -Level "STEP"

    # Create Start Menu directory
    New-DirectoryIfNotExist -Path $Script:StartMenuDir

    # Create shortcuts using WScript.Shell COM object
    $shell = New-Object -ComObject WScript.Shell

    # Start Menu shortcuts
    $shortcutPaths = @{
        "$Script:StartMenuDir\Ainos OS Dashboard.lnk" = @{
            TargetPath = "$BinDir\ainos_tray.exe"
            Arguments = ""
            Description = "Open Ainos OS Dashboard"
        }
        "$Script:StartMenuDir\Ainos OS Service Manager.lnk" = @{
            TargetPath = "$BinDir\ainos_service.exe"
            Arguments = "--status"
            Description = "Ainos OS Service Manager"
        }
        "$Script:StartMenuDir\Ainos OS Edit Config.lnk" = @{
            TargetPath = "powershell.exe"
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$BinDir\edit-config.ps1`""
            Description = "Edit Ainos OS Configuration"
        }
        "$Script:StartMenuDir\Ainos OS Uninstall.lnk" = @{
            TargetPath = "powershell.exe"
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Script:InstallScriptPath`" -Uninstall"
            Description = "Uninstall Ainos OS"
        }
    }

    foreach ($shortcut, $info in $shortcutPaths.GetEnumerator()) {
        $link = $shell.CreateShortcut($shortcut)
        $link.TargetPath = $info.TargetPath
        $link.Arguments = $info.Arguments
        $link.Description = $info.Description
        $link.WorkingDirectory = $InstallDir
        $link.Save()
        Write-Log -Message "Created shortcut: $shortcut" -Level "INFO"
    }

    # Desktop shortcut (only if --desktop-shortcut is implied)
    $desktopShortcut = "$Script:DesktopDir\Ainos OS.lnk"
    if (-not (Test-Path $desktopShortcut)) {
        $link = $shell.CreateShortcut($desktopShortcut)
        $link.TargetPath = "$BinDir\ainos_tray.exe"
        $link.Description = "Ainos OS - AI Native Operating System"
        $link.WorkingDirectory = $InstallDir
        $link.Save()
        Write-Log -Message "Created desktop shortcut" -Level "INFO"
    }

    # Auto-start with Windows (tray tool)
    $regAutoStart = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $trayToolPath = "$BinDir\ainos_tray.exe --minimized"
    if (Test-Path "$BinDir\ainos_tray.exe") {
        Set-ItemProperty -Path $regAutoStart -Name "AinosOSTray" -Value $trayToolPath -Type String
        Write-Log -Message "Registered tray tool for auto-start" -Level "INFO"
    }
}

function Install-UninstallEntry {
    Write-Log -Message "Creating uninstall registry entry..." -Level "STEP"

    $uninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Script:InstallScriptPath`" -Uninstall"

    # Create uninstall key
    if (-not (Test-Path $Script:UninstallKey)) {
        New-Item -Path $Script:UninstallKey -Force | Out-Null
    }

    Set-ItemProperty -Path $Script:UninstallKey -Name "DisplayName" -Value "Ainos OS" -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "DisplayVersion" -Value "0.1.0" -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "Publisher" -Value "Ainos Project" -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "InstallLocation" -Value $InstallDir -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "UninstallString" -Value $uninstallString -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "DisplayIcon" -Value "$BinDir\ainos_tray.exe,0" -Type String
    Set-ItemProperty -Path $Script:UninstallKey -Name "EstimatedSize" -Value 50000 -Type DWord
    Set-ItemProperty -Path $Script:UninstallKey -Name "NoModify" -Value 1 -Type DWord
    Set-ItemProperty -Path $Script:UninstallKey -Name "NoRepair" -Value 1 -Type DWord

    Write-Log -Message "Uninstall entry created" -Level "INFO"
}

# ============================================================================
# Uninstall Functions
# ============================================================================

function Uninstall-Service {
    Write-Log -Message "Uninstalling service..." -Level "STEP"

    try {
        $service = Get-Service -Name $Script:ServiceName -ErrorAction SilentlyContinue
        if ($service) {
            Write-Log -Message "Stopping service..." -Level "INFO"
            Stop-Service -Name $Script:ServiceName -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2

            # Try the service wrapper first
            $serviceWrapper = "$BinDir\ainos_service.exe"
            if (Test-Path $serviceWrapper) {
                & $serviceWrapper --uninstall
            } else {
                sc.exe delete $Script:ServiceName
            }
            Write-Log -Message "Service uninstalled" -Level "INFO"
        } else {
            Write-Log -Message "Service not installed" -Level "INFO"
        }
    } catch {
        Write-Log -Message "Failed to uninstall service: $_" -Level "WARN"
    }
}

function Uninstall-Registry {
    Write-Log -Message "Removing registry entries..." -Level "STEP"

    try {
        if (Test-Path $Script:RegistryRoot) {
            Remove-Item -Path $Script:RegistryRoot -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log -Message "Registry keys removed" -Level "INFO"
        }

        if (Test-Path $Script:UninstallKey) {
            Remove-Item -Path $Script:UninstallKey -Recurse -Force -ErrorAction SilentlyContinue
        }

        # Remove auto-start
        $regAutoStart = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        Remove-ItemProperty -Path $regAutoStart -Name "AinosOSTray" -ErrorAction SilentlyContinue
    } catch {
        Write-Log -Message "Failed to remove registry entries: $_" -Level "WARN"
    }
}

function Uninstall-FirewallRules {
    Write-Log -Message "Removing firewall rules..." -Level "STEP"

    try {
        $rule = Get-NetFirewallRule -DisplayName "Ainos OS AI Daemon" -ErrorAction SilentlyContinue
        if ($rule) {
            Remove-NetFirewallRule -DisplayName "Ainos OS AI Daemon" -ErrorAction SilentlyContinue
            Write-Log -Message "Firewall rules removed" -Level "INFO"
        }
    } catch {
        Write-Log -Message "Failed to remove firewall rules: $_" -Level "WARN"
    }
}

function Uninstall-Shortcuts {
    Write-Log -Message "Removing shortcuts..." -Level "STEP"

    try {
        # Remove Start Menu folder
        if (Test-Path $Script:StartMenuDir) {
            Remove-Item -Path $Script:StartMenuDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log -Message "Start Menu shortcuts removed" -Level "INFO"
        }

        # Remove Desktop shortcut
        $desktopShortcut = "$Script:DesktopDir\Ainos OS.lnk"
        if (Test-Path $desktopShortcut) {
            Remove-Item -Path $desktopShortcut -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Log -Message "Failed to remove shortcuts: $_" -Level "WARN"
    }
}

function Uninstall-EnvironmentPath {
    Write-Log -Message "Removing from PATH environment variable..." -Level "STEP"

    try {
        $currentPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($currentPath -like "*$BinDir*") {
            $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $BinDir }) -join ";"
            [Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
            Write-Log -Message "Removed $BinDir from system PATH" -Level "INFO"
        }
    } catch {
        Write-Log -Message "Failed to update PATH: $_" -Level "WARN"
    }
}

function Uninstall-Files {
    Write-Log -Message "Removing installed files..." -Level "STEP"

    try {
        # Ask user if they want to remove data files
        $removeData = $Silent
        if (-not $Silent) {
            $response = Read-Host "Remove all data files (models, logs, contexts)? [y/N]"
            $removeData = ($response -eq "y" -or $response -eq "Y")
        }

        if ($removeData -and (Test-Path $DataDir)) {
            Remove-Item -Path $DataDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log -Message "Data directory removed" -Level "INFO"
        }

        # Remove install directory
        if (Test-Path $InstallDir) {
            Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log -Message "Install directory removed" -Level "INFO"
        }
    } catch {
        Write-Log -Message "Failed to remove files: $_" -Level "WARN"
    }
}

# ============================================================================
# Main Installation Logic
# ============================================================================

function Main {
    Write-Log -Message "========================================" -Level "STEP"
    Write-Log -Message "  Ainos OS Windows Installer" -Level "STEP"
    Write-Log -Message "========================================" -Level "STEP"
    Write-Log -Message "" -Level "STEP"

    # Check for Administrator privileges
    if (-not (Test-Administrator)) {
        Exit-WithError "This script requires Administrator privileges. Please run as Administrator."
    }

    # Save the install script path for uninstall
    $Script:InstallScriptPath = $MyInvocation.MyCommand.Path

    if ($Uninstall) {
        Write-Log -Message "Starting uninstall..." -Level "STEP"
        Write-Log -Message "" -Level "STEP"

        Uninstall-Service
        Uninstall-FirewallRules
        Uninstall-Shortcuts
        Uninstall-EnvironmentPath
        Uninstall-Registry
        Uninstall-Files

        Write-Log -Message "========================================" -Level "STEP"
        Write-Log -Message "  Ainos OS uninstalled successfully" -Level "STEP"
        Write-Log -Message "========================================" -Level "STEP"
    } else {
        Write-Log -Message "Starting installation..." -Level "STEP"
        Write-Log -Message "Install directory: $InstallDir" -Level "INFO"
        Write-Log -Message "Data directory: $DataDir" -Level "INFO"
        Write-Log -Message "" -Level "STEP"

        # Run installation steps
        Install-Directories
        Install-Files -SourcePath $ConfigSource
        Install-Registry
        Install-Service
        Install-FirewallRules
        Install-EnvironmentPath
        Install-Shortcuts
        Install-UninstallEntry

        Write-Log -Message "========================================" -Level "STEP"
        Write-Log -Message "  Ainos OS installed successfully" -Level "STEP"
        Write-Log -Message "========================================" -Level "STEP"
        Write-Log -Message "" -Level "STEP"
        Write-Log -Message "Next steps:" -Level "INFO"
        Write-Log -Message "  1. Place your model files in: $ModelsDir" -Level "INFO"
        Write-Log -Message "  2. Start the service: Start-Service $Script:ServiceName" -Level "INFO"
        Write-Log -Message "  3. Launch the system tray: $BinDir\ainos_tray.exe" -Level "INFO"
        Write-Log -Message "  4. Open the dashboard: http://127.0.0.1:9501" -Level "INFO"
        Write-Log -Message "" -Level "STEP"
        Write-Log -Message "To configure, run: $BinDir\edit-config.ps1" -Level "INFO"
        Write-Log -Message "To uninstall, run: install.ps1 -Uninstall" -Level "INFO"
    }

    if (-not $Silent) {
        Write-Host ""
        Write-Host "Press any key to continue..." -ForegroundColor Cyan
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
}

# Run main
Main