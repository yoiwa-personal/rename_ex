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
use Errno qw(EACCES ENOENT);
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
    return ($dirfd + 0, $f . "");
}

BEGIN {
    if ($^O eq 'linux') {
	eval {
	    require 'syscall.ph';
	    require POSIX;
	    my $SYS_renameat2 = &SYS_renameat2(); # check for existence
	    # my $RENAME_NOREPLACE = 1; # linux specific value
	    # my $RENAME_EXCHANGE = 2;  # linux specific value
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
	    require Win32API::File;

	    sub _renameat2_win32 ($$$) {
		my ($from, $to, $flags) = @_;
		_parse_arg($from, undef);
		_parse_arg($to, undef);

		my $winflags = Win32API::File::MOVEFILE_REPLACE_EXISTING();
		if ($flags == 0) {
		} elsif ($flags == RENAME_NOREPLACE) {
		    $winflags = 0;
		} elsif ($flags == RENAME_EXCHANGE) {
		    return _rename_exchange_generic($from, $to);
		}
		return Win32API::File::MoveFileEx($from, $to, $winflags);
	    }
	};
	*renameat2 = \&_renameat2_win32;
	$rename_noreplace_supported = "Win32API::File";
    }
}
# TODO: BSD/MacOS (renameatx_np)

sub _renameat2_generic ($$$) {
    my ($from, $to, $flags) = @_;
    _parse_arg($from, undef);
    _parse_arg($to, undef);
    if ($flags == 0) {
	rename($from, $to);
    } elsif ($flags == RENAME_NOREPLACE) {
	if (-e $to) {
	    require Errno;
	    $! = &Errno::EEXIST;
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
    
    if (-d $from) {
	# empty directory can be overwritten by directory
	$tmpname = tempdir("rename.XXXXXX", DIR => $dir, CLEANUP => 0);
	die unless defined $tmpname;
    } else {
	($fh, $tmpname) = tempfile("rename.XXXXXX", DIR => $dir, UNLINK => 0);
	die unless defined $tmpname;
	close $fh;
    }

    # first move "from": EXDEV detected here
    unless (rename $from, $tmpname) {
	{
	    local ($!);
	    if (-d $from) {
		rmdir $tmpname or carp "rename_exchange: rmdir(recovery) temporary dir failed: $!";
	    } else {
		unlink $tmpname or carp "rename_exchange: unlink(recovery) temporary file failed: $!";
	    }
	}
	return undef;
    }
    unless (rename $to, $from) {
	{
	    local ($!);
	    rename $tmpname, $from or carp "rename_exchange: rename(recovery) failed: $!";
	}
	return undef;
    }
    unless (rename $tmpname, $to) {
	{
	    local ($!);
	    # try recover original file
	    rename $tmpname, $from or carp "rename_exchange: rename(recovery) failed: $!";
	}
	return undef;
    }
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

    # trivial case: the very same name; hardlinks are not treated
    return 1 if $from eq $to;

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
    goto &renameat2($_[0], $_[1], RENAME_NOREPLACE);
}

sub rename_exchange ($$) {
    goto &renameat2($_[0], $_[1], RENAME_EXCHANGE);
}

sub renameat ($$) {
    goto &renameat2($_[0], $_[1], 0);
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
