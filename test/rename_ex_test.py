#!/usr/bin/python3 -d

import os, os.path, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import rename_ex
from rename_ex import renameat2, RENAME_EXCHANGE, RENAME_NOREPLACE

from types import SimpleNamespace
import tempfile
from warnings import warn

def write_file(env, fname, content):
    with open(env.prefix + fname, "w") as f:
        f.write(content)

def read_file(env, fname, check=None):
    s = None
    with open(env.prefix + fname, "r") as f:
        s = f.read(-1)
    print(f"reading {env.prefix + fname} => {s!r}")
    if check:
        return s == check
    else:
        return s

def prepare(tobj, use_fd=False):
    global tmpdir
    tmpdir = tobj

    if use_fd:
        fd = os.open(tmpdir, os.O_RDONLY | os.O_DIRECTORY)
        prefix = tmpdir + "/"
    else:
        fd = None
        prefix = ""
        os.chdir(tmpdir)

    env = SimpleNamespace()
    env.use_fd = use_fd
    env.prefix = prefix
    env.fd = fd
        
    os.mkdir(prefix + "1d")
    os.mkdir(prefix + "2d")
    write_file(env, "1", "1")
    write_file(env, "2", "2")
    os.link(prefix + "1", prefix + "1h1")
    os.link(prefix + "1", prefix + "1h2")
    write_file(env, "1d/1f", "1f")
    write_file(env, "2d/2f", "2f")

    return env

def try_renameat2(env, src, dest, flags, msg="", success=True):
    try:
        if env.use_fd == 2:
            renameat2(src, env.prefix + dest,
                         src_dir_fd=env.fd, dst_dir_fd=None, flags=flags)
        elif env.use_fd == 3:
            renameat2(env.prefix + src, dest,
                         src_dir_fd=None, dst_dir_fd=env.fd, flags=flags)
        else:
            renameat2(src, dest,
                      src_dir_fd=env.fd, dst_dir_fd=env.fd, flags=flags)
    except OSError as e:
        print(f"renameat2({src!r}, {dest!r}, flags={flags!r}) => {e!r}")
        if success == True:
            warn(f"test ${msg} failed: {e!r}")
        else:
            pass
    else:
        print(f"renameat2({src!r}, {dest!r}, flags={flags!r}) => OK")
        if success == False:
            warn(f"test ${msg} failed: no error (should fail)")

def check_file(env, f, check, msg=""):
    try:
        r = read_file(env, f)
        if r != check:
            warn(f"test ${msg} failed: content mismatch: {r!r} <> {check!r}")
    except OSError as e:
        warn(f"test ${msg} failed: {e!r}")

def check_filetest(env, fun, a, msg="", success=True):
    try:
        r = fun(env.prefix + a)
        if ((r and success == False) or (not r and success == True)):
            warn(f"test ${msg} failed: filetest mismatch: {r!r} <> {success!r}")
    except OSError as e:
        warn(f"test ${msg} failed: {e!r}")
    
def try_ok(env, f, a, msg="", success=True):
    try:
        f(env.prefix + a)
    except OSError as e:
        if success:
            warn(f"test ${msg} failed {e!r}")
    else:
        if not success:
            warn(f"test ${msg} failed: no error (should fail)")

def depends_on_arch(default, m):
    return m.get(sys.platform, default)

def file_test(env):
    try_renameat2(env, "1", "3", 0, msg="1")
    check_filetest(env, os.path.exists, "1", msg="1-1", success=False)
    check_file(env, "3", "1", msg="1-3")
    try_renameat2(env, "3", "1", 0, msg="2")
    check_filetest(env, os.path.exists, "3", msg="2-3", success=False)
    check_file(env, "1", "1", msg= "2-1")

def dir_test(env):
    try_renameat2(env, "1d", "3d", 0, msg="3")
    check_filetest(env, os.path.exists, "1d", msg="3-1d", success=False)
    check_file(env, "3d/1f", "1f", msg="3-3d")
    try_renameat2(env, "3d", "1d", 0, msg="4")
    check_filetest(env, os.path.exists, "3d", msg="4-3d", success=False)
    check_file(env, "1d/1f", "1f", msg="4-1d")

def file_file_test(env):
    try_renameat2(env, "1", "2", RENAME_EXCHANGE, msg="5")
    check_file(env, "1", "2", msg="5-1")
    check_file(env, "2", "1", msg="5-2")
    try_renameat2(env, "1", "2", RENAME_EXCHANGE, msg="6")
    check_file(env, "1", "1", msg="6-1")
    check_file(env, "2", "2", msg="6-2")

def file_dir_test(env):
    try_renameat2(env, "1", "2d", RENAME_EXCHANGE, msg="7")
    check_file(env, "1/2f", "2f", msg="7-1")
    check_file(env, "2d", "1", msg="7-2")
    try_renameat2(env, "1", "2d", RENAME_EXCHANGE, msg="8")
    check_file(env, "1", "1", msg="8-1")
    check_file(env, "2d/2f", "2f", msg="8-2")

def dir_file_test(env):
    try_renameat2(env, "1d", "2", RENAME_EXCHANGE, msg="7")
    check_file(env, "1d", "2", msg="7-1")
    check_file(env, "2/1f", "1f", msg="7-2")
    try_renameat2(env, "1d", "2", RENAME_EXCHANGE, msg="8")
    check_file(env, "1", "1", msg="8-1")
    check_file(env, "2d/2f", "2f", msg="8-2")

def dir_dir_test(env):
    try_renameat2(env, "1d", "2d", RENAME_EXCHANGE, msg="7")
    check_file(env, "1d/2f", "2f", msg="7-1")
    check_file(env, "2d/1f", "1f", msg="7-2")
    try_renameat2(env, "1d", "2d", RENAME_EXCHANGE, msg="8")
    check_file(env, "1d/1f", "1f", msg="8-1")
    check_file(env, "2d/2f", "2f", msg="8-2")

def same_same_test (env):
    try_renameat2(env, "1", "1", RENAME_EXCHANGE, msg="9-f")
    check_file(env, "1", "1", msg="9-1")
    try_renameat2(env, "2d", "2d", RENAME_EXCHANGE, msg="10")
    check_file(env, "2d/2f", "2f", msg="10-2")

def file_noclobber_ok_test (env):
    try_renameat2(env, "1", "3", RENAME_NOREPLACE, msg="11-fo")
    check_file(env, "3", "1", msg="11-3")
    try_renameat2(env, "3", "1", RENAME_NOREPLACE, msg="11-of")
    check_file(env, "1", "1", msg="11-1")
    try_renameat2(env, "1d", "3d", RENAME_NOREPLACE, msg="11-do")
    check_file(env, "3d/1f", "1f", msg="11-3d")
    try_renameat2(env, "3d", "1d", RENAME_NOREPLACE, msg="11-od")
    check_file(env, "1d/1f", "1f", msg="11-1d")

def file_noclobber_test (env):
    try_renameat2(env, "1", "2", RENAME_NOREPLACE, success=False, msg="11-ff")
    try_renameat2(env, "1d", "2", RENAME_NOREPLACE, success=False, msg="11-df")
    try_renameat2(env, "1", "2d", RENAME_NOREPLACE, success=False, msg="11-fd")
    try_renameat2(env, "1d", "2d", RENAME_NOREPLACE, success=False, msg="11-dd")

def link_test (env):
    try_renameat2(env, "1h1", "1h2", RENAME_EXCHANGE, msg="12")
    check_file(env, "1h1", "1", msg="12-1")
    check_file(env, "1h2", "1", msg="12-2")

    try_renameat2(env, "1h1", "1h2", 0, msg="13")
    check_file(env, "1h1", "1", msg="13-1")
    check_file(env, "1h2", "1", msg="13-2")
    # rename on the same file keeps original!

    try_renameat2(env, "1h2", "1", RENAME_NOREPLACE, success=False, msg="14")
    # rename no replace raises error!

    try_renameat2(env, "1", "1", RENAME_NOREPLACE,
                  success=depends_on_arch(False, {"darwin": "DONTCARE"}), msg="15")
    # rename no replace raises error! (Darwin succeeds with the same path, Win32 workaround in rename_ex)

    check_file(env, "1", "1", msg="14-1")
    check_file(env, "1h2", "1", msg="14-2")

def rename_corner_test (env):
    os.mkdir(env.prefix + "9d1")
    os.mkdir(env.prefix + "9d2")
    os.mkdir(env.prefix + "9d3")
    write_file(env, "9f3", "9")
    write_file(env, "9f1", "9")
    write_file(env, "9f2", "9")

    # NOREPLACE works, of course
    try_renameat2(env, "9d2", "9d1", RENAME_NOREPLACE, success=False, msg="16-0 d->d")

    # a directory does not overwrite a file (on win32, DOES)
    try_renameat2(env, "9d3", "9f3", 0, success=False, msg="16-1 d->f")

    # a directory DOES overwrite an empty directory! (on win32, doesn't)
    if sys.platform != 'win32':
        try_renameat2(env, "9d2", "9d1", 0, msg="16-2 d->d")
        check_filetest(env, os.path.exists, "9d2", success=False, msg="16-2 exist")
        check_filetest(env, os.path.exists, "9d1", msg="16-2 notexist")
    
    # a directory does not overwrite non-empty directory
    try_renameat2(env, "9d1", "2d", 0, success=False, msg="16-2b d->d")

    # a file does not overwrite an empty directory
    try_renameat2(env, "9f2", "9d1", 0, success=False, msg="16-3 f->d")
    if sys.platform != 'win32':
        check_file(env, "9f2", "9", msg="16-3 read")

    if sys.platform != 'win32':
        # further checking for empty dir overwriting behavior
        try_renameat2(env, "1d", "9d1", 0, msg="16-4 d->d")
        check_file(env, "9d1/1f", "1f", msg="16-4 read")

        try_renameat2(env, "9d1", "1d", 0, msg="16-4 d->d")
        check_file(env, "1d/1f", "1f", msg="16-4 read")

    try_ok(env, os.unlink, "9f1", msg="16-5-1")
    try_ok(env, os.unlink, "9f2", msg="16-5-2")

def run_test (use_fd):
    with tempfile.TemporaryDirectory() as d:
      try:
        env = prepare(d, use_fd=use_fd)
        file_test(env)
        dir_test(env)
        file_file_test(env)
        dir_dir_test(env)
        file_dir_test(env)
        dir_file_test(env)
        same_same_test(env)
        file_noclobber_ok_test(env)
        file_noclobber_test(env)
        link_test(env)
        rename_corner_test(env)
      finally:
        os.chdir("/")


# main test
print(rename_ex.support_status()["str"])

for opt in sys.argv[1:]:
    print(f"\n=== running {opt}")
    if opt == 'native':
        run_test(False)
    elif opt == 'native-fd':
        run_test(True)
    elif opt == 'native-r':
        run_test(2)
    elif opt == 'native-l':
        run_test(3)
    elif opt == 'generic':
        rename_ex.set_use_native(False)
        run_test(False)
    elif opt == 'generic-fd':
        rename_ex.set_use_native(False)
        run_test(True)
    elif opt == 'generic-r':
        rename_ex.set_use_native(False)
        run_test(2)
    elif opt == 'generic-l':
        rename_ex.set_use_native(False)
        run_test(3)
    else:
        raise ValueError
