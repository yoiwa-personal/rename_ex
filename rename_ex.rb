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
require 'securerandom'
require 'fiddle'
require 'fiddle/import'

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

  def self._flags_to_display(flags)
    { RENAME_NOREPLACE => "RENAME_NOREPLACE",
      RENAME_EXCHANGE => "RENAME_EXCHANGE" }.fetch(flags, flags.to_s)
  end

  def self._fail_on_nativeonly(flags, cond: true)
    if cond
      raise ArgumentError.new("renameat2(#{self._flags_to_display(flags)}) is not available: use_native_only is set")
    end
  end

  def self._fail_on_unknownflags(flags)
    raise ArgumentError.new("renameat2: unknown flags #{flags}")
  end

  ENV_TYPE_ = Struct.new("ENV_TYPE_", :arch, :native_supported,
                         :undef_flag_passthrough, :exchange_native_supported, :dirfd_supported, keyword_init: true)
  private_constant :ENV_TYPE_

  @@under_debug = $-d
  
  @@use_native = nil ## see set_use_native below
  @@use_native_only = 0

  @@env = ENV_TYPE_.new(
    arch: "generic",
    native_supported: false,
    undef_flag_passthrough: false,
    exchange_native_supported: false,
    dirfd_supported: false)

  def self._reject_dirfd(from_dir_fd, to_dir_fd)
    if from_dir_fd != nil or to_dir_fd != nil
      raise StandardError.new("dir_fd emulation not available")
    end
  end    

  def self._makeoserror(errno, from, to, location: nil)
    return SystemCallError.new("(#{from}, #{to})", errno, location)
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
        raise self._makeoserror(Fiddle::last_error(), oldpath, newpath, location:"_os_renameat2")
      end
      return r
    end

    def _renameat2(from, to, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      from_dir_fd = RenameEx._get_dirfd(from_dir_fd)
      to_dir_fd = RenameEx._get_dirfd(to_dir_fd)

      return RenameEx._os_renameat2(from_dir_fd, from, to_dir_fd, to, flags)
    end

    @@env = ENV_TYPE_.new(
      arch: "linux",
      native_supported: "linux:renameat2",
      undef_flag_passthrough: true,
      exchange_native_supported: true,
      dirfd_supported: true)

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
        raise self._makeoserror(Fiddle::last_error(), oldpath, newpath, location:"_os_renameatx_np")
      end
      return r
    end

    def _renameat2(from, to, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      from_dir_fd = RenameEx._get_dirfd(from_dir_fd)
      to_dir_fd = RenameEx._get_dirfd(to_dir_fd)

      flags = [0, 4, 2][flags]
      return RenameEx._os_renameatx_np(from_dir_fd, from, to_dir_fd, to, flags)
    end

    @@env = ENV_TYPE_.new(
      arch: "darwin",
      native_supported: "darwin:renameatx_np",
      undef_flag_passthrough: false,
      exchange_native_supported: true,
      dirfd_supported: true)

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
      extern 'unsigned long CreateDirectoryTransactedW(void*, void*, void*, unsigned long)'
      extern 'unsigned long RemoveDirectoryTransactedW(void*, unsigned long)'

      # https://github.com/yoiwa-personal/win32_err_map/
      module Win32ErrMap
        DOSERRMAP_H = {
          232 => 32, # EPIPE *
          267 => 20, # ENOTDIR *
          1113 => 42, # EILSEQ
          1816 => 12, # ENOMEM
          10004 =>  4, # EINTR
          10009 =>  9, # EBADF
          10013 => 13, # EACCES
          10014 => 14, # EFAULT
          10022 => 22, # EINVAL
          10024 => 24, # EMFILE
        }
        DOSERRMAP_S = ("222202022413091212120708222222021318021313131313131313131313" +
                       "131313131313132222222222222222222222222222222202222222222222" +
                       "222222222213220222222222222222222222222217221313222222222211" +
                       "222222222222222222222222222222222222133222222822092222222222" +
                       "222222222222222210100922132222222222222222222222224122222222" +
                       "222222222222222213222202222211222213222222222222222222222222" +
                       "222222172222222208080808080808080808080808080822222202222222" +
                       "222222222211222222222222222222222222222222223222222222222222" +
                       "222222222222222222222222222222222222222222222222222222202222" +
                       "222222222222222222222222222222222222222222222222222222222222")
        private_constant :DOSERRMAP_S, :DOSERRMAP_H

        begin
          KNOWNERRORMAX = Errno.constants.map {|x| Errno.const_get(x).const_get(:Errno)}.filter{|x| x < 1000}.max
        rescue
          KNOWNERRORMAX = 140
        end
        def win32_err_map(en)
          if DOSERRMAP_H.include?(en)
            r = DOSERRMAP_H[en]
          elsif 0 <= en and en <= 299
            r = (DOSERRMAP_S.slice(en*2,2).to_i)
          elsif 10000 <= en and en <= 11999
            r = en
          else
            r = 22 # EINVAL
          end
          if en > KNOWNERRORMAX and r == 22
            return en
          else
            return r
          end
        end
        module_function :win32_err_map
      end
      def winsyserror(err, from, to, location)
        SystemCallError.new("(##{err}) - (#{from}, #{to})",
                            Win32ErrMap::win32_err_map(err),
                            location)
      end
      module_function :winsyserror
    end
    private_constant :WIN32KERNEL_

    def self._to_wstr(s)
      (s + "\0").encode('UTF-16LE').force_encoding('BINARY')
    end

    def self._os_MoveFileEx(old, new, flags)
      r = WIN32KERNEL_.MoveFileExW(self._to_wstr(old), self._to_wstr(new), flags.to_i)
      if r == 0
        err = Fiddle::win32_last_error
        raise WIN32KERNEL_::winsyserror(err, old, new, "MoveFileExW")
      end
    end

    class NoTransactionSupported_ < StandardError; end
    class TransactionAborted_ < StandardError; end

    def self._rename_exchange_txf_win32(from, to, to_dir)
      err = nil
      fromw = self._to_wstr(from)
      tow = self._to_wstr(to)

      20.times {
        h_transaction = WIN32KERNEL_.CreateTransaction(nil, nil, 0, 0, 0, 0, nil)
        if h_transaction.null? || h_transaction.to_i == -1
          err = Fiddle::win32_last_error
          if err == 6706 # ERROR_TM_INITIALIZATION_FAILED:
            raise NoTransactionSupported_
          end
          raise WIN32KERNEL_::winsyserror(err, old, new, "CreateTransaction")
        end

        tmpdir = nil
        begin
          20.times {
            t = to_dir + "/..rename." + SecureRandom.alphanumeric(8)

            if WIN32KERNEL_.CreateDirectoryTransactedW(nil, self._to_wstr(t), nil, h_transaction) != 0
              tmpdir = t
              break
            end
            err = Fiddle::win32_last_error
            if err == 183
              continue
            elsif [2005, 6832].include?(err)
              raise RenameEx::NoTransactionSupported_
            elsif [6800, 6706, 6718].include?(err)
              raise RenameEx::TransactionAborted_
            else
              raise WIN32KERNEL_::winsyserror(err, t, to, "_rename_exchange_txf_win32: can't make temporary directory")
            end
          }
        rescue TransactionAborted_
          next
        ensure
          WIN32KERNEL_.CloseHandle(h_transaction) unless tmpdir
        end

	tmp = tmpdir + "/" + ".rename.from"
        tmpw = self._to_wstr(tmp)

        begin
	  if WIN32KERNEL_.MoveFileTransactedW(fromw, tmpw, nil, nil, 0, h_transaction) != 0
            if WIN32KERNEL_.MoveFileTransactedW(tow, fromw, nil, nil, 0, h_transaction) != 0
              if WIN32KERNEL_.MoveFileTransactedW(tmpw, tow, nil, nil, 0, h_transaction) != 0
                if WIN32KERNEL_.RemoveDirectoryTransactedW(self._to_wstr(tmpdir), h_transaction) == 0
                  err = Fiddle::win32_last_error
                  warn "rename_exchange: cleaning tmpdir failed (err): #{tmpdir}"
                end
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
      raise WIN32KERNEL_::winsyserror(err, from, to, "_rename_exchange_txf_win32")
    end

    def self._rename_exchange_win32(from, to, from_dir_fd: nil, to_dir_fd: nil)
      RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)

      fromstat = File.lstat(from)
      tostat = File.lstat(to) # Pass-through FileNotFoundError and others

      return if fromstat.dev == tostat.dev && fromstat.ino == tostat.ino

      basedir = File.dirname(File.absolute_path(to))
      begin
        return self._rename_exchange_txf_win32(from, to, basedir)
      rescue NoTransactionSupported_
        # other exceptions are transferred
        if @@use_native_only >= 1
          raise ArgumentError("renameat2(RENAME_EXCHANGE) is not available (TxF not supported on this os/location)")
        end
        return self._rename_exchange_emulate_by_rename(from, to, dir_to:basedir, fromstat:fromstat, tostat:tostat)
      end
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

    def _renameat2(from, to, from_dir_fd: nil, to_dir_fd: nil, flags: 0)
      RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
      if flags == RENAME_EXCHANGE
        return RenameEx._rename_exchange_win32(from, to)
      end

      fromstat = nil
      tostat = nil
      if @@use_native_only <= 1
        begin
          fromstat = File.lstat(from)
          tostat = File.lstat(to)
          if fromstat.ino == tostat.ino && fromstat.dev == tostat.dev
            # Win32 do rename over the same file with and WITHOUT MOVEFILE_REPLACE_EXISTING !
            return if flags == 0
	    # (with case: in sync with POSIX)
            raise RenameEx._makeoserror(Errno::EEXIST::Errno, from, to, location:"_renameat2")
	    # (without case: clearly a bug)
          end
        rescue Errno::ENOENT
          #
        end
      end
      RenameEx._os_MoveFileEx(from, to, RenameEx._convert_flags_win32(flags))
    end

    @@env = ENV_TYPE_.new(
      arch: "win32",
      native_supported: "win32:MoveFileExW",
      undef_flag_passthrough: false,
      exchange_native_supported: true,
      dirfd_supported: false)
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
      raise self._makeoserror(Errno::EPERM::Errno, from, to, location:"_renameat2_emulate_noreplace")
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
      raise self._makeoserror(Errno::EEXIST::Errno, from, to, location:"_renameat2_emulate_noreplace")
    rescue Errno::ENOENT
      # ok
    end
    return File.rename(from, to)
  end

  def _renameat2_noswapsupport(from, to, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
    if flags == 0 or flags == RENAME_NOREPLACE
      return _renameat2(from, to, from_dir_fd=from_dir_fd, to_dir_fd=to_dir_fd, flags=flags)
    elsif flags == RENAME_EXCHANGE
      if @@use_native_only >= 1
        RenameEx._fail_on_nativeonly(flags)
      end
      return RenameEx._rename_exchange_emulate(from, to)
    else
      RenameEx._fail_on_unknownflags(flags)
    end
  end

  def _renameat2_generic(from, to, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx._reject_dirfd(from_dir_fd, to_dir_fd)
    # The logic is slightly different from Python version, because we do not have os.replace and os.rename
    if flags == 0
      return File.rename(from, to)
      # Ruby's File.rename is always replacing (though it's TOCTOW atomicity is questionable on some architecture)
    elsif @@use_native_only >= 1
      RenameEx._fail_on_nativeonly(flags)
    elsif flags == RENAME_NOREPLACE
      return RenameEx._renameat2_emulate_noreplace(from, to)
    elsif flags == RENAME_EXCHANGE
      return RenameEx._rename_exchange_emulate(from, to)
    else
      RenameEx._fail_on_unknownflags(flags)
    end
  end

  def self._renameat2_choose()
    if @@env.exchange_native_supported && @@use_native
      return :_renameat2
    elsif @@env.native_supported && @@use_native
      return :_renameat2_noswapsupport
    else
      return :_renameat2_generic
    end
  end

  def _renameat2_switcher(from, to, from_dir_fd:nil, to_dir_fd:nil, flags:0)
    RenameEx.method(@@_renameat2_switched).call(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: flags)
  end

  def self.use_native_only(f)
    f = int(f)
    @@native_enforced = f
  end

  def self.set_use_native_only(x)
    if [true, false].include?(x)
      x = x ? 1 : 0
    end
    raise ArgumentError unless x.is_a?(Integer)
    old = @@use_native_only
    @@use_native_only = x
  end

  def self.allow_emulation(x)
    raise ArgumentError unless [true, false].include?(x)
    self.use_native_only(! x)
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
      module_function :renameat2
    end
  end

  self.set_use_native(!! @@env.native_supported)
  
  module_function :renameat2, :_renameat2_generic, :_renameat2_noswapsupport

  def self.support_status
    return { str: "Architecture:                            #{@@env.arch}
Native support for renameat2 or similar: #{@@env.native_supported}
Exchange is supported natively:          #{@@env.exchange_native_supported}
Dir_fd is supported:                     #{@@env.dirfd_supported}
Current Setting:                         #{@@use_native ? 'native' : 'generic emulation'}
Emulation allowed:                       #{@@use_native_only == 0}
Currently used routine:                  #{@@_renameat2_switched}

",
             arch: @@env.arch,
             native_supported: @@env.native_supported,
             exchange_supported: @@env.exchange_native_supported,
             dirfd_supported: @@env.dirfd_supported,
             use_native: @@use_native }
  end

  def rename_noreplace(from, to, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: RENAME_NOREPLACE)
  end

  def rename_exchange(from, to, from_dir_fd:nil, to_dir_fd:nil)
    return renameat2(from, to, from_dir_fd: from_dir_fd, to_dir_fd: to_dir_fd, flags: RENAME_EXCHANGE)
  end
  module_function :rename_noreplace
  module_function :rename_exchange
end
