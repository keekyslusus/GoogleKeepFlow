import ctypes
import os
import sys
from pathlib import Path


FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_ID_TYPE = 0
PATH_BUFFER_SIZE = 32768
RECYCLE_BIN_DIR_NAME = "$recycle.bin"


def file_identity(path):
    """Return [volume, file id]; on NTFS it survives renames and moves within the same drive."""
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    if not stat.st_ino:
        return None
    return [int(stat.st_dev), int(stat.st_ino)]


def is_recycle_bin_path(path):
    return any(part.lower() == RECYCLE_BIN_DIR_NAME for part in Path(path).parts)


def strip_long_path_prefix(path):
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path


def find_path_by_identity(hint_path, identity):
    """Resolve a file id to its current path on the drive of hint_path, or None."""
    if sys.platform != "win32" or not identity:
        return None
    if not 0 < int(identity[1]) < 2 ** 64:
        # 128-bit ReFS ids would need FILE_ID_128; such files just stay "missing".
        return None
    drive = os.path.splitdrive(os.path.abspath(str(hint_path)))[0]
    if not drive:
        return None

    from ctypes import wintypes

    class FILE_ID_DESCRIPTOR(ctypes.Structure):
        # The id union is 16 bytes (FILE_ID_128); a plain file id uses the first 8.
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("Type", ctypes.c_int),
            ("FileId", ctypes.c_ulonglong),
            ("Padding", ctypes.c_byte * 8),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.OpenFileById.restype = wintypes.HANDLE
    kernel32.OpenFileById.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILE_ID_DESCRIPTOR),
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid_handle = wintypes.HANDLE(-1).value

    volume = kernel32.CreateFileW(
        drive + "\\",
        0,
        FILE_SHARE_ALL,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if volume in (None, invalid_handle):
        return None
    try:
        descriptor = FILE_ID_DESCRIPTOR(ctypes.sizeof(FILE_ID_DESCRIPTOR), FILE_ID_TYPE, int(identity[1]))
        handle = kernel32.OpenFileById(
            volume,
            ctypes.byref(descriptor),
            0,
            FILE_SHARE_ALL,
            None,
            FILE_FLAG_BACKUP_SEMANTICS,
        )
    finally:
        kernel32.CloseHandle(volume)
    if handle in (None, invalid_handle):
        return None
    try:
        buffer = ctypes.create_unicode_buffer(PATH_BUFFER_SIZE)
        length = kernel32.GetFinalPathNameByHandleW(handle, buffer, PATH_BUFFER_SIZE, 0)
        if not length or length >= PATH_BUFFER_SIZE:
            return None
    finally:
        kernel32.CloseHandle(handle)

    path = strip_long_path_prefix(buffer.value)
    # Guards against id reuse on another volume or a directory with the same id.
    if not os.path.isfile(path) or file_identity(path) != [int(value) for value in identity]:
        return None
    return path
