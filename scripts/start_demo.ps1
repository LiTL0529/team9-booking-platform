$ErrorActionPreference = "Stop"
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
$env:AWS_PROFILE = "booking-deploy"
$env:AWS_REGION = "ap-southeast-1"
$env:AWS_PAGER = ""
$env:PYTHONUTF8 = "1"
$env:TERRAFORM = Join-Path $repoPath ".local\tools\terraform\terraform.exe"
$env:TF_CLI_CONFIG_FILE = Join-Path $repoPath ".local\tools\terraform\tf.rc"

aws sts get-caller-identity --profile booking-deploy
if ($LASTEXITCODE -ne 0) { throw "Refresh the booking-deploy CLI credentials, then retry." }
Get-Content -LiteralPath (Join-Path $repoPath ".local\aws.env") -Encoding utf8 | ForEach-Object {
    if ($_ -match "^[^#=]+=") {
        $envName, $envValue = $_ -split "=", 2
        Set-Item -LiteralPath "env:$envName" -Value $envValue
    }
}
$demoPw = (Get-Content -LiteralPath (Join-Path $repoPath ".local\demo-password.txt") -Raw -Encoding utf8).Trim()
foreach ($envName in @("PLATFORM_ADMIN_PASSWORD", "PARTNER_PASSWORD", "LOAD_PASSWORD", "SMOKE_PASSWORD")) {
    Set-Item -LiteralPath "env:$envName" -Value $demoPw
}
& .venv\Scripts\python.exe -X utf8 scripts\aws_deploy.py scale --tasks 2
if ($LASTEXITCODE -ne 0) { throw "The environment did not resume; inspect the command error." }
Write-Host "Tasks requested. Wait for all five ECS services to stabilize before the demo."
