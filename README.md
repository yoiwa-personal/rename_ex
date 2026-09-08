# Rename_Ex: Python/Ruby/Perl library for a richer rename primitive in Linux

This library provides an interface to Linux ability to rename files etc. in a bit clever ways:

- Rename a file avoiding overwriting existing destination files
- Exchange two files' names
- Specify directory handles (dirfd) for filenames' origins

Currently, this library supports the following environments:
 - Linux: 
   - fully supported in Python, Ruby and Perl; uses `renameat2` system call.
   - fairly-recent (after June 2014) Linux needed.
 - MacOS Darwin:
   - supported in Python and Ruby; uses `renameatx_np` system call.
   - emulation only on Perl.
 - Windows: 
   - supported on Python and Ruby; MoveFileExW and Transactional NTFS are used.
   - some limited functionality in Perl.

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

The flags can be 0 for usual rename(2) behavior, or one of the constant below:

 - RENAME_NOREPLACE: if the target file exists, the rename will be aborted with EEXIST error.
 - RENAME_EXCHANGE: it will exchange the names of two file.

If any error has been occurred, an appropriate exceptions are raised (except in Perl).

All of those actions are atomic, except that there might be a small time window that
the same file will be visible in both names.

## convenience APIs

There are also three convenience routines exist:
 - `renameat2`: the same functionality without the `flags` argument.
 - `rename_noreplace`: renames a file without overwriting the destination.
 - `rename_exchange`: renames two files, exchanging the names.
The arguments are as same as `renameat2`, except the last `flags` argument.

# Language-dependent behaviors

## Python

In Python, the name of module and imports are both "`rename_ex`".

Dirfd parameters are low-level OS handles in integer, opened with 
`os.open(..., O_RDONLY | O_DIRECTORY)`.  `None` can be used for the current directory.

The dirfd parameters are fully supported, even with emulations.

## Ruby

In Ruby, the library can be required in name `rename_ex`, and available as module `RenameEx`.

Named parameters are different from Python's, reflecting the names given in original `File.rename` methods.

Dirfd parameters takes either an integer or a `Dir` object. For current directory, `nil` is used.

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

The functions return a truth value on successful execution, and a false in failure.
The OS error is stored in `$!`.

Darwin support is via emulation only; native support requires external
libraries not included in core distribution.

Windows support is limited: RENAME_EXCHANGE is emulated and does not support dir_fd.

# Emulations

If the running environment is not supported, the library will fallback to some limited emulations.

 - In Ruby and Perl, dir_fd are not supported in emulated cases.
 - Atomicity is generally lost: there will be a small time window that gives inconsistent results.
   The details of limitation is implementation-specific and subject to change, but do not except even
   that some files are existing on the destination name during the operation. (Impossible for exchange-renaming two non-empty directories.)
 - The emulation is strongly depending on POSIX corner-case behavior, and will not work on non-POSIX underlying OSs.

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
