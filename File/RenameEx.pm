package File::RenameEx;

use 5.32.0;
use strict;
use Exporter 'import';

our @EXPORT = qw(renameat2 RENAME_EXCHANGE RENAME_NOREPLACE);
our @EXPORT_OK = (@EXPORT, '$rename_noreplace_supported', '$rename_exchange_supported');

use Carp;

sub renameat2 ($$$);
use constant RENAME_NOREPLACE => 1;
use constant RENAME_EXCHANGE => 2;

use File::Basename qw(dirname);
use File::Temp qw(tempfile tempdir);
use Errno qw(EACCES ENOENT EEXIST EBUSY);
use Scalar::Util ();

our $rename_noreplace_supported;
our $rename_exchange_supported;
our $rename_atfd_supported;
our $VERSION = v1.0.0;

sub _parse_arg ($$) {
    my ($f, $cur) = @_;
    my ($dirfd);
    if (ref($f) eq 'ARRAY') {
	croak("array arg not supported on this platform") unless defined $cur;
	my @a = @$f;
	croak("bad array argument") unless @a == 2;
	($dirfd, $f) = @a;
	if (! defined $dirfd) {
	    $dirfd = $cur;
	} elsif (Scalar::Util::openhandle($dirfd)
		|| ref($dirfd) eq 'GLOB') {
	    croak("bad directory handle (Perl)") unless defined (telldir $dirfd);
	    $dirfd = fileno($dirfd);
	    croak("bad directory handle (Perl/fno) $dirfd") unless defined $dirfd && $dirfd > 0;
	} elsif (Scalar::Util::looks_like_number($dirfd)) {
	    $dirfd = 0 + $dirfd;
	    croak("bad directory handle (number)") unless defined $dirfd && $dirfd > 0;
	} else {
	    croak("bad directory handle (unknown)" + ref($dirfd));
	}
    } else {
	$dirfd = $cur;
    }
    return ($dirfd + 0, $f . "\0");
}

BEGIN {
    if ($^O eq 'linux') {
	eval {
	    require 'syscall.ph';
	    require POSIX;
	    my $SYS_renameat2 = &SYS_renameat2(); # check for existence
	    # my $RENAME_NOREPLACE = 1; # linux specific value
	    # my $RENAME_EXCHANGE = 2;	# linux specific value
	    my $AT_FDCWD = -100; # linux specific value

	    sub _renameat2_linux ($$$) {
		my ($from, $to, $flags) = @_;
		(my $fromdir, $from) = _parse_arg($from, $AT_FDCWD);
		(my $todir, $to) = _parse_arg($to, $AT_FDCWD);
		$flags = int($flags + 0);
		die unless $flags >= 0 && $flags <= 2;
		my $r = syscall($SYS_renameat2, $fromdir, $from, $todir, $to, $flags);
		return ($r != -1);
	    }
	    $rename_noreplace_supported = $rename_exchange_supported =
	      $rename_atfd_supported = "linux($SYS_renameat2)";
	    *renameat2 = \&_renameat2_linux;
	};
	warn "linux setup failed: $@" if $@;
    } elsif ($^O eq 'MSWin32') {
	eval {
	    package File::RenameEx::Win32ext {
		require Win32::API;

		our $CloseHandle = Win32::API::More->new
		  ('kernel32.dll', 'BOOL CloseHandle(HANDLE hObject)');
		our $MoveFileTransactedA = Win32::API::More->new
		  ( 'kernel32.dll',
		    'BOOL MoveFileTransactedA(LPCSTR lpExistingFileName,
                     LPCSTR lpNewFileName, PVOID lpProgressRoutine,
                     PVOID lpData, DWORD dwFlags, HANDLE hTransaction)');
		our $RemoveDirectoryTransactedA = Win32::API::More->new
		  ( 'kernel32.dll',
		    'BOOL RemoveDirectoryTransactedA(LPCSTR lpPathName, HANDLE hTransaction)');
		our $CreateDirectoryTransactedA = Win32::API::More->new
		  ( 'kernel32.dll',
		    'BOOL CreateDirectoryTransactedA(LPCSTR lpTemplateDirectory,
                     LPCSTR lpNewDirectory, PVOID lpSecurityAttributes, HANDLE hTransaction)');
		our $CreateTransaction = Win32::API::More->new
		  ( 'ktmw32.dll',
		    'HANDLE CreateTransaction(PVOID lpTransactionAttributes,
                     PVOID UOMS, DWORD CreateOptions, DWORD IsolationLevel,
                     DWORD IsolationFlags, DWORD Timeout, LPWSTR Description)');
		our $CommitTransaction = Win32::API::More->new
		  ( 'ktmw32.dll', 'BOOL CommitTransaction(HANDLE hTransaction)');
		our $RollbackTransaction = Win32::API::More->new
		  ('ktmw32.dll', 'BOOL RollbackTransaction(HANDLE hTransaction)');

		my %err_notransaction = map { $_ => 1 } (2005, 6832);
		my %err_transactionabort = map { $_ => 1 } (6800, 6706, 6718);

                # https://github.com/yoiwa-personal/win32_err_map/
                package File::RenameEx::Win32ext::Win32ErrMap {
                    my %__doserrmap = (
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
                                      );

                    my $__doserrmap = ("222202022413091212120708222222021318021313131313131313131313" .
                                       "131313131313132222222222222222222222222222222202222222222222" .
                                       "222222222213220222222222222222222222222217221313222222222211" .
                                       "222222222222222222222222222222222222133222222822092222222222" .
                                       "222222222222222210100922132222222222222222222222224122222222" .
                                       "222222222222222213222202222211222213222222222222222222222222" .
                                       "222222172222222208080808080808080808080808080822222202222222" .
                                       "222222222211222222222222222222222222222222223222222222222222" .
                                       "222222222222222222222222222222222222222222222222222222202222" .
                                       "222222222222222222222222222222222222222222222222222222222222");

                    sub win32_err_map($) {
                        my ($en) = @_;
                        $en = $en + 0;
                        return $__doserrmap{$en} if exists $__doserrmap{$en};
                        if (0 <= $en and $en <= 299) {
                            return 0 + substr($__doserrmap, $en*2, 2);
                        }
                        return $en if (10000 <= $en and $en <= 11999);
                        return 22; # EINVAL
                    }
                }

		sub _translate_error (;$) {
		    my $winerror = ($_[0] // ($^E + 0));
		    $^E = $winerror;
                    my $unixerror = $winerror ? File::RenameEx::Win32ext::Win32ErrMap::win32_err_map($winerror) : 0;
		    $! = $unixerror;
		    return $unixerror;
		}

		{
		    no warnings 'portable';
		    use constant INVALID_HANDLE_VALUE => ((length(pack('P', 0)) == 8) ? hex('ffffffffffffffff') : 0xffffffff);
		}

		sub _rename_exchange_txf_win32 ($$$) {
		    my ($from, $to, $to_dir) = @_;

		    for (my $i = 0; $i < 20; $i++) {
			my $h_transaction = $CreateTransaction->Call(undef, undef, 0, 0, 0, 0, undef);
			if ($h_transaction == INVALID_HANDLE_VALUE) {
			    my $err = $^E + 0;
			    if ($err == 6706) {
				die "_notransaction\n";
			    } else {
				_translate_error($err);
				return 0;
			    }
			}

			my $tmpdir = sprintf("%s/..rename.%04x.%04x.%04x", $to_dir, rand(65536), rand(65536), rand(65536));
			# not cheap (and not strictly required) to use securerandom in Perl, rand is 48 bits

			if (! $CreateDirectoryTransactedA->Call(undef, $tmpdir, undef, $h_transaction)) {
			    my $err = $^E + 0;
			    $CloseHandle->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal CloH_0: $^E";
			    if ($err == 183) {
				next;
			    } elsif ($err_notransaction{$err}) {
				$^E = 0;
				die "_notransaction\n";
			    } elsif ($err_transactionabort{$err}) {
				next;
			    } else {
				_translate_error($err);
				return 0;
			    }
			}
			my $tmpname = $tmpdir . "/" . "..rename.from";

			if ($MoveFileTransactedA->Call($from, $tmpname, undef, undef, 0, $h_transaction) and
			    $MoveFileTransactedA->Call($to, $from, undef, undef, 0, $h_transaction) and
			    $MoveFileTransactedA->Call($tmpname, $to, undef, undef, 0, $h_transaction)) {
			    # succeed!
			    $RemoveDirectoryTransactedA->Call($tmpdir, $h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal RDTA: $^E";
			    $CommitTransaction->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal ComT: $^E";
			    $CloseHandle->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal CloH_1: $^E";
			    $^E = 0;
			    return 1;
			} else {
			    my $err = $^E + 0;
			    if ($err_notransaction{$err}) {
				$RollbackTransaction->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal RbT_2: $^E";
				$CloseHandle->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal CloH_2: $^E";
				$^E = 0;
				die "_notransaction\n";
			    } elsif ($err_transactionabort{$err}) {
				$CloseHandle->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal CloH_3: $^E";
				next;
			    } else {
				$RollbackTransaction->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal RbT_4: $^E";
				$CloseHandle->Call($h_transaction) or Carp::carp "_rename_exchange_txf_win32: internal CloH_4: $^E";
				_translate_error($err);
				return 0;
			    }
			}
		    }
		    $^E = 170; # ERROR_BUSY
		    $! = Errno::EBUSY;
		    return 0;
		}
	    }

            sub _rename_exchange_win32 ($$) {
		my ($from, $to) = @_;
		my $fromstat = _statstr($from);
		my $tostat = _statstr($to);
		if (defined $fromstat && defined $tostat && $fromstat eq $tostat) {
		    return 1;
		}
		local $@;
		my $dir = dirname($to);
		my $r;
		eval {
		    $r = File::RenameEx::Win32ext::_rename_exchange_txf_win32($from, $to, $dir);
		};
		if ($@ eq "_notransaction\n") {
		    return _rename_exchange_generic_by_rename($from, $to);
		} elsif ($@) {
		    die $@;
		}
		return $r;
	    }

            require Win32API::File;

            sub _renameat2_win32 ($$$) {
                my ($from, $to, $flags) = @_;
                _parse_arg($from, undef);
                _parse_arg($to, undef);

                my $fromstat = _statstr($from);
                my $tostat = _statstr($to);

                if (defined $fromstat && defined $tostat && $fromstat eq $tostat) {
                    if ($flags == 0) {return 1;}
                    elsif ($flags == 1) {$! = EEXIST; return 0; }
                    elsif ($flags == 2) {return 1;}
                }
                my $winflags;
                if ($flags == 0) {
		    $winflags = Win32API::File::MOVEFILE_REPLACE_EXISTING();
		} elsif ($flags == RENAME_NOREPLACE) {
		    $winflags = 0;
		} elsif ($flags == RENAME_EXCHANGE) {
                    return _rename_exchange_win32($from, $to);
		} else {
		    $! = Errno::EINVAL;
		    return 0;
		}
		if (Win32API::File::MoveFileEx($from, $to, $winflags)) {
		    $! = 0; $^E = 0;
		    return 1;
		} else {
		    File::RenameEx::Win32ext::_translate_error($^E + 0);
		    return 0;
		}
	    }
	    *renameat2 = \&_renameat2_win32;
	    $rename_noreplace_supported = "Win32API::File";
	    $rename_exchange_supported = "Win32API::TxF";
	};
      	warn "win32 setup failed: $@" if $@;
    }
    # TODO: BSD/MacOS (renameatx_np): needs FFI external module
}

sub _statstr ($) {
    my @r = stat($_[0]);
    @r or return undef;
    join("/", @r)
}

sub _renameat2_generic ($$$) {
    my ($from, $to, $flags) = @_;
    _parse_arg($from, undef);
    _parse_arg($to, undef);
    if ($flags == 0) {
	rename($from, $to);
    } elsif ($flags == RENAME_NOREPLACE) {
	if (-e $to) {
	    $! = EEXIST;
	    return undef;
	}
	rename($from, $to);
    } elsif ($flags == RENAME_EXCHANGE) {
	return _rename_exchange_generic($from, $to);
    }
}

sub _rename_exchange_generic_by_rename($$) {
    # use rename: a $to file vanishes temporarily
    my ($from, $to) = @_;

    unless(-e $to && -e $from) {
	$! ||= ENOENT;
	return undef;
    }
    # temporary file/directory is on "to" file side
    my $dir = dirname($to);

    my ($fh, $tmpname);
    
    my $tmpdir = tempdir("rename.XXXXXX", DIR => $dir, CLEANUP => 0);
    die unless defined $tmpdir;
    $tmpname = $tmpdir . "/..rename.from";

    # first move "from": EXDEV detected here
    unless (rename $from, $tmpname) {
	{
	    local ($!);
            rmdir $tmpdir or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
	}
	return undef;
    }
    unless (rename $to, $from) {
	if ($! == ENOENT) { # same file case
	    if (rename $tmpname, $from) {
                rmdir $tmpdir or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
		return 1;
	    } else {
		carp "rename_exchange: rename(recovery) failed: $!";
		return 0;
	    }
	}
	{
	    local ($!);
	    rename $tmpname, $from or carp "rename_exchange: rename(recovery) failed: $!";
            rmdir $tmpdir or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
	    return undef;
	}
    }
    unless (rename $tmpname, $to) {
	{
	    local ($!);
	    # try recover original file
	    (rename $from, $to and
	     rename $tmpname, $from)
	      or carp "rename_exchange: rename(recovery) failed: $!";
            rmdir $tmpdir or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
	}
	return undef;
    }
    rmdir $tmpdir or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
    return 1;
}
    
sub _rename_exchange_generic($$) {
    # use tmpdir, link and rename
    my ($from, $to, $flags) = @_;

    my $dirto = dirname($to);
    my $dirfrom = dirname($from);

    # write privileges on the directories are required
    unless(-w $dirto && -w $dirfrom) {
	$! ||= EACCES;
	return undef;
    }

    unless(-e $to && -e $from) {
	$! ||= ENOENT;
	return undef;
    }

    # trivial case: the very same name
    return 1 if $from eq $to;

    # same hardlinks: by_rename will not work well
    my $fromstat = _statstr($from);
    my $tostat = _statstr($to);
    return 1 if $fromstat && $tostat && ($fromstat eq $tostat);

    if (-d $to || -d $from) {
	# we have no ways to avoid the brief disappearance;
	#  - files cannot be overwritten by directory (why?)
	#  - non-empty directory cannot be overwritten by directory
	#  - directory cannot be hardlinked
	goto &_rename_exchange_generic_by_rename;
    }

    # temporary directory is on "to" file side
    my $tmp;
    eval {
	$tmp = File::Temp->newdir(".rename.XXXXXX", DIR => $dirto, CLEANUP => 1)
    };
    unless($tmp) {
	$! ||= EACCES;
	return undef;
    }
    my $tmpdir = $tmp->dirname;
    die unless defined $tmpdir;

    my $tmpfrom = "$tmpdir/.exchange.from";
    my $tmpto = "$tmpdir/.exchange.to";

    # first make hardlink of "from" file: EXDEV detected here
    unless (link $from, $tmpfrom) {
	local $!; # hide errors on tmpdir deletion
	undef $tmp;
	return undef;
    }
    unless (link $to, $tmpto) {
	local $!;
	undef $tmp;
	return undef;
    }

    # critical section: files may be lost
    $tmp->unlink_on_destroy(0); # don't wipe the files by myself!

    unless (rename $tmpto, $from) {
	# first rename failed: the files are still in the original state.
	local $!;
	$tmp->unlink_on_destroy(1);
	undef $tmp;
	return undef;
    }

    if (rename $tmpfrom, $to) {
	# both move succeeded: it's safe state now.

	# In usual cases, the tmpdir is empty; If originals are same
	# file (incl. hardlinks), the original temporary files are
	# left (weird behavior of rename syscall).
	
	local $!;
	$tmp->unlink_on_destroy(1);
	undef $tmp;
	return 1;
    } else {
	# OOPS: second rename failed!
	# from is overwritten, but to is not. from is in danger to be lost.

	local $!;
	# try recover original "from" file.
	if (rename $tmpfrom, $from) {
	    # recovery succeed; now safe to remove the tmpdir.
	    # usually it's clear; but when these were the same non-dir files,
	    # hardlinks are remaining.
	    $tmp->unlink_on_destroy(1);
	    undef $tmp;
	} else {
	    # even recovery failed; keep tmpdir for manual last-resort.
	    carp "rename_exchange: rename(recovery) failed: $!; original file \"\Q$from\E\" is left on \"\Q$tmpfrom\E\"";
	}
	return undef;
    }
    ...;
}

*renameat2 = \&_renameat2_generic unless defined $rename_noreplace_supported;

sub rename_noreplace ($$) {
    return renameat2($_[0], $_[1], RENAME_NOREPLACE);
}

sub rename_exchange ($$) {
    return renameat2($_[0], $_[1], RENAME_EXCHANGE);
}

sub renameat ($$) {
    return renameat2($_[0], $_[1], 0);
}    

sub _supported {
    if(wantarray) {
	return ($rename_noreplace_supported, $rename_exchange_supported,
		$rename_atfd_supported);
    } else {
	return sprintf("noreplace: %s\nexchange: %s\natfd: %s",
		       ($rename_noreplace_supported // "(emulation)"),
		       ($rename_exchange_supported // "(emulation)"),
		       ($rename_atfd_supported // "(no)"));
    }
}
