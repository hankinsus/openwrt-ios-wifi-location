from __future__ import annotations

import base64
import re
from urllib.parse import urlparse

_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::\d{1,5})?$")

# Unique separator line (a cmd.exe comment). The extractor stub must not contain
# this literal; it rebuilds the string in pieces and uses LastIndexOf.
PS_MARKER = "::IOS_WIFI_LOC_BEGIN_PS1"
PS_MARKER_PREFIX = "::IOS_WIFI_LOC"
PS_MARKER_SUFFIX = "_BEGIN_PS1"

# ASCII stub: read this .bat as UTF-8 and iex everything after the last marker.
PS_EXTRACTOR = (
    "$p=$env:IOS_WIFI_LOC_SELF\n"
    "if(-not $p){ Write-Host 'embedded script missing'; exit 1 }\n"
    "$s=Get-Content -LiteralPath $p -Raw -Encoding UTF8\n"
    f"$k=('{PS_MARKER_PREFIX}'+'{PS_MARKER_SUFFIX}')\n"
    "$i=$s.LastIndexOf($k)\n"
    "if($i -lt 0){ Write-Host 'embedded script missing'; exit 1 }\n"
    "iex $s.Substring($i+$k.Length)\n"
)

class ToolError(ValueError):
    pass


WINDOWS_PAIR_STEP1_PS = """python -m pip install pymobiledevice3==11.63.1
pymobiledevice3 lockdown pair
pymobiledevice3 amfi enable-developer-mode
"""

WINDOWS_PAIR_STEP2_PS = """pymobiledevice3 lockdown pair
pymobiledevice3 lockdown wifi-connections on
"""

WINDOWS_PAIR_PS_BODY = r"""$ErrorActionPreference = 'Stop'
$server = $env:IOS_WIFI_LOC_SERVER
$token = $env:IOS_WIFI_LOC_TOKEN

function Say([string]$m) { Write-Host $m }

function Get-IosWifiPython {
  foreach ($c in @('python', 'py')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    if ($cmd.Source -match 'WindowsApps') { continue }
    try {
      & $c -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,9) else 1)' 2>$null
      if ($LASTEXITCODE -eq 0) { return $c }
    } catch {}
  }
  return $null
}

function Refresh-Path {
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
}

try {
  Say '正在检查 Python...'
  $py = Get-IosWifiPython
  if (-not $py) {
    Say '没有找到 Python 3.9+，正在用 winget 安装 Python 3.12...'
    try {
      winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    } catch {
      Say 'winget 未能自动安装 Python，请手动安装 Python 3.12 后重试。'
      exit 1
    }
    if ($LASTEXITCODE -ne 0) {
      Say 'winget 未能自动安装 Python，请手动安装 Python 3.12 后重试。'
      exit 1
    }
    Refresh-Path
    $py = Get-IosWifiPython
    if (-not $py) {
      Say '已安装 Python，但当前窗口还找不到。请关闭窗口后重新运行本工具。'
      exit 1
    }
  }
  Say ('已找到 Python：' + $py)
  Say '正在安装 pymobiledevice3==11.63.1 ...'
  & $py -m pip install --user --disable-pip-version-check pymobiledevice3==11.63.1
  if ($LASTEXITCODE -ne 0) {
    Say '安装 pymobiledevice3 失败。'
    exit 1
  }
  Say ''
  Say '请用 USB 连接 iPhone，在手机上点「信任」，必要时暂时关闭锁屏密码。'
  Read-Host 'Press Enter after you have tapped Trust on the iPhone'
  Say '正在配对 (lockdown pair)...'
  & $py -m pymobiledevice3 lockdown pair
  if ($LASTEXITCODE -ne 0) {
    Say '配对失败。请确认已点信任，并再试一次。'
    exit 1
  }
  Say '如需开启开发者模式，请在下一提示时确认（需要暂时关闭密码）。'
  $ans = Read-Host '现在开启开发者模式？(Y/n)'
  if ($ans -notin @('n', 'N')) {
    & $py -m pymobiledevice3 amfi enable-developer-mode
    Say '若提示失败，请关闭密码后重试，并在手机上完成「开发者模式」重启确认。'
  }
  Say '正在开启 Wi-Fi 连接...'
  & $py -m pymobiledevice3 lockdown wifi-connections on

  $dir = 'C:\ProgramData\Apple\Lockdown'
  if (-not (Test-Path $dir)) {
    throw ('找不到配对目录：' + $dir + '。请确认已安装 Apple Devices 或 iTunes，并已完成配对。')
  }
  $files = @()
  # Upload SystemConfiguration.plist plus every UDID plist, not just the newest file.
  Get-ChildItem -LiteralPath $dir -Filter '*.plist' -File | Sort-Object { if ($_.Name -eq 'SystemConfiguration.plist') { 0 } else { 1 } }, Name | ForEach-Object {
    $bytes = [IO.File]::ReadAllBytes($_.FullName)
    $files += @{ filename = $_.Name; content_base64 = [Convert]::ToBase64String($bytes) }
  }
  if ($files.Count -lt 1) { throw '目录里没有可上传的 .plist 文件。' }
  Say ('正在上传 ' + (($files | ForEach-Object { $_.filename }) -join '、') + ' 到 ' + $server + ' ...')
  $body = @{ files = @($files) } | ConvertTo-Json -Depth 5 -Compress
  $uri = $server + '/api/pairing/import'
  if ($token) { $uri = $uri + '?token=' + [uri]::EscapeDataString($token) }
  try {
    $resp = Invoke-RestMethod -Method Post -Uri $uri -ContentType 'application/json; charset=utf-8' -Body $body
    Say '上传成功。'
    if ($resp.summary) { Say $resp.summary }
    if ($resp.pairing) { Say ('服务器已保存 ' + $resp.pairing.count + ' 个配对文件。现在可以回到网页刷新查看。') }
  } catch {
    throw ('上传失败：' + $_.Exception.Message)
  }

  Say ''
  Say '配对完成。可以把手机从 USB 拔出，连同一局域网 Wi-Fi，在网页里选择设备并设置定位。'
  exit 0
} catch {
  Say $_.Exception.Message
  exit 1
}
"""


def to_crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")



def encode_windows_pair_bat(script: str) -> bytes:
    """UTF-8 with BOM and CRLF, as required by cmd.exe on Chinese Windows."""
    text = to_crlf(script)
    if not text.endswith("\r\n"):
        text += "\r\n"
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def encoded_extractor_command() -> str:
    """UTF-16LE base64 for powershell -EncodedCommand (avoids cmd quoting)."""
    return base64.b64encode(PS_EXTRACTOR.encode("utf-16le")).decode("ascii")


def extract_embedded_ps_body(script: str) -> str:
    """Return the PowerShell body after the last marker occurrence."""
    text = script.replace("\r\n", "\n").replace("\r", "\n")
    idx = text.rfind(PS_MARKER)
    if idx < 0:
        raise ValueError("embedded script missing")
    return text[idx + len(PS_MARKER) :].lstrip("\n")


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
    """Hybrid .bat: short ASCII cmd header + UTF-8 PowerShell body after PS_MARKER."""
    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("服务器地址无效")
    base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    # Header is ASCII-only. EncodedCommand avoids cmd.exe quote/ampersand splitting;
    # the stub uses LastIndexOf and a constructed marker so it cannot iex itself.
    encoded = encoded_extractor_command()
    header = "\n".join(
        [
            "@echo off",
            "setlocal EnableExtensions",
            f'set "IOS_WIFI_LOC_SERVER={base}"',
            'set "IOS_WIFI_LOC_SELF=%~f0"',
            "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand " + encoded,
            "if errorlevel 1 ( echo. & echo The pairing tool did not finish. See the messages above. ) else ( echo. & echo All done. )",
            "echo.",
            "pause",
            "exit /b",
            PS_MARKER,
            "",
        ]
    )
    return to_crlf(header + WINDOWS_PAIR_PS_BODY)
