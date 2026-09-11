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
    (fname + "\0").encode(FILESYSTEM_ENCODING)
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

  @@under_debug = $-d
  
  @@use_native = nil ## see set_use_native below
  @@emulation_allowed = true
  @@arch = 'generic'
  @@renameat2_native_supported = false
  @@renameat2_undefflags_passthrough = false
  @@rename_exchange_native_supported = false
  @@renameat2_dirfd_supported = false

  def self._reject_dirfd(from_dir_fd, to_dir_fd)
    if from_dir_fd != nil or to_dir_fd != nil
      raise StandardError.new("dir_fd emulation not available")
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
    @@arch = "linux"
    @@renameat2_native_supported = "linux:renameat2"
    @@renameat2_undefflags_passthrough = true
    @@rename_exchange_native_supported = true
    @@renameat2_dirfd_supported = true

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
    @@arch = "darwin"
    @@renameat2_native_supported = "darwin:renameatx_np"
    @@renameat2_undefflags_passthrough = false
    @@rename_exchange_native_supported = true
    @@renameat2_dirfd_supported = true

  elsif Fiddle.respond_to?(:win32_last_error)
    module WIN32KERNEL_
      extend Fiddle::Importer
      dlload 'ktmw32.dll', 'kernel32.dll'
      extern 'unsigned long MoveFileExW(void *, void *, unsigned long)'
      extern 'unsigned long CommitTransaction(void*)'
      extern 'unsigned long RollbackTransaction(void*)'
      extern 'void* CreateTransaction(void*, void*, unsigned long, unsigned long, unsigned long, unsigned long, void*)'
      extern 'unsigned long MoveFileTransactedW(void*, void*, void*, void*, unsigned long, void*)'
      extern 'unsigned long CloseHandle(void*)'
    end
    private_constant :WIN32KERNEL_

    def self._to_wstr(s)
      (s + "\0").encode('UTF-16LE').force_encoding('BINARY')
    end

    def self._os_MoveFileEx(old, new, flags)
      r = WIN32KERNEL_.MoveFileExW(self._to_wstr(old), self._to_wstr(new), flags.to_i)
      if r == 0
        err = Fiddle::win32_last_error
 	raise SystemCallError.new("MoveFileEx failed #{err}", err)
      end
    end

    class NoTransactionSupported_ < StandardError; end

    def self._rename_exchange_txf_win32(from, to, tmp)
      err = nil
      fromw = self._to_wstr(from)
      tow = self._to_wstr(to)
      tmpw = self._to_wstr(tmp)

      20.times {
        h_transaction = WIN32KERNEL_.CreateTransaction(nil, nil, 0, 0, 0, 0, nil)
        if h_transaction.null? || h_transaction.to_i == -1
          err = Fiddle::win32_last_error
          if err == 6706 # ERROR_TM_INITIALIZATION_FAILED:
            raise _NoTransactionSupported_
          end
          raise SystemCallError("CreateTransaction Failed #{err}", err)
        end

        begin
          if WIN32KERNEL_.MoveFileTransactedW(fromw, tmpw, nil, nil, 0, h_transaction)
            if WIN32KERNEL_.MoveFileTransactedW(tow, fromw, nil, nil, 0, h_transaction)
              if WIN32KERNEL_.MoveFileTransactedW(tmpw, tow, nil, nil, 0, h_transaction)
                if WIN32KERNEL_.CommitTransaction(h_transaction)
                  return true
                end
              end
            end
          end
          err = Fiddle::win32_last_error
          if [2005, 6832].include?(err) # ERROR_VOLUME_NOT_SUPPORTED, ERROR_TRANSACTIONAL_OPEN_NOT_ALLOWED
            raise _NoTransactionSupported
          elsif [6800, 6706, 6718].include?(err)
            # ERR_TRANSACTIONAL_CONFLICT, ERROR_TRANSACTION_ALREADY_ABORTED, ERROR_TRANSACTION_NOT_ACTIVE
            next
          else
            WIN32KERNEL_.RollbackTransaction(h_transaction)
            break
          end
        ensure
          WIN32KERNEL_.CloseHandle(h_transaction)
        end
      }
      raise SystemCallError("Exchanging File Failed #{err}", err)
    end

    def self._rename_exchange_win32(from, to, *, from_dir_fd: nil, to_dir_fd: nil)
      RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)

      fromstat = File.lstat(from)
      tostat = File.lstat(to) # Pass-through FileNotFoundError and others

      return if fromstat.dev == tostat.dev && fromstat.ino == tostat.ino

      basedir = File.dirname(File.absolute_path(to))
      tmpdir = Dir.mktmpdir("..rename.", tmpdir: basedir)
      tmpname = tmpdir + "/" + ".rename.from"

      begin
        return self._rename_exchange_txf_win32(from, to, tmpname)
      rescue NoTransactionSupported_
        # other exceptions are transferred
      ensure
        Dir.rmdir(tmpdir)
      end
      if ! @@emulation_allowed
        raise ValueError("renameat2(RENAME_EXCHANGE) is not available (txf not supported on this os/location)")
      end
      return self._rename_exchange_emulate_by_rename(from, to, dir_to:basedir, fromstat:fromstat, tostat:tostat)
    end

    def self._convert_flags_win32(flags)
      if flags == 0
        return 1 # MOVEFILE_REPLACE_EXISTING
      elsif flags == RENAME_NOREPLACE
        return 0
      #elsif flags == RENAME_EXCHANGE
      #  raise ValueError
      else
        raise ArgumentError.new("bad flags in renameat2")
      end
    end

    def _renameat2(from, to, *, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
      if flags == RENAME_EXCHANGE
        return RenameEx._rename_exchange_win32(from, to)
      end

      fromstat = nil
      tostat = nil
      begin
        fromstat = File.lstat(from)
        tostat = File.lstat(to)
        if fromstat.ino == tostat.ino && fromstat.dev == tostat.dev
          # Win32 do rename over the same file with and WITHOUT MOVEFILE_REPLACE_EXISTING !
          return if flags == 0 # (with case: in sync with POSIX)
          raise Errno::EEXIST  # (without case: clearly a bug)
        end
      rescue Errno::ENOENT
        #
      end

      RenameEx._os_MoveFileEx(from, to, RenameEx._convert_flags_win32(flags))
    end

    @@arch = "win32"
    @@renameat2_native_supported = "win32:MoveFileExW"
    @@renameat2_undefflags_passthrough = false
    @@rename_exchange_native_supported = true
    @@renameat2_dirfd_supported = false
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
  
  def self._rename_exchange_emulate_by_rename(from, to, dir_to:, fromstat: , tostat: )
    tmpdir = Dir.mktmpdir("..rename.", tmpdir: dir_to)
    tmpname = tmpdir + "/.rename.from"

    begin
      File.rename(from, tmpname)
    rescue StandardError => e
      begin
        Dir.rmdir(tmpdir)
      rescue StandardError => ee
        warn "rename_exchange: rmdir(recovery) tmporary dir failed: #{ee}"
      end
      raise e
    end

    begin
      File.rename(to, from)
    rescue StandardError => e
      begin
        File.rename(tmpname, from)
        Dir.rmdir(tmpdir)
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
        Dir.rmdir(tmpdir)
      rescue StandardError => ee
        warn "rename_exchange: rename(recovery) 2 tmporary file failed:#{ee}: #{from} is left as #{tmporary}"
      end
      raise e
    end
    begin
      Dir.rmdir(tmpdir)
    rescue StandardError => ee
      warn "rename_exchange: removig tmpdir failed:#{ee}"
    end
  end

  def self._rename_exchange_emulate_by_link(from, to, dir_to: )
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
        File.unlink(tmpfrom)
        Dir.rmdir(tmpdir)
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

  def self._rename_exchange_emulate(from, to)
    dir_from = File.dirname(File.absolute_path(from))
    dir_to = File.dirname(File.absolute_path(to))

    if not (FileTest.writable?(dir_from) && FileTest.writable?(dir_to))
      raise Errno::EPERM
    end

    fromstat = File.lstat(from)
    tostat = File.lstat(to) # Pass-through FileNotFoundError and others

    if fromstat.dev == tostat.dev && fromstat.ino == tostat.ino
      return
    end

    if fromstat.directory? or tostat.directory?
      return self._rename_exchange_emulate_by_rename(from, to, dir_to:dir_to, fromstat:fromstat, tostat:tostat)
    else
      return self._rename_exchange_emulate_by_link(from, to, dir_to:dir_to)
    end
  end

  def self._renameat2_emulate_noreplace(from, to)
    begin
      File.lstat(to)
      raise Errno::EEXIST
    rescue Errno::ENOENT
      # ok
    end
    return File.rename(from, to)
  end

  def _renameat2_noswapsupport(from, to, *, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
    if flags == 0 or flags == RENAME_NOREPLACE
      return _renameat2(from, to, from_dir_fd=from_dir_fd, to_dir_fd=to_dir_fd, flags=flags)
    elsif flags == RENAME_EXCHANGE
      if not @@emulation_allowed
        raise ArgumentError.new("renameat2(#{flags}) is not available")
      end
      return RenameEx._rename_exchange_emulate(from, to)
    else
      raise ArgumentError.new("renameat2(#{flags}) is unknown")
    end
  end

  def _renameat2_generic(from, to, *, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
    if flags == 0
      return File.rename(from, to) # Ruby's File.rename is always replacing
    elsif not @@emulation_allowed
      raise ArgumentError.new("renameat2(#{flags}) is not available")
    elsif flags == RENAME_NOREPLACE
      return RenameEx._renameat2_emulate_noreplace(from, to)
    elsif flags == RENAME_EXCHANGE
      return RenameEx._rename_exchange_emulate(from, to)
    else
      raise ArgumentError.new("renameat2(#{flags}) is unknown")
    end
  end

  def self._renameat2_choose()
    if @@rename_exchange_native_supported && @@use_native
      return :_renameat2
    elsif @@renameat2_native_supported && @@use_native
      return :_renameat2_noswapsupport
    else
      return :_renameat2_generic
    end
  end

  def _renameat2_switcher(from, to, *, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx.method(@@_renameat2_switched).call(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: flags)
  end

  def self.allow_emulation(x)
    raise ArgumentError unless [true, false].include?(x)
    @@emulation_allowed = x
  end
  
  def self.set_use_native(x)
    raise ArgumentError unless [true, false].include?(x)
    @@use_native = x
    @@_renameat2_switched = RenameEx._renameat2_choose()
    if @@under_debug
      alias :renameat2 :_renameat2_switcher
    else
      case @@_renameat2_switched
      when :_renameat2
        alias :renameat2 :_renameat2
      when :_renameat2_noswapsupport
        alias :renameat2 :_renameat2_noswapsupport
      when :_renameat2_generic
        alias :renameat2 :_renameat2_generic
      end
    end
  end

  self.set_use_native(!! @@renameat2_native_supported)
  
  module_function :renameat2, :_renameat2_generic, :_renameat2_noswapsupport

  def self.support_status
    return { str: "Architecture:                            #{@@arch}
Native support for renameat2 or similar: #{@@renameat2_native_supported}
Exchange is supported natively:          #{@@rename_exchange_native_supported}
Dir_fd is supported:                     #{@@renameat2_dirfd_supported}
Current Setting:                         #{@@use_native ? 'native' : 'generic emulation'}
Emulation allowed:                       #{@@emulation_allowed}
Currently used routine:                  #{@@_renameat2_switched}

",
             arch: @@arch,
             native_supported: @@renameat2_native_supported,
             exchange_supported: @@rename_exchange_native_supported,
             dirfd_supported: @@renameat2_dirfd_supported,
             use_native: @@use_native }
  end

  def rename_noreplace(from, to, *, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: RENAME_NOREPLACE)
  end

  def rename_exchange(from, to, *, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: RENAME_EXCHANGE)
  end
  module_function :rename_noreplace
  module_function :rename_exchange
end
