# -*- python -*-
# Python library providing additional rename functionality
#
# https://github.com/yoiwa-personal/rename_ex/
#
# Copyright 2026 Yutaka OIWA <yutaka@oiwa.jp>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This module provide an interface to Linux's ability to rename files
with additional functionality, or similar ones in other OSs.

 - renameat2(src, dst, 0) is equivalent to os.rename in Linux.
   It will replace the previous dst file if possible.

 - renameat2(src, dst, RENAME_NOREPLACE) keeps "dst" file intact.
   If the target file is existing, the call will fail.

 - renameat2(src, dst, RENAME_EXCHANGE) exchanges the names of
   two files.

If OS supports dir_fd functionality, it will be provided in the
same way in Python's os.rename provision.
"""

import ctypes
import os
import os.path
import sys
import tempfile
import warnings
import stat
from pathlib import Path
from collections.abc import Sequence

__all__ = ['RENAME_NOREPLACE', 'RENAME_EXCHANGE',
           'renameat2', 'rename_noreplace', 'rename_exchange']

under_debug = sys.flags.debug

arch = 'generic'
renameat2_native_supported = False
renameat2_undefflags_passthrough = False
rename_exchange_native_supported = False
renameat2_dirfd_supported = False

use_native = None # see _set_use_native

# constants for user API (the same as Linux)
RENAME_NOREPLACE = 1
RENAME_EXCHANGE = 2

_encoding = sys.getfilesystemencoding()
_errors = sys.getfilesystemencodeerrors()

def _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, forced=False, name="Error"):
    if forced or (os.stat not in os.supports_dir_fd):
        if (src_dir_fd != None or dst_dir_fd != None):
            os.stat(src, dir_fd=src_dir_fd) # cause Error
            raise ValueError("dirfd is not supported")

def _fnencode(fname):
    if isinstance(fname, Path):
        fname = str(fname)
    if isinstance(fname, bytes):
        return fname
    else:
        return fname.encode(_encoding, errors=_errors)

# Rules-of-thumb for naming OS-specific routine naming:
#    _renameat2 has Python-level common interface:
#      receives None for dir_fd, common signature, strings are Python-native
#    _os_..* wraps system calls:
#      strings are Python-native, dir_fd and flags are already converted
#    names with _ and arch names are also used for local purposes
#
#    _renameat2 must at least exposed; AT_FDCWD, if available.

if sys.platform == 'linux':
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
    _libc.renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint
    ]
    _libc.renameat2.restype = ctypes.c_int

    def _os_renameat2(olddirfd, oldpath, newdirfd, newpath, flags):
        oldb = _fnencode(oldpath)
        newb = _fnencode(newpath)

        r = _libc.renameat2(olddirfd, oldb, newdirfd, newb, flags)

        if r != 0:
            er = ctypes.get_errno()
            raise OSError(er, os.strerror(er))

    AT_FDCWD = -100

    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameat2(int(src_dir_fd), src, int(dst_dir_fd), dst, int(flags))

    arch = 'linux'
    renameat2_native_supported = 'linux:renameat2'
    renameat2_undefflags_passthrough = True
    rename_exchange_native_supported = True
    rename_osrename_is_noreplacing = False
    renameat2_dirfd_supported = True

elif sys.platform == "darwin":
    _libc = ctypes.CDLL(None, use_errno=True)
    _libc.renameatx_np.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint
    ]
    _libc.renameatx_np.restype = ctypes.c_int

    def _os_renameatx_np(olddirfd, oldpath, newdirfd, newpath, flags):
        oldb = _fnencode(oldpath)
        newb = _fnencode(newpath)

        r = _libc.renameatx_np(olddirfd, oldb, newdirfd, newb, flags)

        if r != 0:
            er = ctypes.get_errno()
            raise OSError(er, os.strerror(er))

    def _convert_flags_darwin(flags):
        if flags == 0:
            return 0
        elif flags == RENAME_NOREPLACE:
            return 4 # RENAME_EXCL
        elif flags == RENAME_EXCHANGE:
            return 2 # RENAME_SWAP
        else:
            raise ValueError("unknown flags")
    
    AT_FDCWD = -2

    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameatx_np(int(src_dir_fd), src, int(dst_dir_fd), dst, _convert_flags_darwin(flags))

    arch = 'darwin'
    renameat2_native_supported = 'darwin:renameatx_np'
    renameat2_undefflags_passthrough = False
    rename_exchange_native_supported = True
    rename_osrename_is_noreplacing = False
    renameat_dirfd_supported = True

elif sys.platform == "win32":
    from ctypes import wintypes

    MOVEFILE_REPLACE_EXISTING = 1

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _ktmw32 = ctypes.WinDLL('ktmw32', use_last_error=True)

    _kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    _kernel32.MoveFileExW.restype = wintypes.BOOL

    _ktmw32 = ctypes.WinDLL('ktmw32', use_last_error=True)

    # Transaction File System
    
    _ktmw32.CreateTransaction.argtypes = [
        wintypes.LPVOID, wintypes.HANDLE, wintypes.DWORD, 
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR
    ]
    _ktmw32.CreateTransaction.restype = wintypes.HANDLE
    
    _kernel32.MoveFileTransactedW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID, 
        wintypes.LPVOID, wintypes.DWORD, wintypes.HANDLE
    ]
    _kernel32.MoveFileTransactedW.restype = wintypes.BOOL
    
    _ktmw32.CommitTransaction.argtypes = [wintypes.HANDLE]
    _ktmw32.CommitTransaction.restype = wintypes.BOOL
    
    _ktmw32.RollbackTransaction.argtypes = [wintypes.HANDLE]
    _ktmw32.RollbackTransaction.restype = wintypes.BOOL

    def _os_MoveFileEx(old, new, flags):
        r = _kernel32.MoveFileExW(old, new, flags)
        if r == 0:
            er = ctypes.get_last_error()
            raise ctypes.WinError(er)

    class _NoTransactionSupported(Exception):
        pass

    def _rename_exchange_txf_win32(src, dst, tmp):
        err = None

        for seq in range(tempfile.TMP_MAX):
            h_transaction = _ktmw32.CreateTransaction(None, None, 0, 0, 0, 0, "Swap Files Transaction")
            if h_transaction == wintypes.HANDLE(-1).value or h_transaction is None:
                err = ctypes.get_last_error()
                if err == 6706: # ERROR_TM_INITIALIZATION_FAILED:
                    raise _NoTransactionSupported
                raise ctypes.WinError(err)

            success = False

            try:
                if _kernel32.MoveFileTransactedW(src, tmp, None, None, 0, h_transaction):
                 if _kernel32.MoveFileTransactedW(dst, src, None, None, 0, h_transaction):
                  if _kernel32.MoveFileTransactedW(tmp, dst, None, None, 0, h_transaction):
                   if _ktmw32.CommitTransaction(h_transaction):
                        return True

                err = ctypes.get_last_error()
                if err == 2005: # ERROR_VOLUME_NOT_SUPPORTED
                    raise _NoTransactionSupported
                if err in (6800, 6706, 6718):
                    # ERR_TRANSACTIONAL_CONFLICT, ERROR_TRANSACTION_ALREADY_ABORTED, ERROR_TRANSACTION_NOT_ACTIVE
                    continue
                else:
                    _ktmw32.RollbackTransaction(h_transaction)
                    break
            finally:
                _kernel32.CloseHandle(h_transaction)
        raise ctypes.WinError(err)

    def _rename_exchange_win32(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, forced=True, name="renameat2(win32,EXCHANGE)")

        srcstat = None
        dststat = None

        srcstat = os.lstat(src)
        dststat = os.lstat(dst) # FileNotFoundError is propagated

        if srcstat == dststat:
           return

        basedir = os.path.dirname(dst)
        _, tmpdir = _mktemp_at(dir=basedir, dir_fd=dst_dir_fd, mkdir=True)
        tmpname = tmpdir + "/" + ".rename.from"
        tmp_dir_fd = dst_dir_fd

        try:
             return _rename_exchange_txf_win32(src, dst, tmpname)
        except _NoTransactionSupported:
             pass
        finally:
             os.rmdir(tmpdir)

        if use_native == -1:
            raise ValueError("renameat2(RENAME_NOREPLACE) is not available")
        return _rename_exchange_emulate(src, dst, rename_f=_renameat2)
               # replacing rename_f is passed here

    def _convert_flags_win32(flags):
        if flags == 0:
            return 1 # MOVEFILE_REPLACE_EXISTING
        elif flags == RENAME_NOREPLACE:
            return 0
        elif flags == RENAME_EXCHANGE:
            raise ValueError("exchange not supported")
        else:
            raise ValueError("unknown flags")
    
    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, forced=True, name="renameat2(win32)")

        if flags == RENAME_EXCHANGE:
            return _rename_exchange_win32(src, dst)
        elif flags != 0 and flags != 2:
            raise ValueError("invalid flags for renameat2")
        srcstat = None
        dststat = None
        try:
            srcstat = os.lstat(src)
            dststat = os.lstat(dst)

            if srcstat == dststat:
                # Win32 do rename over the same file with and WITHOUT MOVEFILE_REPLACE_EXISTING !
                if flags == 0: return          # (with case: in sync with POSIX)
                else: raise FileExistsError    # (without case: clearly a bug)
        except FileNotFoundError: pass

        _os_MoveFileEx(src, dst, _convert_flags_win32(flags))

    AT_FDCWD = None # no integer value, our _renameat2 accepts

    arch = 'win32'
    renameat2_native_supported = 'win32:MoveFileExW'
    renameat2_undefflags_passthrough = False
    rename_exchange_native_supported = True
    rename_osrename_is_noreplacing = True
    renameat2_dirfd_supported = False

# see tempfile.py from Python
_os_open_flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
                  | getattr(os, 'O_NOFOLLOW', 0)
                  | getattr(os, 'O_BINARY', 0))
_os_use_effective_ids = os.access in os.supports_effective_ids

def _mktemp_at(dir, dir_fd, mkdir=True, func=None):
    if (dir == ''): dir = "."
    if dir_fd == None:
        dir = os.path.abspath(dir)
    import secrets
    if func:
        f = func
    elif mkdir:
        f = lambda name: os.mkdir(name, mode=0o700, dir_fd=dir_fd)
    else:
        f = lambda name: os.open(name, flags=_os_open_flags, mode=0o600, dir_fd=dir_fd)
    for seq in range(tempfile.TMP_MAX):
        token = secrets.token_urlsafe(8)
        fname = os.path.join(dir, "..rename." + token)
        try:
            fd = f(fname)
        except FileExistsError:
            continue
        return fd, str(fname)
    raise FileExistsError(errno.EEXIST, "cannot make temporary file")

def _rename_exchange_emulate_by_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None, dir_dst=None, rename_f=os.rename):
    _fd, tmpdir = _mktemp_at(dir=dir_dst, dir_fd=dst_dir_fd, mkdir=True)

    tmpsrc = tmpdir + "/.exchange.from"
    tmpdst = tmpdir + "/.exchange.to"
    tmp_dir_fd = dst_dir_fd
    
    try:
        os.link(src, tmpsrc, src_dir_fd=src_dir_fd, dst_dir_fd=tmp_dir_fd)
    except Exception as e:
        try:
            os.rmdir(tmpdir, dir_fd=dst_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise

    try:
        os.link(dst, tmpdst, src_dir_fd=dst_dir_fd, dst_dir_fd=tmp_dir_fd)
    except Exception as e:
        try:
            os.unlink(tmpsrc, dir_fd=tmp_dir_fd)
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise
    
    # critical section: files may be lost
    try:
        rename_f(tmpdst, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
    except Exception as e:
        # still safe...
        try:
            os.unlink(tmpdst, dir_fd=tmp_dir_fd)
            os.unlink(tmpsrc, dir_fd=tmp_dir_fd)
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise
    
    try:
        rename_f(tmpsrc, dst, src_dir_fd=tmp_dir_fd, dst_dir_fd=dst_dir_fd)
        # now safe
    except Exception as e:
        # in danger: src is about to lost
        try:
            rename_f(tmpsrc, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: rename for recovery failed: {e!r}: original file {src!r} is left on {tmpsrc!r}")
            # don't touch on temporary directory!
            raise e
        # now safe: only tmpdir is exist
        try:
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise

    # here, the directory should be empty:
    # however, if src and dst are the same file, tmp files are left.
    try:
        try:
            os.unlink(tmpdst, dir_fd=tmp_dir_fd)
            os.unlink(tmpsrc, dir_fd=tmp_dir_fd)
        except FileNotFoundError:
            pass
        os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
    except Exception as ee:
        warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise

def _rename_exchange_emulate_by_rename(src, dst, *,
                                       src_dir_fd=None, dst_dir_fd=None,
                                       dir_dst=None):
    # this routine works with os.rename both replacing and non-replacing.
    # non_replacing is safer, so no rename_f arg is given here

    _, tmpdir = _mktemp_at(dir=dir_dst, dir_fd=dst_dir_fd, mkdir=True)
    tmpname = tmpdir + "/" + ".rename.from"
    tmp_dir_fd = dst_dir_fd

    try:
        os.rename(src, tmpname, src_dir_fd=src_dir_fd, dst_dir_fd=tmp_dir_fd)
    except Exception as e:
        try: os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: rmdir(recovery) temporary dir failed: {ee!r}")
        raise e

    try:
        os.rename(dst, src, src_dir_fd=dst_dir_fd, dst_dir_fd=src_dir_fd)
    except Exception as e:
        try:
            os.rename(tmpname, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: rename(recovery) 1 temporary file failed: {ee!r}")

        # now in original state
        if isinstance(e, FileNotFoundError):
            # same file in different path (should have been detected by stat check)
            return
        raise e

    try:
        os.rename(tmpname, dst, src_dir_fd=dst_dir_fd, dst_dir_fd=dst_dir_fd)
    except Exception as e:
        try:
            os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
            os.rename(tmpname, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: rename(recovery) 2 temporary file failed:{ee!r}: {src!r} is left as {tmpname!r}")
        raise e
    os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
    return

def _rename_exchange_emulate(src, dst, *, src_dir_fd=None, dst_dir_fd=None, rename_f=None):
    dir_dst = os.path.dirname(dst)
    if dir_dst == '': dir_dst = '.'
    dir_src = os.path.dirname(src)
    if dir_src == '': dir_src = '.'

    if not (os.access(dir_dst, os.W_OK, effective_ids=_os_use_effective_ids, dir_fd=dst_dir_fd)
            and os.access(dir_src, os.W_OK, effective_ids=_os_use_effective_ids, dir_fd=src_dir_fd)):
        raise PermissionError

    srcstat = os.lstat(src, dir_fd=src_dir_fd)
    dststat = os.lstat(dst, dir_fd=dst_dir_fd) # Pass-through FileNotFoundError and others

    if srcstat == dststat: return

    if (rename_f is None and rename_osrename_is_noreplacing) or stat.S_ISDIR(srcstat.st_mode) or stat.S_ISDIR(dststat.st_mode):
        return _rename_exchange_emulate_by_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, dir_dst=dir_dst)
    else:
        return _rename_exchange_emulate_by_link(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, dir_dst=dir_dst, rename_f=(rename_f or os.rename))

def _renameat2_emulate_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    try:
        os.lstat(dst, dir_fd=dst_dir_fd)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError
    return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    # link and unlink is another solution; however,
    #  1) it will fail if only src directory is non-writable,
    #  2) it will not work with directory, and
    #  3) it still makes race conditions around unlink.

def _renameat2_emulate_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    # this really depends on that os.rename is non-replacing
    assert rename_osrename_is_noreplacing

    srcstat = None
    dststat = None
    srcstat = os.lstat(src) # err is propagated
    try:
        dststat = os.lstat(dst)  # err is eaten

        if srcstat == dststat:
            return
            # Win32 do rename over the same file!
    except FileNotFoundError: pass

    try:
        # first try rename;
        # in Win32, PermissionError is first raised over FileExistError
        os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    except FileExistsError as e:
        s_isdir = stat.S_ISDIR(srcstat.st_mode)
        isdir = stat.S_ISDIR(dststat.st_mode)

        # simulate posix corner cases...
        if (srcstat.st_ino == dststat.st_ino and srcstat.st_dev == dststat.st_dev):
            return
        if (isdir and not s_isdir):
            raise IsADirectoryError
        if (s_isdir and not isdir):
            raise NotADirectoryError

        if isdir:
            # check it empty?
            if len(os.listdir(dst)) != 0:
                raise IsADirectoryError("target is non-empty directory")

        _, tmpfile = _mktemp_at(
            # this mktemp_at depends on non-replacing os.rename
            os.path.dirname(dst), dir_fd=dst_dir_fd,
            func = lambda f: os.rename(dst, f, src_dir_fd=dst_dir_fd, dst_dir_fd=dst_dir_fd))
        try:
            os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        except Exception as e:
            try:
                os.rename(tmpfile, dst, src_dir_fd=dst_dir_fd, dst_dir_fd=dst_dir_fd)
            except Exception as ee:
                warnings.warn(f"rename_replace: cannot recover from temporary rename: file {dst!r} is left alone in {tempfile!r} {ee!r}")
            raise e
        try:
            if isdir:
                os.rmdir(tmpfile, dir_fd=dst_dir_fd)
            else:
                os.unlink(tmpfile, dir_fd=dst_dir_fd)
        except Exception as ee:
            raise RuntimeError(f"rename_replace: cannot remove temporary old-destination rename(recovery) 1 temporary file failed: {ee!r}") from ee

def _renameat2_noswapsupport(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    if (flags == 0 or flags == RENAME_NOREPLACE):
        return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=flags)
    if use_native == -1:
        raise ValueError(f"renameat2({flags}) is not available")
    if flags == RENAME_EXCHANGE:
        return _rename_exchange_emulate(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        raise ValueError(f"renameat2: unknown flag {flags}")

def _renameat2_generic(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, name="renameat2(generic)")
    if (flags == 0):
        if rename_osrename_is_noreplacing:
            return _renameat2_emulate_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        else:
            return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    if use_native == -1:
        raise ValueError(f"renameat2({flags}) is not available")
    if flags == RENAME_NOREPLACE:
        return _renameat2_emulate_noreplace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif flags == RENAME_EXCHANGE:
        return _rename_exchange_emulate(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        raise ValueError(f"renameat2: unknown flag {flags}")

def _renameat2_choose():
    if rename_exchange_native_supported and use_native:
        return _renameat2
    elif renameat2_native_supported and use_native:
        return _renameat2_noswapsupport
    else:
        return _renameat2_generic

def _renameat2_switcher(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    _renameat2_choose()(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=flags)

def set_use_native(x):
    global use_native
    global renameat2
    if x not in (True, False, -1):
        raise ValueError
    if under_debug:
        renameat2 = _renameat2_switcher
    else:
        if ((use_native is not None) and
            (not not use_native) != (not not x)):
            raise ValueError("rename_at.set_use_native: only available under debugging")
        renameat2 = _renameat2_choose()
    use_native = x

set_use_native(not (not renameat2_native_supported))

def support_status():
    return { "str": f"""Architecture:                            {arch}
Native support for renameat2 or similar: {renameat2_native_supported}
Exchange is supported natively:          {rename_exchange_native_supported}
Dir_fd is supported:                     {renameat2_dirfd_supported}
Current setting for used routine:        {"native(forced)"  if use_native == -1 else "native" if use_native else "generic emulation"}
""",
             "arch": arch,
             "native_supported": renameat2_native_supported,
             "exchange_supported": rename_exchange_native_supported,
             "dirfd_supported": renameat2_dirfd_supported,
             "use_native": use_native }

renameat = renameat2 # only optional "flags" is different

def rename_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    """Rename a file in src."""
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_NOREPLACE)

def rename_exchange(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_EXCHANGE)
