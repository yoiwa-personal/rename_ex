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
import errno
import functools
from pathlib import Path
from collections import namedtuple
from collections.abc import Sequence

__all__ = ['RENAME_NOREPLACE', 'RENAME_EXCHANGE',
           'renameat2', 'rename_noreplace', 'rename_exchange']

_Environment = namedtuple('_Environment',
                          ('arch', 'native_supported',
                           'undef_flags_passthrough',
                           'exchange_native_supported',
                           'os_rename_nonreplacing',
                           'dirfd_supported'))

_env = _Environment(
    arch = 'generic',
    native_supported = False,
    undef_flags_passthrough = False,
    exchange_native_supported = False,
    os_rename_nonreplacing = False, # guessing
    dirfd_supported = False)

under_debug = sys.flags.debug

use_native = None # see _set_use_native
use_native_only = 0

# constants for user API (the same as Linux)
RENAME_NOREPLACE = 1
RENAME_EXCHANGE = 2

def _flags_to_display(x):
    if isinstance(x, int):
        if (x >= 0 and x <= 2):
            x = ("0", "RENAME_NOREPLACE", "RENAME_EXCHANGE")[x]
    return str(x)

_encoding = sys.getfilesystemencoding()
_errors = sys.getfilesystemencodeerrors()

def _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, forced=False, name="Error"):
    if forced or (os.stat not in os.supports_dir_fd):
        if (src_dir_fd != None or dst_dir_fd != None):
            os.stat(src, dir_fd=src_dir_fd) # cause Error
            raise ValueError(f"{name}: dirfd is not supported")

def _fnencode(fname):
    if isinstance(fname, Path):
        fname = str(fname)
    if isinstance(fname, bytes):
        return fname
    else:
        return fname.encode(_encoding, errors=_errors)

def _oserror(errno, src, dst):
    return OSError(errno, os.strerror(errno), src, None, dst)

def _fail_on_nativeonly(flags, cond=True):
    if cond:
        raise ValueError(f"renameat2({_flags_to_display(flags)}) is not available: use_native_only is set")

def _fail_on_unknownflags(flags):
    raise ValueError(f"renameat2: unknown flags {flags}")
    
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
            raise OSError(er, os.strerror(er), oldpath, None, newpath)

    AT_FDCWD = -100

    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameat2(int(src_dir_fd), src, int(dst_dir_fd), dst, int(flags))

    _env = _Environment(
        arch = 'linux',
        native_supported = 'linux:renameat2',
        undef_flags_passthrough = True,
        exchange_native_supported = True,
        os_rename_nonreplacing = False,
        dirfd_supported = True)

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
            raise OSError(er, os.strerror(er), oldpath, None, newpath)

    def _convert_flags_darwin(flags):
        if flags == 0:
            return 0
        elif flags == RENAME_NOREPLACE:
            return 4 # RENAME_EXCL
        elif flags == RENAME_EXCHANGE:
            return 2 # RENAME_SWAP
        else:
            _fail_on_unknownflags(flags)
    
    AT_FDCWD = -2

    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameatx_np(int(src_dir_fd), src, int(dst_dir_fd), dst, _convert_flags_darwin(flags))

    _env = _Environment(
        arch = 'darwin',
        native_supported = 'darwin:renameatx_np',
        undef_flags_passthrough = False,
        exchange_native_supported = True,
        os_rename_nonreplacing = False,
        dirfd_supported = True)

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
    
    _ktmw32.CommitTransaction.argtypes = [wintypes.HANDLE]
    _ktmw32.CommitTransaction.restype = wintypes.BOOL

    _ktmw32.RollbackTransaction.argtypes = [wintypes.HANDLE]
    _ktmw32.RollbackTransaction.restype = wintypes.BOOL

    _kernel32.MoveFileTransactedW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID, 
        wintypes.LPVOID, wintypes.DWORD, wintypes.HANDLE
    ]
    _kernel32.MoveFileTransactedW.restype = wintypes.BOOL
    
    _kernel32.CreateDirectoryTransactedW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
        wintypes.HANDLE]
    _kernel32.CreateDirectoryTransactedW.restype = wintypes.BOOL

    _kernel32.RemoveDirectoryTransactedW.argtypes = [
        wintypes.LPCWSTR, wintypes.HANDLE]
    _kernel32.RemoveDirectoryTransactedW.restype = wintypes.BOOL

    def _os_MoveFileEx(old, new, flags):
        r = _kernel32.MoveFileExW(old, new, flags)
        if r == 0:
            er = ctypes.get_last_error()
            raise ctypes.WinError(er)

    class _NoTransactionSupported(Exception):
        pass
    class _TransactionAborted(Exception):
        pass

    def _rename_exchange_txf_win32(src, dst, dstdir):
        err = None

        for seq in range(tempfile.TMP_MAX):
            h_transaction = _ktmw32.CreateTransaction(None, None, 0, 0, 0, 0, "Swap Files Transaction")
            if h_transaction == wintypes.HANDLE(-1).value or h_transaction is None:
                err = ctypes.get_last_error()
                if err == 6706: # ERROR_TM_INITIALIZATION_FAILED:
                    raise _NoTransactionSupported
                raise ctypes.WinError(err)

            def __mkdir(f):
                if _kernel32.CreateDirectoryTransactedW(None, f, None, h_transaction):
                    return 0
                err = ctypes.get_last_error()
                if err == 183: # ERROR_FILE_EXISTS
                    raise FileExistsError() # mktemp_at to retry
                if err in (2005, 6832):
                    raise _NoTransactionSupported
                if err in (6800, 6706, 6718):
                    raise _TransactionAborted
                raise ctypes.WinError(err)

            tmpdir = False
            try:
                _, tmpdir = _mktemp_at(dir=dstdir, dir_fd=None, func=__mkdir)
            except _TransactionAborted:
                continue
            # except _TransactionAborted: propagate to parent
            finally:
                if tmpdir == False:
                    _kernel32.CloseHandle(h_transaction)

            tmp = tmpdir + "/" + ".rename.from"

            try:
                if _kernel32.MoveFileTransactedW(src, tmp, None, None, 0, h_transaction):
                 if _kernel32.MoveFileTransactedW(dst, src, None, None, 0, h_transaction):
                  if _kernel32.MoveFileTransactedW(tmp, dst, None, None, 0, h_transaction):
                   if not _kernel32.RemoveDirectoryTransactedW(tmpdir, h_transaction):
                       err = ctypes.get_last_error()
                       warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ctypes.WinError(err)!r}")
                   if _ktmw32.CommitTransaction(h_transaction):
                        return True

                err = ctypes.get_last_error()
                if err in (2005, 6832): # ERROR_VOLUME_NOT_SUPPORTED, ERROR_TRANSACTIONAL_OPEN_NOT_ALLOWED
                    raise _NoTransactionSupported # propagate to parent
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

        dir_dst = os.path.dirname(dst)
        if dir_dst == '': dir_dst = '.'
        tmp_dir_fd = dst_dir_fd

        try:
            return _rename_exchange_txf_win32(src, dst, dir_dst)
        except _NoTransactionSupported:
            # no transaction fs support. os.link() may also be unsupported, use rename.
            if use_native_only >= 1:
                _fail_on_nativeonly("RENAME_NOREPLACE")
            return _rename_exchange_emulate_by_rename(src, dst, dir_dst=dir_dst)

    def _convert_flags_win32(flags):
        if flags == 0:
            return 1 # MOVEFILE_REPLACE_EXISTING
        elif flags == RENAME_NOREPLACE:
            return 0
        elif flags == RENAME_EXCHANGE:
            assert False
            raise ValueError("exchange not supported")
        else:
            _fail_on_unknownflags(flags)
    
    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, forced=True, name="renameat2(win32)")
        if flags == RENAME_EXCHANGE:
            return _rename_exchange_win32(src, dst)
        elif flags != 0 and flags != 1:
            _fail_on_unknownflags(flags)
        srcstat = None
        dststat = None

        if use_native_only <= 1:
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

    _env = _Environment(
        arch = 'win32',
        native_supported = 'win32:MoveFileExW',
        undef_flags_passthrough = False,
        exchange_native_supported = True,
        os_rename_nonreplacing = True,
        dirfd_supported = False)

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
    raise OSError(errno.EBUSY, "cannot make temporary file", dir)

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
        raise e
    try:
        os.link(dst, tmpdst, src_dir_fd=dst_dir_fd, dst_dir_fd=tmp_dir_fd)
    except Exception as e:
        try:
            os.unlink(tmpsrc, dir_fd=tmp_dir_fd)
            os.rmdir(tmpdir, dir_fd=tmp_dir_fd)
        except Exception as ee:
            warnings.warn(f"rename_exchange: cleaning tmpdir failed: {ee!r}")
        raise e
    
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
        raise e
    
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
        raise e

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
        raise e

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
        raise _oserror(errno.EPERM, src, dst)

    srcstat = os.lstat(src, dir_fd=src_dir_fd)
    dststat = os.lstat(dst, dir_fd=dst_dir_fd) # Pass-through FileNotFoundError and others

    if srcstat == dststat: return
    if (rename_f is None and _env.os_rename_nonreplacing) or stat.S_ISDIR(srcstat.st_mode) or stat.S_ISDIR(dststat.st_mode):
        return _rename_exchange_emulate_by_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, dir_dst=dir_dst)
    else:
        return _rename_exchange_emulate_by_link(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, dir_dst=dir_dst, rename_f=(rename_f or os.rename))

def _renameat2_emulate_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    try:
        os.lstat(dst, dir_fd=dst_dir_fd)
        # this check is required in Win32, when src and dst are same file with different name
    except FileNotFoundError:
        pass
    else:
        raise _oserror(errno.EEXIST, src, dst)
    return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    # link and unlink is another solution; however,
    #  1) it will fail if only src directory is non-writable,
    #  2) it will not work with directory, and
    #  3) it still makes race conditions around unlink.

def _renameat2_emulate_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    if use_native_only <= 1:
        # this really depends on that os.rename is non-replacing
        assert _env.os_rename_nonreplacing

        srcstat = None
        dststat = None
        srcstat = os.lstat(src) # err is propagated
        try:
            dststat = os.lstat(dst)  # err is eaten

            if srcstat == dststat:
                return
                # Win32 do rename over the same file!
        except FileNotFoundError: pass
        else:
            s_isdir = stat.S_ISDIR(srcstat.st_mode)
            isdir = stat.S_ISDIR(dststat.st_mode)

            # simulate posix corner cases...
            if (isdir and not s_isdir):
                raise _oserror(errno.EISDIR, src, dst)
            if (s_isdir and not isdir):
                raise _oserror(errno.ENOTDIR, src, dst)

    return os.replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

def _renameat2_noswapsupport(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    if (flags == 0 or flags == RENAME_NOREPLACE):
        return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=flags)
    if flags == RENAME_EXCHANGE:
        if use_native_only >= 1:
            _fail_on_nativeonly(flags)
        return _rename_exchange_emulate(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        _fail_on_unknownflags(flags)

def _renameat2_generic(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    _reject_dirfd_ifunsupported(src_dir_fd, dst_dir_fd, name="renameat2(generic)")
    if (flags == 0):
        if _env.os_rename_nonreplacing:
            return _renameat2_emulate_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        else:
            return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    if flags == RENAME_NOREPLACE:
        if _env.os_rename_nonreplacing:
            return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if use_native_only >= 1:
            _fail_on_nativeonly(flags)
        return _renameat2_emulate_noreplace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif flags == RENAME_EXCHANGE:
        if use_native_only >= 1:
            _fail_on_nativeonly(flags)
        return _rename_exchange_emulate(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        _fail_on_unknownflags(flags)

def _renameat2_choose():
    if _env.exchange_native_supported and use_native:
        return _renameat2
    elif _env.native_supported and use_native:
        return _renameat2_noswapsupport
    else:
        return _renameat2_generic

# DynamicCallable: https://gist.github.com/yoiwa/fe6e01d7e436d9b3a99db127be0df859
class DynamicCallable: # use as a decorator
    """A swappable callable wrapper.

    A callable whose underlying implementation can be dynamically updated at runtime.

    First apply @DynamicCallable for initial implementation.
    Then, @old_func._set_implementation for updated implementation.
    Function application form is also possible.

    This is particularly useful for exported module-level functions.
    For instance/class methods, assign directly to attributes of __class__ .
    """

    def __new__(cls, func):
        class DynamicCallable(cls):
            # __call__ is always invoked from a class, not from an instance.
            # We need a singleton class.
            __name__ = cls.__name__
            __qualname__ = cls.__qualname__
            __doc__ = cls.__doc__
            __module__ = cls.__module__

            def __init__(self, func):
                self.__class__.__call__ = staticmethod(func)
                functools.update_wrapper(self, func, updated=[])
                self.__class__.__print_prefix = f"{self.__name__} := "

            def _set_implementation(self, new_func, update_info=False):
                self.__class__.__call__ = staticmethod(new_func)
                if update_info:
                    functools.update_wrapper(self, new_func, updated=[])
                else:
                    self.__wrapped__ = new_func

            def __repr__(self):
                return f"<DynamicCallable: {self.__class__.__print_prefix}{self.__class__.__call__.__name__}>"

        return super().__new__(DynamicCallable)
## end DynamicCallable snippets

@DynamicCallable
def renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    """renameat2 - rename, replace or exchange a file relative to directory file descriptors.

    renameat2(src, dst, flags=0) will replace any existing target file.
    renameat2(src, dst, flags=rename_ex.RENAME_NOREPLACE) will only rename to non-existing target.
    renameat2(src, dst, flags=rename_ex.RENAME_EXCHANGE) will swap names of two files.
    """
    _renameat2_choose()(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=flags)

def set_use_native(x):
    global use_native
    global renameat2
    if x not in (True, False):
        raise ValueError
    old = use_native
    use_native = x
    renameat2._set_implementation(_renameat2_choose())
    return old

set_use_native(bool(_env.native_supported))

def set_use_native_only(x):
    global use_native_only
    if isinstance(x, bool):
        x = int(x)
    if isinstance(x, int):
        old = use_native_only
        use_native_only = x
        return old
    else:
        raise ValueError("non-bool, non-integer argument to use_native_only")

def allow_emulation(b):
    # old name
    if b not in (True, False):
        raise ValueError
    use_native_only(not b)

def support_status():
    used_f = renameat2.__wrapped__
    used_routine = ("native" if used_f is _renameat2
                    else "native/emulated swap" if used_f is _renameat2_noswapsupport
                    else "emulated" if used_f is _renameat2_generic
                    else "unknown")

    d = _env._asdict()
    d.update({
        "str": f"""Architecture:                            {_env.arch}
Native support for renameat2 or similar: {_env.native_supported}
Exchange is supported natively:          {_env.exchange_native_supported}
Dir_fd is supported:                     {_env.dirfd_supported}
Current setting:                         {"native" if use_native else "generic emulation"}
Enforce Native Routines:                 {use_native_only!r}
Currently-used routine:                  {used_routine} ({renameat2.__wrapped__!r})
""",
        "use_native_only": use_native_only,
        "allow_emulation": use_native_only == 0,
        "use_native": use_native})
    return d

renameat = renameat2 # only optional "flags" is different

def rename_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    """Rename a file in src to dst.  Raise some OSError if dst already exists."""
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_NOREPLACE)

def rename_exchange(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    """Exchange names of files in src and dst.  Raise some OSError if dst does not exist."""
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_EXCHANGE)
