# Rename_Ex: Python/Ruby/Perl library for a richer rename primitive in Linux

This library provides an interface to extended OS capabilities for renaming
files in smarter ways:

- Rename a file while avoiding overwriting existing destination files
- Exchange two files' names
- Specify directory handles (dirfd) for filenames' origins

Currently, this library supports the following environments:
 - Linux:
   - Fully supported in Python, Ruby, and Perl.
   - Requires a fairly recent Linux kernel (June 2014 or later).
 - macOS (Darwin):
   - Supported in Python and Ruby.
   - Emulation only in Perl.
 - Windows:
   - Supported in Python and Ruby; supported in Perl with NTFS.
   - Some limitations exist.

It also provides limited emulation routines for other POSIX-compliant environments.

# Provided APIs

The main API of the library is named `renameat2`, after the Linux-specific system call.

 - Python: `renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0)`
 - Ruby: `renameat2(from, to, *, from_dir_fd=nil, to_dir_fd=nil, flags=0)`

The Perl API details are described below.

The first two arguments are the name of the file to be renamed and its target name.

If `src_dir_fd` (`from_dir_fd`) contains an open directory handle (`os.open` in Python, `Dir` in Ruby), 
the pathname `src` or `from` will be evaluated relative to the given directory.
By default, it is relative to the current directory.
The same applies to the `dst` or `to` parameters.

The `flags` argument can be `0` for replacing the destination (if it exists) with the
source, or one of the constants below:

 - `RENAME_NOREPLACE` (1): If the target file exists, the rename operation will abort with an `EEXIST` error.
 - `RENAME_EXCHANGE` (2): Atomically exchanges the names of two files.

If an error occurs, an appropriate exception is raised (except in Perl).

All of these actions are atomic, except that there might be a small window of time during which
the file is visible under both names.

## Convenience APIs

Three convenience routines are also provided:
 - `renameat2`: The same functionality without the `flags` argument, replacing the destination.
 - `rename_noreplace`: Renames a file without overwriting the destination.
 - `rename_exchange`: Renames two files, exchanging their names.

The arguments are the same as `renameat2`, except for the missing `flags` argument.

# Emulations

If the running environment is not natively supported, the library will fall back to limited emulation.

 - Parameters for `dir_fd` are not supported in some emulated cases.
 - Atomicity is generally lost: there will be a small window of time that produces inconsistent results.
   The specific limitations depend on the implementation and are subject to change,
   but do not expect destination files to remain intact during exchange operations.
   (For example, exchange-renaming two non-empty directories is impossible under emulation.)
 - Emulation relies heavily on POSIX corner-case behavior and will not work on non-POSIX underlying OSs.

## Emulation Control APIs

 - `set_use_native_only(level)` will change the behavior of the above functions
   when native system calls are unavailable.

   - `level = False` or `0` (default): The module will emulate the
     behavior as much as possible using available language
     features. In many cases, doing so will lose atomicity.
	 
	 See the section "Emulations" below for further details.

   - `level = True` or `1`: The functions will fail if the core behavior
     of the function (e.g., continuity of destination existence) would be lost.
     These functions will still perform several pre-flight checks before calling
     the native functions to maintain consistent behavior. It will, however, leave
     a small window of TOCTOU race conditions in extreme cases.

   - `level = 2`: The functions will skip any pre-flight checks and call
     the native functions as fast as possible. This provides the
     strictest sense of atomic behavior, but it may reveal some
     inconsistencies with POSIX-like semantics or expose "weird"
     behavior of the underlying operating system.

## Emulation Details

The following implementation details are subject to change in the future and may be outdated:

 - Replacing rename (`flags=0`):
   
   When the OS's default rename function is non-replacing, the emulation
   will remove the destination file just before renaming.

   There will be a window of time during which the destination does not exist, 
   and under race conditions, the rename might fail.
   
 - Non-replacing rename (`flags=1`):
 
   When the OS's default rename function is replacing, the emulation
   will first check for the existence of the destination file, and if
   it exists, report an emulated OS error.
   
   Under race conditions, a file may be accidentally overwritten.

 - Exchanging rename (`flags=2`):
 
   If the OS is Unix-like, supports hard links and replacing rename,
   and both targets are non-directory files, the emulation will create a
   temporary directory, make two hard links for the source and destination,
   and then overwrite the original locations using replacing renames.
   There will be no window of time with unoccupied locations, but
   accidental overwriting might occur under race conditions.

   If any of the above conditions are not met, the emulation will
   simply exchange the source and destination using a temporary name.
   There will be a small window of time where neither original location is
   occupied by a file.
   
   Checking the above conditions might also cause a TOCTOU race
   condition. If this occurs, the emulation might throw
   unexpected errors or get stuck in an unrecoverable state. In some
   cases, temporary directories may remain after such an error.

# Language-Dependent Behaviors

## Python

In Python, the module name and import target are both "`rename_ex`".

The statement `from rename_ex import *` will import the four
functions starting with `rename`, along with two constants for the flags.

Functions report errors by raising appropriate exceptions.

Values for `dir_fd` parameters are low-level OS handles represented as integers, opened with 
`os.open(..., O_RDONLY | O_DIRECTORY)`. `None` can be used for the current directory.

The `dir_fd` parameters are fully supported even with emulation, provided
the underlying OS supports it.

## Ruby

In Ruby, the library can be required using `rename_ex`, and is available as the module `RenameEx`.
Use `import` and `extend` to use the functions and constants without specifying module names.

Named parameters differ from Python's to reflect the parameter names in the standard `File.rename` method.

Functions report errors by raising appropriate exceptions.

The `dir_fd` parameters are only available for native functions, not under emulation.
`dir_fd` parameters accept either an integer or a `Dir` object. For the current directory, `nil` is used.

## Perl

The package is named `File::RenameEx`.

Due to syntax differences in Perl function interfaces, `dirfd`
parameters are passed differently. The Perl API is as follows:

  - `renameat2(srcfile, dstfile, flags)`
  - `renameat2([srcfd, srcname], [dstfd, dstname], flags)`

When an array reference is passed in place of a file name, it is treated as
a pair consisting of a `dirfd` and a name relative to that directory.
The `srcfd` and `dstfd` parameters can be either an integer or a reference/glob to an opened `DIRHANDLE` (via `opendir`).
The current directory is denoted by `undef` in the second syntax.
Both argument types can be mixed in a single call.

The `dir_fd` parameters are only available on Linux.

The functions return a truthy value on successful execution and a
false value on failure. The OS error is stored in `$!`.

macOS (Darwin) support is via emulation only; native support requires external
libraries not included in the core distribution.

`set_use_native_only` is not yet implemented in Perl.

# OS-Dependent Behavior

## Linux

All functionalities and languages are supported, including `dir_fd` parameters.

The required system call, `renameat2`, was introduced in June 2014.

If there are two hard links for the same file (e.g., `1` and `2`), and
`renameat("1", "2")` is called, link `1` is not removed and the
call succeeds. This is standard POSIX behavior.

## macOS (Modern Darwin)

macOS is supported natively in Python and Ruby using the `renameatx_np` system call.

It is not natively supported in Perl due to the unavailability of the `syscall` function.
Limited emulation is provided instead.

## Windows (Win32)

In Python and Ruby, all three function flags are supported on NTFS.
Support for `dirfd` is currently unavailable.

Note that Python provides `os.replace` and `os.rename` on this platform.

For `RENAME_EXCHANGE`, the library uses the Transactional NTFS (TxF) kernel
feature, which remains available in 2026 but has been declared
deprecated. Unfortunately, current Win32 APIs only provide direct
APIs for replacing and non-replacing renames, not for exchanges.
If it is called on other network file systems, or if TxF support is
discontinued, the library will fall back to race-unsafe emulation
routines.

The corner-case behavior of Win32 APIs is quite different from POSIX
systems. Most cases are covered by pre-flight checks, but small time windows
for TOCTOU race conditions may still exist.

If there are two hard links for the same file (e.g., `1` and `2`),
and `rename_noreplace("1", "2")` is called with `set_use_native_only(2)`,
`2` is overwritten by `1` (or in other words, `1` is silently removed),
regardless of the `NOREPLACE` request.
This reflects native NTFS semantics and is not a library bug.

# Author, Copyright, and License

(c) 2026 Yutaka OIWA <yutaka@oiwa.jp>.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
