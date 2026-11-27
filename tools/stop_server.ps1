# Phone Clock 서버 종료
#  - 이 폴더의 server.py 를 실행 중인 python/pythonw 프로세스
#  - config.json 포트(기본 8790)를 점유 중인 python/pythonw 프로세스
param([switch]$Quiet)

$base = Split-Path -Parent $PSScriptRoot
$script = Join-Path $base 'server.py'
$port = 8790
try { $port = [int]((Get-Content (Join-Path $base 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json).port) } catch {}

$ids = @()
$ids += Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($script) } |
    ForEach-Object { $_.ProcessId }
$ids += Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
    Where-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -in 'python', 'pythonw' } |
    ForEach-Object { $_.OwningProcess }
$ids = $ids | Sort-Object -Unique

foreach ($id in $ids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
if (-not $Quiet) {
    if ($ids) { Write-Output "Phone Clock 서버를 종료했습니다." } else { Write-Output "실행 중인 서버가 없습니다." }
}
