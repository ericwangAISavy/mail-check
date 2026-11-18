"""Windows DPAPI: encrypt small secrets to the current Windows user.

Data protected here can only be decrypted by the same Windows user (on the
same machine for a local account), which is the same protection Windows
Credential Manager gives its entries — but without its per-user storage cap.
"""

from __future__ import annotations

import ctypes
import os

#: Never show a prompt; a service process has nobody to answer it.
_UI_FORBIDDEN = 0x1


def available() -> bool:
    return os.name == "nt"


if os.name == "nt":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _signature = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
                  ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.argtypes = _signature
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, *_signature[2:]]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _run(function, data: bytes, entropy: bytes, *extra) -> bytes:
    source = ctypes.create_string_buffer(data, len(data))
    salt = ctypes.create_string_buffer(entropy, len(entropy))
    blob_in = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    blob_salt = _Blob(len(entropy), ctypes.cast(salt, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    if not function(ctypes.byref(blob_in), *extra, ctypes.byref(blob_salt), None, None,
                    _UI_FORBIDDEN, ctypes.byref(blob_out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def protect(data: bytes, entropy: bytes) -> bytes:
    return _run(_crypt32.CryptProtectData, data, entropy, None)


def unprotect(data: bytes, entropy: bytes) -> bytes:
    """Raise OSError when the data is corrupt or belongs to another user/purpose."""
    return _run(_crypt32.CryptUnprotectData, data, entropy, None)
