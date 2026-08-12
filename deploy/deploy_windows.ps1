<#!
.SYNOPSIS
Lab Tools OCR 节点（Windows）部署管理脚本。

.DESCRIPTION
使用 NSSM (Non-Sucking Service Manager) 将 ocr_server 注册为 Windows 系统服务，
并支持服务状态的查询、启动、停止、卸载，以及注册开机自启计划任务。

部署完成后，在 Ubuntu 主节点上编辑 deploy/lab-tools.service 的
LAB_TOOLS_OCR_NODE_URL 指向本机即可接入，然后执行：
    sudo bash ./deploy_ubuntu.sh service

.PARAMETER Action
要执行的操作（默认 install）：
- install   : 安装或重装 Windows 服务 (默认值)
- uninstall : 卸载并删除 Windows 服务
- start     : 启动服务
- stop      : 停止服务
- restart   : 重启服务
- status    : 查询当前服务状态
- check     : 预检环境（Python/NSSM/路径是否可用）
- schedule  : 创建开机自启计划任务（SYSTEM 账户，无需登录）

.PARAMETER ServiceName
Windows 服务名（默认 LabToolsOCRService）。

.PARAMETER PythonExe
Python 解释器路径。默认使用 <项目根>\ocr_server\.venv\Scripts\python.exe
（ocr_server.py 强制要求使用其所在目录的 .venv 运行）。

.PARAMETER Port
OCR 服务监听端口（默认 8001，与 Ubuntu 端 LAB_TOOLS_OCR_NODE_URL 默认值一致）。

.PARAMETER NodeName / NodeRole
节点名称与角色（默认 win11 / heavy），用于 health 输出与调度层标识。

.PARAMETER OcrMaxFileMb / OcrMaxPdfPages / OcrTimeoutSec / OcrPdfDpi
OCR 业务参数（默认 100MB / 200页 / 300s / 200DPI）。

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1
# 默认执行 install：安装（或重装）并启动 OCR 服务

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action status
# 查看服务状态

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action schedule
# 创建开机自启计划任务（SYSTEM 账户，用户未登录时也可后台运行）

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action uninstall
# 卸载服务
#>
[CmdletBinding()]
param(
    [ValidateSet("install", "uninstall", "start", "stop", "restart", "status", "check", "schedule")]
    [string]$Action = "install",

    [string]$ServiceName = "LabToolsOCRService",
    [string]$DisplayName = "Lab Tools OCR Service (PaddleOCR CPU)",
    [string]$Description = "Lab Tools OCR Node - PaddleOCR CPU, port 8001",
    [string]$PythonExe,
    [string]$AppScript = "ocr_server.py",
    [string]$Port = "8001",
    [string]$NodeName = "win11",
    [string]$NodeRole = "heavy",
    [string]$OcrMaxFileMb = "100",
    [string]$OcrMaxPdfPages = "200",
    [string]$OcrTimeoutSec = "300",
    [string]$OcrPdfDpi = "200",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message"
}

function Test-ServiceExists {
    param([string]$Name)
    cmd /c "nssm status $Name >nul 2>&1"
    return $LASTEXITCODE -eq 0
}

$deployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $deployDir
$ocrRoot = Join-Path $repoRoot "ocr_server"

if (-not $PythonExe) {
    $PythonExe = Join-Path $ocrRoot ".venv\Scripts\python.exe"
}

if (-not [System.IO.Path]::IsPathRooted($PythonExe)) {
    $PythonExe = Join-Path $repoRoot $PythonExe
}

$appScriptFull = if ([System.IO.Path]::IsPathRooted($AppScript)) {
    $AppScript
}
else {
    Join-Path $ocrRoot $AppScript
}

$logDir = Join-Path $repoRoot "log"
$stdoutLog = Join-Path $logDir "nssm_stdout.log"
$stderrLog = Join-Path $logDir "nssm_stderr.log"

if (-not (Test-Path $ocrRoot)) {
    throw "OCR server directory not found: $ocrRoot"
}

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe`n请先在 ocr_server 目录创建虚拟环境并安装依赖：`n  python -m venv ocr_server\.venv`n  ocr_server\.venv\Scripts\python -m pip install -r ocr_server\requirements_win11.txt"
}

if (-not (Test-Path $appScriptFull)) {
    throw "Application script not found: $appScriptFull"
}

$command = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $command) {
    throw "NSSM was not found in PATH. Please install NSSM first and ensure nssm.exe is available."
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

Write-Info "Action: $Action"
Write-Info "Project root: $repoRoot"
Write-Info "OCR root: $ocrRoot"
Write-Info "Python executable: $PythonExe"
Write-Info "Service name: $ServiceName"

switch ($Action) {
    "check" {
        Write-Success "Pre-check passed. Paths and NSSM are available."
        if (Test-ServiceExists -Name $ServiceName) {
            Write-Info "Service $ServiceName is installed."
        }
        else {
            Write-Warn "Service $ServiceName is not installed yet."
        }
        return
    }

    "status" {
        if (-not (Test-ServiceExists -Name $ServiceName)) {
            Write-Warn "Service $ServiceName is not installed."
            return
        }
        & nssm status $ServiceName
        return
    }

    "start" {
        if (-not (Test-ServiceExists -Name $ServiceName)) {
            throw "Service $ServiceName does not exist."
        }
        Write-Info "Starting service $ServiceName...";
        & nssm start $ServiceName
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to start service $ServiceName."
        }
        Write-Success "Service $ServiceName started."
        return
    }

    "stop" {
        if (-not (Test-ServiceExists -Name $ServiceName)) {
            throw "Service $ServiceName does not exist."
        }
        Write-Info "Stopping service $ServiceName...";
        cmd /c "nssm stop $ServiceName >nul 2>&1"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stop service $ServiceName."
        }
        Write-Success "Service $ServiceName stopped."
        return
    }

    "restart" {
        if (-not (Test-ServiceExists -Name $ServiceName)) {
            throw "Service $ServiceName does not exist."
        }
        Write-Info "Restarting service $ServiceName...";
        cmd /c "nssm restart $ServiceName >nul 2>&1"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to restart service $ServiceName."
        }
        Write-Success "Service $ServiceName restarted."
        return
    }

    "uninstall" {
        if (Test-ServiceExists -Name $ServiceName) {
            Write-Warn "Removing existing service $ServiceName...";
            cmd /c "nssm stop $ServiceName >nul 2>&1"
            cmd /c "nssm remove $ServiceName confirm >nul 2>&1"
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to remove service $ServiceName."
            }
        }
        else {
            Write-Warn "Service $ServiceName is not installed."
        }
        Write-Success "Service $ServiceName removed."
        return
    }

    "schedule" {
        Write-Info "Creating scheduled task to start service $ServiceName at startup..."

        $taskName = "$($ServiceName)Startup"
        $taskDescription = "Starts the $DisplayName service at system startup."
        $taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\deploy_windows.ps1`" -Action start -ServiceName `"$ServiceName`""
        $taskTrigger = New-ScheduledTaskTrigger -AtStartup
        $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable

        Register-ScheduledTask -TaskName $taskName -Description $taskDescription -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -User "SYSTEM" -Force

        Write-Success "Scheduled task $taskName created successfully."
        return
    }
}

Write-Info "Starting Windows OCR service deployment..."

if (Test-ServiceExists -Name $ServiceName) {
    Write-Warn "Service $ServiceName already exists. Reinstalling it..."
    cmd /c "nssm stop $ServiceName >nul 2>&1"
    cmd /c "nssm remove $ServiceName confirm >nul 2>&1"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove existing service $ServiceName."
    }
}

Write-Info "Installing service $ServiceName...";
& nssm install $ServiceName $PythonExe $appScriptFull
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install service $ServiceName."
}

$envExtra = @(
    "NODE_NAME=$NodeName",
    "NODE_ROLE=$NodeRole",
    "PORT=$Port",
    "OCR_MAX_FILE_MB=$OcrMaxFileMb",
    "OCR_MAX_PDF_PAGES=$OcrMaxPdfPages",
    "OCR_TIMEOUT_SEC=$OcrTimeoutSec",
    "OCR_PDF_DPI=$OcrPdfDpi",
    "PYTHONIOENCODING=utf-8",
    "PYTHONUNBUFFERED=1",
    "LANG=zh_CN.UTF-8"
) -join " "

Write-Info "Configuring service settings..."
& nssm set $ServiceName AppDirectory $ocrRoot
& nssm set $ServiceName AppEnvironmentExtra $envExtra
& nssm set $ServiceName Start SERVICE_AUTO_START
& nssm set $ServiceName AppExit Default Restart
& nssm set $ServiceName AppStdout $stdoutLog
& nssm set $ServiceName AppStderr $stderrLog
& nssm set $ServiceName AppStdoutCreationDisposition 2
& nssm set $ServiceName AppStderrCreationDisposition 2
& nssm set $ServiceName AppRotateFiles 1
& nssm set $ServiceName AppRotateSeconds 3600
& nssm set $ServiceName AppRotateOnline 1
& nssm set $ServiceName AppRotateBytes 10485760
& nssm set $ServiceName DisplayName $DisplayName
& nssm set $ServiceName Description $Description

if ($LASTEXITCODE -ne 0) {
    throw "Failed to configure service $ServiceName."
}

if (-not $NoStart) {
    Write-Info "Starting service $ServiceName...";
    & nssm start $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start service $ServiceName."
    }
}
else {
    Write-Warn "Skipping automatic start because -NoStart was supplied."
}

Write-Success "OCR service deployment completed successfully."
Write-Host ""
Write-Host "Service details:"
Write-Host "  Name: $ServiceName"
Write-Host "  Display Name: $DisplayName"
Write-Host "  Python: $PythonExe"
Write-Host "  App Directory: $ocrRoot"
Write-Host "  Port: $Port"
Write-Host "  Stdout Log: $stdoutLog"
Write-Host "  Stderr Log: $stderrLog"
Write-Host "  Encoding: UTF-8"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  nssm start `"$ServiceName`""
Write-Host "  nssm stop `"$ServiceName`""
Write-Host "  nssm restart `"$ServiceName`""
Write-Host "  nssm status `"$ServiceName`""
Write-Host "  nssm edit `"$ServiceName`""
Write-Host "  nssm remove `"$ServiceName`""
Write-Host ""
Write-Host "Ubuntu 主节点接入（将 <本机IP> 替换为本机局域网 IP）："
Write-Host "  编辑 deploy/lab-tools.service 中 LAB_TOOLS_OCR_NODE_URL 为 http://<本机IP>:$Port 后执行："
Write-Host "  sudo bash ./deploy_ubuntu.sh service"