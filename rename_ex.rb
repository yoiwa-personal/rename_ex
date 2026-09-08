# -*- ruby -*-
# Ruby library providing additional rename functionality
#
# https://github.com/yoiwa-personal/rename_ex/
#
# Copyright 2019 Yutaka OIWA <yutaka@oiwa.jp>.
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

require 'tempfile'
require 'fiddle'
require 'fiddle/import'
require 'forwardable'

module RenameEx
  RENAME_NOREPLACE = 1
  RENAME_EXCHANGE = 2
  
  FILESYSTEM_ENCODING = Encoding.find("filesystem")
  private_constant :FILESYSTEM_ENCODING

  def self._fnencode(fname)
    fname.encode(FILESYSTEM_ENCODING)
  end

  def self._get_dirfd(dir)
    if dir == nil
      return AT_FDCWD
    elsif dir.is_a?(Dir)
      return dir.fineno
    elsif dir.is_a?(Integer)
      return dir
    else
      raise ValueError
    end
  end

  if RUBY_PLATFORM.include?('-linux')
    module LIBC
      extend Fiddle::Importer
      dlload "libc.so.6"
      extern "int renameat2(int, const char *, int, const char *, unsigned int)"
    end
    private_constant :LIBC
    AT_FDCWD = -100

    def self._os_renameat2(olddirfd, oldpath, newdirfd, newpath, flags)
      oldb = self._fnencode(oldpath)
      newb = self._fnencode(newpath)

      r = LIBC::renameat2(olddirfd, oldb, newdirfd, newb, flags)
      if r == -1
        raise SystemCallError.new(Fiddle::last_error())
      end
      return r
    end

    def _renameat2(from, to, *, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      from_dir_fd = RenameEx._get_dirfd(from_dir_fd)
      to_dir_fd = RenameEx._get_dirfd(to_dir_fd)

      return RenameEx._os_renameat2(from_dir_fd, from, to_dir_fd, to, flags)
    end
    renameat2_supported = true

  elsif RUBY_PLATFORM.include?('-darwin')
    module LIBC
      extend Fiddle::Importer
      dlload 'libc.dylib'
      extern 'int renameatx_np(int, const const char *, int, const char *, unsigned int)'
    end
    private_constant :LIBC
    AT_FDCWD = -2

    def self._os_renameatx_np(olddirfd, oldpath, newdirfd, newpath, flags)
      oldb = self._fnencode(oldpath)
      newb = self._fnencode(newpath)

      r = LIBC::renameatx_np(olddirfd, oldb, newdirfd, newb, flags)
      if r == -1
        raise SystemCallError.new(Fiddle::last_error())
      end
      return r
    end

    def _renameat2(from, to, *, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      from_dir_fd = RenameEx._get_dirfd(from_dir_fd)
      to_dir_fd = RenameEx._get_dirfd(to_dir_fd)

      flags = [0, 4, 2][flags]
      return RenameEx._os_renameatx_np(from_dir_fd, from, to_dir_fd, to, flags)
    end
    renameat2_supported = true

  end

  def self._mktempnode(dir, mkdir)
    if (dir == '')
      dir = "."
    end
    dir = File.absolute_path(dir)

    openflags = (File::RDWR | File::CREAT | File::NOFOLLOW | File::EXCL)
    if mkdir
      f = lambda { |name| Dir.mkdir name, mode=0o700 }
    else
      f = lambda { |name| open name, openflags, 0o600 }
    end

    fname = nil
    require 'securerandom'
    20.times {
      token = SecureRandom.alphanumeric(8)
      begin
        fname = dir + "/.rename-" + token
        fd = f.call(fname)
      rescue Errno::EEXIST
        continue
      end
      return fd, fname
    }
    raise Errno::EBUSY
  end
  
  def self._rename_exchange_generic_by_rename(from, to)
    fromstat = File.lstat(from)
    tostat = File.lstat(to) # Pass-through FileNotFoundError and others

    if fromstat.dev == tostat.dev && fromstat.ino == tostat.ino
      return
    end

    tmpisdir = fromstat.directory?
    
    basedir = File.dirname(File.absolute_path(to))
    if tmpisdir
      tmpname = Dir.mktmpdir("..rename.", tmpdir: basedir)
    else
      fd, tmpname = self._mktempnode(basedir, false)
      fd.close
    end

    begin
      File.rename(from, tmpname)
    rescue StandardError => e
      if tmpisdir
        begin
          Dir.rmdir(tmpname)
        rescue StandardError => ee
          warn "rename_exchange: rmdir(recovery) tmporary dir failed: #{ee}"
        end
      else
        begin
          File.delete(tmpname)
        rescue StandardError => ee
          warn "rename_exchange: unlink(recovery) tmporary file failed: #{ee}"
        end
      end
      raise e
    end

    begin
      File.rename(to, from)
    rescue StandardError => e
      begin
        File.rename(tmpname, from)
      rescue StandardError => ee
        warn "rename_exchange: rename(recovery) 1 tmporary file failed: #{ee}"
      end
      if e.is_a?(Errno::ENOENT)
        return
      else
        raise e
      end
    end

    begin
      File.rename(tmpname, to)
    rescue StandardError => e
      begin
        File.rename(from, to)
        File.rename(tmpname, from)
      rescue StandardError => ee
        warn "rename_exchange: rename(recovery) 2 tmporary file failed:#{ee}: #{from} is left as #{tmporary}"
      end
      raise e
    end
  end

  def self._rename_exchange_generic(from, to)
    dir_from = File.dirname(from)
    dir_to = File.dirname(to)

    if not (FileTest.writable?(dir_from) && FileTest.writable?(dir_to))
      raise Errno::EPERM
    end

    fromstat = File.lstat(from)
    tostat = File.lstat(to) # Pass-through FileNotFoundError and others

    if fromstat.dev == tostat.dev && fromstat.ino == tostat.ino
      return
    end

    if fromstat.directory? or tostat.directory?
      return self._rename_exchange_generic_by_rename(from, to)
    end

    tmpdir = Dir.mktmpdir("..rename.", tmpdir=dir_to)

    tmpfrom = tmpdir + "/.exchange.from"
    tmpto = tmpdir + "/.exchange.to"
    
    begin
      File.link(from, tmpfrom)
    rescue StandardError => e
      begin
        Dir.rmdir(tmpdir)
      rescue StandardError => ee
        warn("rename_exchange: cleaning tmpdir failed: #{ee}")
      end
      raise e
    end

    begin
      File.link(to, tmpto)
    rescue StandardError => e
      begin
        File.unlink(tmpfrom, dir_fd=tmp_dir_fd)
        Dir.rmdir(tmpdir, dir_fd=tmp_dir_fd)
      rescue StandardError => ee
        warn("rename_exchange: cleaning tmpdir failed: #{ee}")
      end
      raise e
    end

    # critical section: files may be lost
    begin
      File.rename(tmpto, from)
    rescue StandardError => e
      # still safe...
      begin
        File.delete(tmpto)
        File.delete(tmpfrom)
        Dir.rmdir(tmpdir)
      rescue StandardError => ee
        warn("rename_exchange: cleaning tmpdir failed: #{ee}")
      end
      raise e
    end
    
    begin
      File.rename(tmpfrom, to)
    # now safe
    rescue StandardError => e
      # in danger: from is about to lost
      begin
        File.rename(tmpfrom, from)
      rescue StandardError => ee
        warn("rename_exchange: rename for recovery failed: #{ee}: original file #{from} is left on #{tmpfrom}")
        # don't touch on temporary directory!
        raise e
      end
      # now safe: only tmpdir is exist
      begin
        Dir.rmdir(tmpdir)
      rescue StandardError => ee
        warn("rename_exchange: cleaning tmpdir failed: #{ee}")
      end
      raise
    end

    # here, the directory should be empty:
    # however, if from and to are the same file, tmp files are left.
    begin
      begin
        File.delete(tmpto)
        File.delete(tmpfrom)
      rescue Errno::ENOENT
      end
      Dir.rmdir(tmpdir)
    rescue StandardError => ee
      warn("rename_exchange: cleaning tmpdir failed: #{ee}")
      raise ee
    end
  end

  def _renameat2_generic(from, to, *, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    if from_dir_fd != nil or to_dir_fd != nil
      raise StandardError.new("dir_fd emulation not available")
    end
    if flags == 0
      return File.rename(from, to)
    elsif flags == RENAME_NOREPLACE
      begin
        File.lstat(to)
        raise Errno::EEXIST
      rescue Errno::ENOENT
        # ok
      end
      return File.rename(from, to)
    elsif flags == RENAME_EXCHANGE
      return RenameEx._rename_exchange_generic(from, to)
    end
  end

  if renameat2_supported
    alias :renameat2 :_renameat2
  else
    alias :renameat2 :_renameat2_generic
  end
  
  module_function :renameat2, :_renameat2_generic

  def rename_noreplace(from, to, *, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to,
                     from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd,
                     flags: RENAME_NOREPLACE)
  end

  def rename_exchange(from, to, *, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to,
                     from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd,
                     flags: RENAME_EXCHANGE)
  end
  module_function :rename_noreplace
  module_function :rename_exchange
end
