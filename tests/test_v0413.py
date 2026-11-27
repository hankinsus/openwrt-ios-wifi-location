from __future__ import annotations

import base64

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page
from ios_wifi_loc.windows_pair import (
    PS_EXTRACTOR,
    PS_MARKER,
    PS_MARKER_PREFIX,
    PS_MARKER_SUFFIX,
    encode_windows_pair_bat,
    encoded_extractor_command,
    extract_embedded_ps_body,
    render_windows_pair_bat,
)


def test_version_is_0413():
    assert __version__ == "0.5.15"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.15" in html
    assert "v0.4.12" not in html


def test_extractor_uses_lastindexof_and_constructed_marker():
    assert PS_MARKER_PREFIX + PS_MARKER_SUFFIX == PS_MARKER
    assert "LastIndexOf" in PS_EXTRACTOR
    assert "$s.IndexOf(" not in PS_EXTRACTOR
    # The full separator must not appear as a literal in the stub.
    assert PS_MARKER not in PS_EXTRACTOR
    assert PS_MARKER_PREFIX in PS_EXTRACTOR and PS_MARKER_SUFFIX in PS_EXTRACTOR
    encoded = encoded_extractor_command()
    decoded = base64.b64decode(encoded).decode("utf-16le")
    assert decoded == PS_EXTRACTOR
    assert "LastIndexOf" in decoded
    assert PS_MARKER not in decoded


def test_extract_embedded_ps_body_skips_decoy_first_marker():
    decoy = (
        "@echo off\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
        f"$k='{PS_MARKER}'; $i=$s.IndexOf($k); "
        "if($i -lt 0){ Write-Host 'embedded script missing'; exit 1 }; "
        "iex $s.Substring($i+$k.Length)\"\r\n"
        "exit /b\r\n"
    )
    body = "$ErrorActionPreference = 'Stop'\r\nSay 'real body'\r\n"
    script = decoy + PS_MARKER + "\r\n" + body
    extracted = extract_embedded_ps_body(script)
    assert extracted.lstrip().startswith("$ErrorActionPreference")
    assert "Say 'real body'" in extracted
    assert "embedded script missing" not in extracted
    assert "-Command" not in extracted
    assert "IndexOf" not in extracted


def test_rendered_bat_extracts_exact_body_not_stub():
    script = render_windows_pair_bat("http://10.16.1.2:19443")
    body = extract_embedded_ps_body(script)
    assert body.lstrip().startswith("$ErrorActionPreference")
    assert "embedded script missing" not in body
    assert "-EncodedCommand" not in body
    assert "powershell -NoProfile" not in body
    assert "@echo off" not in body
    assert "WindowsApps" in body
    assert "winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements" in body
    assert "Refresh-Path" in body
    assert "-m pymobiledevice3 lockdown pair" in body
    assert "-m pymobiledevice3 amfi enable-developer-mode" in body
    assert "pymobiledevice3==11.63.1" in body
    assert r"C:\ProgramData\Apple\Lockdown" in body
    assert "/api/pairing/import" in body
    assert "SystemConfiguration.plist" in body
    assert "Invoke-RestMethod" in body
    assert "content_base64" in body
    assert "Get-ChildItem -LiteralPath $dir -Filter '*.plist' -File" in body
    assert "LastWriteTime" not in script
    header = script.rsplit("\r\n" + PS_MARKER + "\r\n", 1)[0]
    header.encode("ascii")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand" in header
    assert PS_MARKER not in header
    raw = encode_windows_pair_bat(script)
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.replace(b"\r\n", b"").find(b"\n") == -1
