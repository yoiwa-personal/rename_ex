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

renameat2_native_supported = False
renameat2_undefflags_passthrough = False
rename_exchange_native_supported = False
renameat_dirfd_supported = False

use_native = True

# constants for user API (the same as Linux)
RENAME_NOREPLACE = 1
RENAME_EXCHANGE = 2

_encoding = sys.getfilesystemencoding()
_errors = sys.getfilesystemencodeerrors()

def _fnencode(fname):
    if isinstance(fname, Path):
        fname = str(fname)
    if isinstance(fname, bytes):
        return fname
    else:
        return fname.encode(_encoding, errors=_errors)

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

    renameat2_native_supported = 'linux:renameat2'
    renameat2_undefflags_passthrough = True
    rename_exchange_native_supported = True
    renameat2_dirfd_supported = True

    AT_FDCWD = -100

    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameat2(int(src_dir_fd), src, int(dst_dir_fd), dst, int(flags))

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

    renameat2_native_supported = 'darwin:renameatx_np'
    renameat2_undefflags_passthrough = False
    rename_exchange_native_supported = True
    renameat_dirfd_supported = True

    AT_FDCWD = -2

    def _convert_flags_darwin(flags):
        if flags == 0:
            return 0
        elif flags == RENAME_NOREPLACE:
            return 4 # RENAME_EXCL
        elif flags == RENAME_EXCHANGE:
            return 2 # RENAME_SWAP
        else:
            raise ValueError("unknown flags")
    
    def _renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameatx_np(int(src_dir_fd), src, int(dst_dir_fd), dst, _convert_flags_darwin(flags))

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

    renameat2_native_supported = 'win32:MoveFileExW'
    renameat2_undefflags_passthrough = False
    rename_exchange_native_supported = True
    renameat_dirfd_supported = False

    AT_FDCWD = -2

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
        if src_dir_fd is not None: raise ValueError("dirfd is not supported on Win32")
        if dst_dir_fd is not None: raise ValueError("dirfd is not supported on Win32")

        srcstat = None
        dststat = None

        srcstat = os.lstat(src)
        dststat = os.lstat(dst) # FileNotFoundError is propargated

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
        return _rename_exchange_generic(src, dst)

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
        if src_dir_fd is not None: raise ValueError("dirfd is not supported on Win32")
        if dst_dir_fd is not None: raise ValueError("dirfd is not supported on Win32")

        if flags == RENAME_EXCHANGE:
            return _rename_exchange_win32(src, dst)
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

# see tempfile.py from Python
_os_open_flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
                  | getattr(os, 'O_NOFOLLOW', 0)
                  | getattr(os, 'O_BINARY', 0))
_os_use_effective_ids = os.access in os.supports_effective_ids

def _mktemp_at(dir, dir_fd, mkdir=True):
    if (dir == ''): dir = "."
    if dir_fd == None:
        dir = os.path.abspath(dir)
    import secrets
    if mkdir:
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

def _rename_exchange_generic_by_rename(src, dst, *,
                                       src_dir_fd=None, dst_dir_fd=None):
    srcstat = os.lstat(src, dir_fd=src_dir_fd)
    dststat = os.lstat(dst, dir_fd=dst_dir_fd)

    if srcstat == dststat: return

    basedir = os.path.dirname(dst)
    _, tmpdir = _mktemp_at(dir=basedir, dir_fd=dst_dir_fd, mkdir=True)
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
        if isinstance(e, FileNotFoundError):
            # same file in different path (should be detected stat check)
            return 0
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

def _rename_exchange_generic(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    rename_f = _renameat2 if sys.platform == 'win32' else os.rename
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

    if stat.S_ISDIR(srcstat.st_mode) or stat.S_ISDIR(dststat.st_mode):
        return _rename_exchange_generic_by_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

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

def _renameat2_generic_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    try:
        os.lstat(dst, dir_fd=dst_dir_fd)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError
    return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    # link and unlink is another solution; however,
    #  1) it will fail if only src directory is non-writable, and
    #  2) it still makes race-condition around unlink.

def _renameat2_generic(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    if (os.stat not in os.supports_dir_fd):
        if src_dir_fd != None or dst_dir_fd != None:
            os.stat(src, dir_fd=src_dir_fd) # cause Error
            raise NotImplementedError
    if (flags == 0):
        return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif (flags == RENAME_NOREPLACE):
        return _renameat2_generic_noreplace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif (flags == RENAME_EXCHANGE):
        return _rename_exchange_generic(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

def _renameat2_wrapper(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
    if flags == 0:
        if renameat2_native_supported and use_native:
            return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=0)
        return os.rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif flags == RENAME_NOREPLACE:
        if renameat2_native_supported and use_native:
            return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_NOREPLACE)
        if use_native == -1:
            raise ValueError("renameat2(RENAME_NOREPLACE) is not available")
        return _renameat2_generic_noreplace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    elif flags == RENAME_EXCHANGE:
        if rename_exchange_native_supported and use_native:
            return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_EXCHANGE)
        if use_native == -1:
            raise ValueError("renameat2(RENAME_EXCHANGE) is not available")
        return _rename_exchange_generic(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    else:
        if not (renameat2_native_supported and renameat2_undefflags_passthrough):
            raise ValueError("unknown flags to renameat2")
        return _renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=flags)

def _set_use_native(x):
    if x not in (True, False, -1):
        raise ValueError
    global use_native
    use_native = x
    global renameat2
    if renameat2_native_supported and rename_exchange_native_supported and renameat2_undefflags_passthrough:
        renameat2 = _renameat2
    else:
        renameat2 = _renameat2_wrapper

_set_use_native(True if renameat2_native_supported else False)

def _get_native_support():
    return { "str": f"""Native support for renameat2 or similar: {renameat2_native_supported}
Exchange is supported natively: {rename_exchange_native_supported}
Current setting for using routine: {"native(forced)"  if use_native == -1 else "native" if use_native else "generic emulation"}""",
      "native_supported": rename_exchange_native_supported,
      "exchange_supported": rename_exchange_native_supported,
      "use_native": use_native }

renameat = renameat2 # only optional "flags" is different

def rename_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_NOREPLACE)

def rename_exchange(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_EXCHANGE)
