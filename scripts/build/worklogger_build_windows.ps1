param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\", "/")
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "This script only supports Windows."
}

$AppName = "WorkLogger"
$SpecFile = Join-Path $ProjectRoot "worklogger.spec"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$VenvDir = Join-Path $ProjectRoot ".venv_build"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
$I18NCompileScript = Join-Path $ProjectRoot "scripts\i18n\i18n_compile.py"
$TargetExe = Join-Path $DistDir "$AppName.exe"
$OnedirOutput = Join-Path $DistDir $AppName
$LogDir = Join-Path $ProjectRoot "build_logs"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$script:LogFile = Join-Path $LogDir "build_windows_$Timestamp.log"
$BuildPython = $null

if (-not (Test-Path -LiteralPath $LogDir -PathType Container)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
"" | Set-Content -LiteralPath $script:LogFile -Encoding utf8

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy/MM/dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $script:LogFile -Value $line -Encoding utf8
}

function Resolve-PathWithinProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $resolved = [System.IO.Path]::GetFullPath($Path)
    $projectPrefix = "$ProjectRoot\"
    if ($resolved -ne $ProjectRoot -and -not $resolved.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside project root: $resolved"
    }
    return $resolved
}

function Format-CommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )
    $parts = @($FilePath) + $Arguments
    return ($parts | ForEach-Object {
            if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ }
        }) -join " "
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $cmdLine = Format-CommandLine -FilePath $FilePath -Arguments $Arguments
    Write-Log "RUN  : $Description"
    Write-Log "CMD  : $cmdLine"

    & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $script:LogFile -Append | Out-Host
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
    Write-Log "OK   : $Description"
}

function Invoke-ExternalWithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $false)]
        [int]$MaxAttempts = 3,
        [Parameter(Mandatory = $false)]
        [int]$DelaySeconds = 5
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Invoke-External -Description "$Description (attempt $attempt/$MaxAttempts)" -FilePath $FilePath -Arguments $Arguments
            return
        }
        catch {
            if ($attempt -ge $MaxAttempts) {
                throw "$Description failed after $MaxAttempts attempts. Last error: $($_.Exception.Message)"
            }
            Write-Log "WARN : $Description failed on attempt $attempt. Retrying in $DelaySeconds seconds."
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Remove-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $false)]
        [int]$MaxAttempts = 3,
        [Parameter(Mandatory = $false)]
        [int]$DelaySeconds = 2
    )

    $resolved = Resolve-PathWithinProject -Path $Path
    if (-not (Test-Path -LiteralPath $resolved)) {
        return
    }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            if (Test-Path -LiteralPath $resolved -PathType Container) {
                Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
            }
            else {
                Remove-Item -LiteralPath $resolved -Force -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $resolved) {
                throw "Path still exists after deletion attempt."
            }
            return
        }
        catch {
            if ($attempt -ge $MaxAttempts) {
                throw "Failed to remove path: $resolved. $($_.Exception.Message)"
            }
            Write-Log "WARN : Failed to remove '$resolved' on attempt $attempt/$MaxAttempts. Retrying in $DelaySeconds seconds."
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

try {
    Write-Log "============================================================"
    Write-Log "WorkLogger Windows onefile build started"
    Write-Log "Project root : $ProjectRoot"
    Write-Log "Spec file    : $SpecFile"
    Write-Log "Target EXE   : $TargetExe"
    Write-Log "Log file     : $script:LogFile"
    Write-Log "============================================================"

    if (-not (Test-Path -LiteralPath $SpecFile -PathType Leaf)) {
        throw "Spec file not found: $SpecFile"
    }
    if (-not (Test-Path -LiteralPath $I18NCompileScript -PathType Leaf)) {
        throw "i18n compile script not found: $I18NCompileScript"
    }

    $pythonCmd = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
    if (-not (Get-Command $pythonCmd -ErrorAction SilentlyContinue)) {
        throw "Python was not found. Install Python 3.10+ or set PYTHON_BIN."
    }

    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
    $env:PIP_NO_INPUT = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONUTF8 = "1"

    Invoke-External -Description "Validate host Python" -FilePath $pythonCmd -Arguments @("--version")

    $needVenvRebuild = $false
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        $needVenvRebuild = $true
    }
    if (-not (Test-Path -LiteralPath $VenvPip -PathType Leaf)) {
        if (-not $needVenvRebuild) {
            Write-Log "WARN : Existing build virtual environment is unhealthy (pip executable is missing). Recreating it."
        }
        $needVenvRebuild = $true
    }

    if ($needVenvRebuild) {
        if (Test-Path -LiteralPath $VenvDir) {
            Write-Log "RUN  : Remove broken/incomplete virtual environment"
            Remove-PathIfExists -Path $VenvDir
            Write-Log "OK   : Remove broken/incomplete virtual environment"
        }
        Invoke-External -Description "Create build virtual environment" -FilePath $pythonCmd -Arguments @("-m", "venv", $VenvDir)
    }

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Build virtual environment is missing python executable: $VenvPython"
    }
    if (-not (Test-Path -LiteralPath $VenvPip -PathType Leaf)) {
        throw "Build virtual environment is missing pip executable: $VenvPip"
    }

    $BuildPython = $VenvPython
    Write-Log "OK   : Using build virtual environment: $VenvDir"
    Write-Log "OK   : Build Python executable: $BuildPython"

    Invoke-ExternalWithRetry -Description "Upgrade pip/setuptools/wheel" -FilePath $BuildPython -Arguments @("-m", "pip", "install", "--timeout", "60", "--retries", "2", "--upgrade", "pip", "setuptools", "wheel")
    Invoke-ExternalWithRetry -Description "Install packaging dependencies (PyInstaller, certifi)" -FilePath $BuildPython -Arguments @("-m", "pip", "install", "--no-cache-dir", "--timeout", "60", "--retries", "2", "pyinstaller", "certifi")

    $requirementsFile = Join-Path $ProjectRoot "requirements.txt"
    if (Test-Path -LiteralPath $requirementsFile -PathType Leaf) {
        $filteredRequirementsFile = Join-Path $ProjectRoot ".tmp_requirements_build_$Timestamp.txt"
        $filteredLines = New-Object System.Collections.Generic.List[string]
        $llamaRequirement = "llama-cpp-python>=0.2.90"
        foreach ($line in Get-Content -LiteralPath $requirementsFile) {
            $trimmed = $line.Trim()
            if ($trimmed -match '^\s*llama-cpp-python(\b|[<>=!~])') {
                $llamaRequirement = $trimmed
                continue
            }
            [void]$filteredLines.Add($line)
        }
        if ($filteredLines.Count -eq 0) {
            throw "No requirements remain after excluding llama-cpp-python from the general dependency install."
        }
        $filteredLines | Set-Content -LiteralPath $filteredRequirementsFile -Encoding utf8
        try {
            Invoke-ExternalWithRetry -Description "Install application dependencies (excluding local-model runtime)" -FilePath $BuildPython -Arguments @("-m", "pip", "install", "--no-cache-dir", "--timeout", "60", "--retries", "2", "-r", $filteredRequirementsFile)
        }
        finally {
            Remove-PathIfExists -Path $filteredRequirementsFile
        }

        # Install local-model runtime from prebuilt CPU wheels to avoid source build on machines without MSVC/nmake.
        Invoke-ExternalWithRetry -Description "Install llama-cpp-python prebuilt CPU wheel" -FilePath $BuildPython -Arguments @(
            "-m", "pip", "install",
            "--no-cache-dir",
            "--timeout", "60",
            "--retries", "2",
            "--prefer-binary",
            "--only-binary", "llama-cpp-python",
            "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu",
            $llamaRequirement
        )
    }
    else {
        Write-Log "WARN : requirements.txt not found. Skipping dependency installation."
    }

    Invoke-External -Description "Compile gettext catalogs (.po -> .mo)" -FilePath $BuildPython -Arguments @($I18NCompileScript)

    if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
    }

    Write-Log "RUN  : Cleanup previous build artifacts"
    Remove-PathIfExists -Path $BuildDir
    Remove-PathIfExists -Path $TargetExe
    Remove-PathIfExists -Path $OnedirOutput
    Write-Log "OK   : Cleanup previous build artifacts"

    Invoke-External -Description "Run PyInstaller from spec" -FilePath $BuildPython -Arguments @(
        "-m",
        "PyInstaller",
        $SpecFile,
        "--clean",
        "--noconfirm",
        "--distpath",
        $DistDir,
        "--workpath",
        $BuildDir
    )

    if (-not (Test-Path -LiteralPath $TargetExe -PathType Leaf)) {
        throw "Expected artifact missing: $TargetExe"
    }
    if (Test-Path -LiteralPath $OnedirOutput -PathType Container) {
        throw "Unexpected onedir output detected: $OnedirOutput. Windows build must remain onefile."
    }

    $artifact = Get-Item -LiteralPath $TargetExe -ErrorAction Stop
    if ($artifact.Length -le 0) {
        throw "Artifact size is zero bytes: $TargetExe"
    }

    $header = [byte[]]::new(2)
    $stream = [System.IO.File]::OpenRead($TargetExe)
    try {
        $read = $stream.Read($header, 0, 2)
    }
    finally {
        $stream.Dispose()
    }
    if ($read -ne 2 -or $header[0] -ne 0x4D -or $header[1] -ne 0x5A) {
        throw "Artifact type validation failed: expected PE/MZ executable."
    }

    if (Test-Path -LiteralPath $BuildDir -PathType Container) {
        Write-Log "RUN  : Cleanup build work directory after success"
        Remove-PathIfExists -Path $BuildDir
        Write-Log "OK   : Cleanup build work directory after success"
    }

    Write-Log "SUCCESS: Windows onefile build completed."
    Write-Log "SUCCESS: Artifact verified at $TargetExe ($($artifact.Length) bytes)."
    Write-Log "SUCCESS: Detailed log saved to $script:LogFile."
    exit 0
}
catch {
    Write-Log "FAILED : $($_.Exception.Message)"
    Write-Log "FAILED : Detailed log saved to $script:LogFile"
    exit 1
}
