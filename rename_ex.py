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

renameat2_supported = False

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

    def _os_renameat2(olddirfd, oldpath, newdirfd, newpath, flags):
        _libc.renameat2.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint
        ]
        _libc.renameat2.restype = ctypes.c_int

        oldb = _fnencode(oldpath)
        newb = _fnencode(newpath)

        r = _libc.renameat2(olddirfd, oldb, newdirfd, newb, flags)

        if r != 0:
            er = ctypes.get_errno()
            raise OSError(er, os.strerror(er))

    renameat2_supported = 'linux:renameat2'

    AT_FDCWD = -100

    def renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameat2(int(src_dir_fd), src, int(dst_dir_fd), dst, int(flags))

elif sys.platform == "darwin":
    _libc = ctypes.CDLL(None, use_errno=True)

    def _os_renameatx_np(olddirfd, oldpath, newdirfd, newpath, flags):
        _libc.renameatx_np.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint
        ]
        _libc.renameatx_np.restype = ctypes.c_int

        oldb = _fnencode(oldpath)
        newb = _fnencode(newpath)

        r = _libc.renameatx_np(olddirfd, oldb, newdirfd, newb, flags)

        if r != 0:
            er = ctypes.get_errno()
            raise OSError(er, os.strerror(er))

    renameat2_supported = 'darwin:renameatx_np'

    AT_FDCWD = -2

    def _convert_flags_darwin(flags):
        if flags == 0:
            return 0
        elif flags == RENAME_NOREPLACE:
            return 4 # RENAME_EXCL
        elif flags == RENAME_EXCHANGE:
            return 2 # RENAME_SWAP
        else:
            raise ValueError.new("unknown flags")
    
    def renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0):
        if src_dir_fd is None: src_dir_fd = AT_FDCWD
        if dst_dir_fd is None: dst_dir_fd = AT_FDCWD
        _os_renameatx_np(int(src_dir_fd), src, int(dst_dir_fd), dst, _convert_flags_darwin(flags))

# see tempfile.py from Python
_os_open_flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
                  | getattr(os, 'O_NOFOLLOW', 0)
                  | getattr(os, 'O_BINARY', 0))
    
def _mktemp_at(dir, dir_fd, mkdir=True):
    #assert(dir_fd != None)
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
        fname = os.path.join(dir, ".rename-" + token)
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

    tmpisdir = stat.S_ISDIR(srcstat.st_mode)
    
    basedir = os.path.dirname(dst)
    if tmpisdir:
        fd, tmpname = _mktemp_at(dir=basedir, dir_fd=dst_dir_fd, mkdir=True)
    else:
        fd, tmpname = _mktemp_at(dir=basedir, dir_fd=dst_dir_fd, mkdir=False)
        os.close(fd)
    tmp_dir_fd = dst_dir_fd
        
    try:
        os.rename(src, tmpname, src_dir_fd=src_dir_fd, dst_dir_fd=tmp_dir_fd)
    except Exception as e:
        if tmpisdir:
            try: os.rmdir(tmpname, dir_fd=tmp_dir_fd)
            except Exception as ee:
                warnings.warn(f"rename_exchange: rmdir(recovery) temporary dir failed: {ee!r}")
        else:
            try: os.unlink(tmpname, dir_fd=tmp_dir_fd)
            except Exception as ee:
                warnings.warn(f"rename_exchange: unlink(recovery) temporary file failed: {ee!r}")
        raise e

    try:
        os.rename(dst, src, src_dir_fd=dst_dir_fd, dst_dir_fd=src_dir_fd)
    except Exception as e:
        try:
            os.rename(tmpname, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
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
        except Exception as ee:
            warnings.warn(f"rename_exchange: rename(recovery) 2 temporary file failed:{ee!r}: {src!r} is left as {tmpname!r}")
        raise e
    return

def _rename_exchange_generic(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    dir_dst = os.path.dirname(dst)
    if dir_dst == '': dir_dst = '.'
    dir_src = os.path.dirname(src)
    if dir_src == '': dir_src = '.'

    if not (os.access(dir_dst, os.W_OK, effective_ids=True, dir_fd=dst_dir_fd)
            and os.access(dir_src, os.W_OK, effective_ids=True, dir_fd=src_dir_fd)):
        raise PermissionError

    srcstat = os.lstat(src, dir_fd=src_dir_fd)
    dststat = os.lstat(dst, dir_fd=dst_dir_fd) # Pass-through FileNotFoundError and others

    if srcstat == dststat: return

    if stat.S_ISDIR(srcstat.st_mode) or stat.S_ISDIR(dststat.st_mode):
        return _rename_exchange_generic_by_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    #    tmpdir = tempfile.mkdtemp(prefix="rename", dir=dir_dst)
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
        os.rename(tmpdst, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
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
        os.rename(tmpsrc, dst, src_dir_fd=tmp_dir_fd, dst_dir_fd=dst_dir_fd)
        # now safe
    except Exception as e:
        # in danger: src is about to lost
        try:
            os.rename(tmpsrc, src, src_dir_fd=tmp_dir_fd, dst_dir_fd=src_dir_fd)
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
    
def rename_noreplace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_NOREPLACE)

def rename_exchange(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    return renameat2(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=RENAME_EXCHANGE)

renameat = renameat2 # only optional "flags" is different
