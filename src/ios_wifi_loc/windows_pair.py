from __future__ import annotations

import re
from urllib.parse import urlparse

_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::\d{1,5})?$")


class ToolError(ValueError):
    pass


WINDOWS_PAIR_STEP1_PS = """python -m pip install pymobiledevice3==11.63.1
pymobiledevice3 lockdown pair
pymobiledevice3 amfi enable-developer-mode
"""

WINDOWS_PAIR_STEP2_PS = """pymobiledevice3 lockdown pair
pymobiledevice3 lockdown wifi-connections on
"""

WINDOWS_PAIR_UPLOAD_PS = r"""$dir = 'C:\ProgramData\Apple\Lockdown'
if (-not (Test-Path $dir)) { throw ('找不到配对目录：' + $dir + '。请确认已安装 Apple Devices 或 iTunes，并已完成配对。') }
$files = @()
$sysPath = Join-Path $dir 'SystemConfiguration.plist'
if (Test-Path -LiteralPath $sysPath) {
  $bytes = [IO.File]::ReadAllBytes($sysPath)
  $files += @{ filename = 'SystemConfiguration.plist'; content_base64 = [Convert]::ToBase64String($bytes) }
}
$udid = Get-ChildItem -LiteralPath $dir -Filter '*.plist' -File | Where-Object { $_.Name -ne 'SystemConfiguration.plist' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($udid) {
  $bytes = [IO.File]::ReadAllBytes($udid.FullName)
  $files += @{ filename = $udid.Name; content_base64 = [Convert]::ToBase64String($bytes) }
}
if ($files.Count -lt 1) { throw '目录里没有可上传的 .plist 文件。' }
Write-Host ('正在上传 ' + (($files | ForEach-Object { $_.filename }) -join '、') + ' 到 ' + $server + ' ...')
$body = @{ files = @($files) } | ConvertTo-Json -Depth 5 -Compress
$uri = $server + '/api/pairing/import'
if ($token) { $uri = $uri + '?token=' + [uri]::EscapeDataString($token) }
try {
  $resp = Invoke-RestMethod -Method Post -Uri $uri -ContentType 'application/json; charset=utf-8' -Body $body
  Write-Host '上传成功。'
  if ($resp.summary) { Write-Host $resp.summary }
  if ($resp.pairing) { Write-Host ('服务器已保存 ' + $resp.pairing.count + ' 个配对文件。现在可以回到网页刷新查看。') }
} catch { throw ('上传失败：' + $_.Exception.Message) }
""".strip() + "\n"

def powershell_bat_commands(script: str, *, last: bool = False) -> str:
    """Turn a PowerShell snippet into powershell -Command fragments for a .bat file."""
    parts: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts.append(f'  "{line} " ^')
    if not parts:
        return ""
    if last:
        parts[-1] = parts[-1][:-2]
    return "\n".join(parts)


def server_base_from_host(host: str, *, scheme: str = "http") -> str:
    raw = (host or "").strip()
    if not raw or not _HOST.fullmatch(raw):
        raise ToolError("无法从请求里得到有效的服务器地址")
    hostname = raw.split(":", 1)[0].lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        # Still allow LAN tools when the user opened the page on localhost.
        pass
    checked_scheme = "https" if scheme == "https" else "http"
    return f"{checked_scheme}://{raw}"


def render_windows_pair_bat(server: str) -> str:
    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("服务器地址无效")
    base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    upload = powershell_bat_commands("$token = $env:IOS_WIFI_LOC_TOKEN\n" + WINDOWS_PAIR_UPLOAD_PS)
    # UTF-8 BOM helps Windows notepad/cmd display Chinese when chcp 65001 is set.
    script = f"""@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "IOS_WIFI_LOC_SERVER={base}"
echo ========================================
echo  OpenWrt 无线虚拟定位 - Windows 一键配对
echo  将把配对文件上传到 %IOS_WIFI_LOC_SERVER%
echo ========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $server=$env:IOS_WIFI_LOC_SERVER; function Say([string]$m){{ Write-Host $m }}; " ^
  "function Get-IosWifiPython {{ foreach($c in @('python','py')){{ $cmd=Get-Command $c -ErrorAction SilentlyContinue; if(-not $cmd){{ continue }}; if($cmd.Source -match 'WindowsApps'){{ continue }}; try{{ & $c -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,9) else 1)' 2>$null; if($LASTEXITCODE -eq 0){{ return $c }} }} catch {{}} }}; return $null }}; " ^
  "function Refresh-Path {{ $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User') }}; " ^
  "Say '正在检查 Python...'; $py=Get-IosWifiPython; " ^
  "if(-not $py){{ Say '没有找到 Python 3.9+，正在用 winget 安装 Python 3.12...'; try{{ winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements }} catch {{ Say 'winget 未能自动安装 Python，请手动安装 Python 3.12 后重试。'; exit 1 }}; if($LASTEXITCODE -ne 0){{ Say 'winget 未能自动安装 Python，请手动安装 Python 3.12 后重试。'; exit 1 }}; Refresh-Path; $py=Get-IosWifiPython; if(-not $py){{ Say '已安装 Python，但当前窗口还找不到。请关闭窗口后重新运行本工具。'; exit 1 }} }}; " ^
  "Say ('已找到 Python：' + $py); Say '正在安装 pymobiledevice3==11.63.1 ...'; & $py -m pip install --user --disable-pip-version-check pymobiledevice3==11.63.1; if($LASTEXITCODE -ne 0){{ Say '安装 pymobiledevice3 失败。'; exit 1 }}; " ^
  "Say ''; Say '请用 USB 连接 iPhone，在手机上点「信任」，必要时暂时关闭锁屏密码。'; pause; " ^
  "Say '正在配对 (lockdown pair)...'; & $py -m pymobiledevice3 lockdown pair; if($LASTEXITCODE -ne 0){{ Say '配对失败。请确认已点信任，并再试一次。'; exit 1 }}; " ^
  "Say '如需开启开发者模式，请在下一提示时确认（需要暂时关闭密码）。'; $ans=Read-Host '现在开启开发者模式？(Y/n)'; if($ans -notmatch '^[Nn]'){{ & $py -m pymobiledevice3 amfi enable-developer-mode; Say '若提示失败，请关闭密码后重试，并在手机上完成「开发者模式」重启确认。' }}; " ^
  "Say '正在开启 Wi-Fi 连接...'; & $py -m pymobiledevice3 lockdown wifi-connections on; " ^
{upload}
  "Say ''; Say '配对完成。可以把手机从 USB 拔出，连同一局域网 Wi-Fi，在网页里选择设备并设置定位。';"
if errorlevel 1 (
  echo.
  echo 过程没有完成，请根据上面的说明处理后重新运行。
) else (
  echo.
  echo 全部完成。
)
echo.
pause
endlocal
"""
    return script
