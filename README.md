# Rename_Ex: Python/Ruby/Perl library for a richer rename primitive in Linux

This library provides an interface to extended OS ability to rename
files etc. in a bit clever ways:

- Rename a file avoiding overwriting existing destination files
- Exchange two files' names
- Specify directory handles (dirfd) for filenames' origins

Currently, this library supports following environments:
 - Linux:
   - fully supported in Python, Ruby and Perl.
   - fairly-recent (after June 2014) Linux needed.
 - MacOS Darwin:
   - supported in Python and Ruby.
   - emulation only on Perl.
 - Windows:
   - supported on Python and Ruby, Perl with NTFS.
   - some limitation exists.

It also provides limited emulation routines for other POSIX compliant environments.

# provided APIs

The main API of the library is named "renameat2", given after the name of the Linux-specific system call.

 - Python: `renameat2(src, dst, *, src_dir_fd=None, dst_dir_fd=None, flags=0)`
 - Ruby: `renameat2(from, to, *, from_dir_fd=nil, to_dir_fd=nil, flags=0)`

The API details in Perl will be described later.

First two arguments are the name of a file to be renamed, and its target name.

If `src_dir_fd` (`from_dir_fd`) contains an open directory handle (`os.open` in Python, `Dir` in Ruby), 
the pathname `src` or `from` will be evaluated relative to the given directory.
By default, it will be relative to the current directory.
The same applies for `dst` or `to` parameters as well.

The flags can be 0 for replacing the destination (if exist) with the
source, or one of the constant below:

 - RENAME_NOREPLACE (1): if the target file exists, the rename will be aborted with EEXIST error.
 - RENAME_EXCHANGE (2): it will exchange the names of two file.

If any error has been occurred, an appropriate exceptions are raised (except in Perl).

All of those actions are atomic, except that there might be a small time window that
the same file will be visible in both names.

## Convenience APIs

There are also three convenience routines exist:
 - `renameat2`: the same functionality without the `flags` argument, replacing the destination.
 - `rename_noreplace`: renames a file without overwriting the destination.
 - `rename_exchange`: renames two files, exchanging these names.
The arguments are as same as `renameat2`, except the last `flags` argument.

# Emulations

If the running environment is not supported, the library will fallback to some limited emulations.

 - Parameters for dir_fd are not supported in some emulated cases.
 - Atomicity is generally lost: there will be a small time window that gives inconsistent results.
   The details of limitation is implementation-specific and subject to change, but do not except even
   that some files are existing on the destination name during the operation. (Impossible for exchange-renaming two non-empty directories.)
 - The emulation is strongly depending on POSIX corner-case behavior, and will not work on non-POSIX underlying OSs.

## Emulation control APIs

 - set_use_native_only(level) will change behavior of above functions
   when native system calls etc. are not available.

   - level = False or 0 (default): the module will emulate the
     behavior as much as possible, using the available language
     features.  In many cases, doing it will loss atomicity
     requirements.
	 
	 See section "Emulations" below for further details.

   - level = True or 1: the functions will fail, if the core behavior
     of the function (e.g. continuity of destination existence) will
     be lost.  These functions will still perform several pre-flight
     checks before calling the native calls to make a consistent
     behavior.  It will however a small window of TOC-TOW race
     conditions in extreme cases.

   - level = 2: the functions will skip any pre-flight check and call
     the native functions as fast as possible.  It will provide the
     most strict sense of atomic behavior, but it may reveal some
     inconsistency with POSIX-like semantics, or expose some "weird"
     behavior of underlying operating systems.

# Language-dependent behaviors

## Python

In Python, the name of the module and for imports are both "`rename_ex`".

The statement `from rename_ex import *` will import the above four
functions starting with `rename`, and two constants for the flags.

The functions will report errors by raising an appropriate exception.

Values for dir_fd parameters are low-level OS handles in integer, opened with 
`os.open(..., O_RDONLY | O_DIRECTORY)`.  `None` can be used for the current directory.

The dir_fd parameters are fully supported, even with emulations, given
the underlying OS supports it.

## Ruby

In Ruby, the library can be required in name `rename_ex`, and available as module `RenameEx`.
Use `import` and `extend` to use the functions and constants without module names.

Named parameters are different from Python's, reflecting the names given in original `File.rename` methods.

The functions will report errors by raising an appropriate exception.

The dir_fd parameters are only available for native functions, not
with emulations.  The dir_fd parameters takes either an integer or a
`Dir` object. For the current directory, `nil` is used.

## Perl

The package is named `File::RenameEx`.

Due to different syntax natures of Perl function interfaces, the dirfd
parameters are passed in an different way.  The Perl API is like
below:

  - `renameat2(srcfile, dstfile, flags)`
  - `renameat2([srcfd, srcname], [dstfd, dstname], flags)`

When an array reference is given in the position of the file name, it will be treated as
a pair of dirfd and a name relative to that directory.
The parameter `srcfd` and `dstfd` can be either an integer or an reference/glob to opened DIRHANDLE by `opendir`.
The current directory is denoted by `undef` in the second syntax.
Both types of arguments can be mixed in a single call.

The dir_fd parameters are only available for Linux.

The functions return a truth value on successful execution, and a
false value in failure.  The OS error is stored in `$!`.

Darwin support is via emulation only; native support requires external
libraries not included in core distribution.

set_use_native_only is not yet implemented in Perl.

# OS-dependent behavior

## Linux

All functionalities and all languages are supported, including dir_fd parameters.

The required system call, `renameat2`, was first implemented in June 2014.

If there are two hard links for the same file, namely 1 and 2, and
when `renameat("1", "2")` is called, the link 1 is not removed and the
call still succeeds.  This is a defined POSIX behavior.

## MacOS (modern Darwin)

MacOS is supported natively on Python and Ruby, using `renameatx_np` system call.

It is not supported with Perl, due to unavailability of `syscall` function.
Limited emulation will be provided.

## Windows (Win32)

In Python and Ruby, all three function flags are supported on NTFS.
Support for dirfd is currently not available.

Note that Python provides `os.replace` and `os.rename` on this platform.

For RENAME_EXCHANGE, the library uses transactional NTFS (TxF) kernel
feature, which is still available in 2026 but being declared as
deprecated.  Unfortunately, current Win32 APIs only provide direct
APIs for replacing and replacing renames, not for exchanges.
If it is called for other network file systems, or TxF support is
terminated, the library will fallback to race-unsafe emulation
routines.

Corner case behavior of Win32 API is quite different from POSIX
systems.  Most cases are covered by pre-flight check, but it may have
small time windows for TOCTOW type race conditions.

If there are two hard links for the same file, namely 1 and 2,
and `rename_noreplace("1", "2")` is called with `set_use_native_only(2)`,
2 is overwritten by 1, or in another phrasing, 1 is silently removed,
regardless of NOREPLACE requests.
This is the as-is NTFS semantics and not our bug.

# Author, Copyright and License

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
