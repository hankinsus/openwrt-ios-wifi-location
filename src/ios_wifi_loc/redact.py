from __future__ import annotations

import re

_PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]{1,40}-----.*?-----END [A-Z0-9 ]{1,40}-----",
    re.DOTALL,
)
_SECRET_FIELD = re.compile(
    r"(?i)\b(HostPrivateKey|RootPrivateKey|DevicePrivateKey|HostCertificate|"
    r"DeviceCertificate|RootCertificate|EscrowBag|SystemBUID|HostID|"
    r"WiFiMACAddress|BluetoothMACAddress|deviceKVSData|RootPrivateKey|"
    r"HostCertificate)\b[^,\n}]*"
)
_LONG_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/])")
_HIDDEN = "[已隐藏]"


def redact(text: str) -> str:
    if not text:
        return ""
    cleaned = _PEM.sub(_HIDDEN, text)
    cleaned = _SECRET_FIELD.sub(_HIDDEN, cleaned)
    cleaned = _LONG_B64.sub(_HIDDEN, cleaned)
    return cleaned
