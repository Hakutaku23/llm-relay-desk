[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop")]
    [string] $Action,

    [Parameter(Mandatory = $true)]
    [string] $PidFile,

    [Parameter(Mandatory = $true)]
    [string] $LogFile
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RequiredEnvironmentValue {
    param([Parameter(Mandatory = $true)][string] $Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "缺少配置项：$Name"
    }

    return $value.Trim()
}

function Get-OptionalEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [string] $DefaultValue = ""
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }

    return $value.Trim()
}

function Assert-SafeSshConfigValue {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][string] $Value
    )

    if ($Value.Contains("`r") -or $Value.Contains("`n") -or $Value.Contains('"')) {
        throw "$Name 包含不允许的换行或双引号。"
    }
}

function Convert-ToPositiveInteger {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][string] $Value,
        [int] $Maximum = 65535
    )

    $parsed = 0
    if (-not [int]::TryParse($Value, [ref] $parsed)) {
        throw "$Name 必须是整数。"
    }

    if ($parsed -lt 1 -or $parsed -gt $Maximum) {
        throw "$Name 必须处于 1-$Maximum。"
    }

    return $parsed
}

function Convert-ToWindowsCommandLineArgument {
    param([Parameter(Mandatory = $true)][string] $Value)

    if ($Value.Length -eq 0) {
        return '""'
    }

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    # Windows CommandLineToArgvW-compatible escaping.
    $builder = New-Object System.Text.StringBuilder
    [void] $builder.Append('"')
    $backslashCount = 0

    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashCount++
            continue
        }

        if ($character -eq '"') {
            [void] $builder.Append(('\' * (($backslashCount * 2) + 1)))
            [void] $builder.Append('"')
            $backslashCount = 0
            continue
        }

        if ($backslashCount -gt 0) {
            [void] $builder.Append(('\' * $backslashCount))
            $backslashCount = 0
        }

        [void] $builder.Append($character)
    }

    if ($backslashCount -gt 0) {
        [void] $builder.Append(('\' * ($backslashCount * 2)))
    }

    [void] $builder.Append('"')
    return $builder.ToString()
}

function Test-TcpConnection {
    param(
        [Parameter(Mandatory = $true)][string] $HostName,
        [Parameter(Mandatory = $true)][int] $Port,
        [int] $TimeoutMilliseconds = 500
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $asyncResult = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }

        $client.EndConnect($asyncResult)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Stop-RecordedTunnel {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }

    $rawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $processId = 0

    if ([int]::TryParse($rawPid, [ref] $processId)) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.ProcessName -ieq "ssh") {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "已关闭 SSH 隧道进程 PID=$processId"
        }
    }

    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

if ($Action -eq "Stop") {
    Stop-RecordedTunnel
    exit 0
}

$sshCommand = Get-Command "ssh.exe" -ErrorAction Stop
$sshExecutable = $sshCommand.Source

$jumpHost = Get-RequiredEnvironmentValue "SSH_JUMP_HOST"
$jumpUser = Get-RequiredEnvironmentValue "SSH_JUMP_USER"
$jumpPort = Convert-ToPositiveInteger "SSH_JUMP_PORT" (
    Get-OptionalEnvironmentValue "SSH_JUMP_PORT" "22"
)
$jumpIdentity = Get-OptionalEnvironmentValue "SSH_JUMP_IDENTITY_FILE"

$targetHost = Get-RequiredEnvironmentValue "SSH_TARGET_HOST"
$targetUser = Get-RequiredEnvironmentValue "SSH_TARGET_USER"
$targetPort = Convert-ToPositiveInteger "SSH_TARGET_PORT" (
    Get-OptionalEnvironmentValue "SSH_TARGET_PORT" "22"
)
$targetIdentity = Get-OptionalEnvironmentValue "SSH_TARGET_IDENTITY_FILE"

$localPort = Convert-ToPositiveInteger "SSH_LOCAL_PORT" (
    Get-OptionalEnvironmentValue "SSH_LOCAL_PORT" "11435"
)
$remoteHost = Get-OptionalEnvironmentValue "VLLM_REMOTE_HOST" "127.0.0.1"
$remotePort = Convert-ToPositiveInteger "VLLM_REMOTE_PORT" (
    Get-OptionalEnvironmentValue "VLLM_REMOTE_PORT" "8000"
)

$connectTimeout = Convert-ToPositiveInteger "SSH_CONNECT_TIMEOUT_SECONDS" (
    Get-OptionalEnvironmentValue "SSH_CONNECT_TIMEOUT_SECONDS" "15"
) 300
$aliveInterval = Convert-ToPositiveInteger "SSH_SERVER_ALIVE_INTERVAL" (
    Get-OptionalEnvironmentValue "SSH_SERVER_ALIVE_INTERVAL" "30"
) 3600
$aliveCountMax = Convert-ToPositiveInteger "SSH_SERVER_ALIVE_COUNT_MAX" (
    Get-OptionalEnvironmentValue "SSH_SERVER_ALIVE_COUNT_MAX" "3"
) 100
$strictHostKeyChecking = Get-OptionalEnvironmentValue `
    "SSH_STRICT_HOST_KEY_CHECKING" "accept-new"

$configValues = @{
    SSH_JUMP_HOST = $jumpHost
    SSH_JUMP_USER = $jumpUser
    SSH_TARGET_HOST = $targetHost
    SSH_TARGET_USER = $targetUser
    VLLM_REMOTE_HOST = $remoteHost
    SSH_STRICT_HOST_KEY_CHECKING = $strictHostKeyChecking
}

foreach ($item in $configValues.GetEnumerator()) {
    Assert-SafeSshConfigValue $item.Key $item.Value
}

foreach ($identity in @($jumpIdentity, $targetIdentity)) {
    if (-not [string]::IsNullOrWhiteSpace($identity)) {
        Assert-SafeSshConfigValue "SSH identity file" $identity
        if (-not (Test-Path -LiteralPath $identity -PathType Leaf)) {
            throw "SSH 密钥文件不存在：$identity"
        }
    }
}

$runtimeDirectory = Split-Path -Parent $PidFile
if ([string]::IsNullOrWhiteSpace($runtimeDirectory)) {
    throw "PID 文件必须包含目录。"
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$logDirectory = Split-Path -Parent $LogFile
if (-not [string]::IsNullOrWhiteSpace($logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}

Stop-RecordedTunnel

if (Test-TcpConnection -HostName "127.0.0.1" -Port $localPort) {
    throw "本机端口 $localPort 已被其他程序占用。"
}

$generatedConfig = Join-Path $runtimeDirectory "ssh_config.generated"
$stdoutLog = Join-Path $runtimeDirectory "ssh_tunnel.stdout.log"

function Convert-ToSshPath {
    param([Parameter(Mandatory = $true)][string] $PathValue)
    return $PathValue.Replace("\", "/")
}

$configLines = New-Object System.Collections.Generic.List[string]
$configLines.Add("Host llm-relay-jump")
$configLines.Add("    HostName $jumpHost")
$configLines.Add("    User $jumpUser")
$configLines.Add("    Port $jumpPort")
$configLines.Add("    BatchMode yes")
$configLines.Add("    StrictHostKeyChecking $strictHostKeyChecking")
if (-not [string]::IsNullOrWhiteSpace($jumpIdentity)) {
    $configLines.Add(
        '    IdentityFile "' + (Convert-ToSshPath $jumpIdentity) + '"'
    )
    $configLines.Add("    IdentitiesOnly yes")
}

$configLines.Add("")
$configLines.Add("Host llm-relay-vllm")
$configLines.Add("    HostName $targetHost")
$configLines.Add("    User $targetUser")
$configLines.Add("    Port $targetPort")
$configLines.Add("    ProxyJump llm-relay-jump")
$configLines.Add("    BatchMode yes")
$configLines.Add("    StrictHostKeyChecking $strictHostKeyChecking")
if (-not [string]::IsNullOrWhiteSpace($targetIdentity)) {
    $configLines.Add(
        '    IdentityFile "' + (Convert-ToSshPath $targetIdentity) + '"'
    )
    $configLines.Add("    IdentitiesOnly yes")
}

[System.IO.File]::WriteAllLines(
    $generatedConfig,
    $configLines,
    (New-Object System.Text.UTF8Encoding($false))
)

$forwardSpec = "127.0.0.1:${localPort}:${remoteHost}:${remotePort}"
$arguments = @(
    "-F", $generatedConfig,
    "-N",
    "-T",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ConnectTimeout=$connectTimeout",
    "-o", "ServerAliveInterval=$aliveInterval",
    "-o", "ServerAliveCountMax=$aliveCountMax",
    "-o", "TCPKeepAlive=yes",
    "-L", $forwardSpec,
    "llm-relay-vllm"
)

Remove-Item -LiteralPath $LogFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stdoutLog -Force -ErrorAction SilentlyContinue

$argumentLine = (
    $arguments |
        ForEach-Object { Convert-ToWindowsCommandLineArgument ([string] $_) }
) -join " "

$process = Start-Process `
    -FilePath $sshExecutable `
    -ArgumentList $argumentLine `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $LogFile `
    -PassThru

[System.IO.File]::WriteAllText(
    $PidFile,
    $process.Id.ToString(),
    (New-Object System.Text.UTF8Encoding($false))
)

$deadline = [DateTime]::UtcNow.AddSeconds($connectTimeout)

while ([DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 250
    $process.Refresh()

    if ($process.HasExited) {
        $details = ""
        if (Test-Path -LiteralPath $LogFile) {
            $details = (Get-Content -LiteralPath $LogFile -Raw).Trim()
        }

        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        if ([string]::IsNullOrWhiteSpace($details)) {
            throw "SSH 进程提前退出，退出代码：$($process.ExitCode)"
        }

        throw "SSH 进程提前退出：`n$details"
    }

    if (Test-TcpConnection -HostName "127.0.0.1" -Port $localPort) {
        Write-Host (
            "SSH 隧道已建立：127.0.0.1:{0} -> {1}:{2}（经 {3}）" -f
            $localPort,
            $remoteHost,
            $remotePort,
            $jumpHost
        )
        Write-Host "SSH 进程 PID=$($process.Id)"
        exit 0
    }
}

Stop-RecordedTunnel
throw "SSH 隧道在 $connectTimeout 秒内未能监听本机端口 $localPort。"
