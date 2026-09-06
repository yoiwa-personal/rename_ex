#!/usr/bin/perl

use 5.024;

use strict;
use FindBin;
use lib "$FindBin::Bin/..";
use File::RenameEx;

sub do_renameat2 ($$$);

our ($dirhandle, $tmpdir, $path);


sub write_file ($$) {
    open (my $fh, ">", $_[0]) or die;
    print $fh $_[1];
    close $fh or die;
}

sub read_file ($) {
    local $/;
    open (my $fh, "<", $_[0]) or return undef;
    my $s = <$fh>;
    close $fh or die;
    print ("    reading $_[0] => $s\n");
    return $s;
}
      
sub prepare () {
    $tmpdir = File::Temp->newdir(CLEANUP => 1);
    $path = $tmpdir->dirname;

    opendir($dirhandle, $path) or die;
    
    mkdir("$path/1d");
    mkdir("$path/2d");
    mkdir("$path/de");
    write_file("$path/1", "1");
    write_file("$path/2", "2");
    link("$path/1", "$path/1h1");
    link("$path/1", "$path/1h2");
    write_file("$path/1d/1f", "1f");
    write_file("$path/2d/2f", "2f");
    
    return ($tmpdir, $path);
}

sub file_test () {
    do_renameat2([$dirhandle, "1"], [$dirhandle, "3"], 0) or warn "1 $!";
    (-f "$path/1") and warn "1-1";
    read_file("$path/3") eq "1" or warn "1-3";
    do_renameat2([$dirhandle, "3"], [$dirhandle, "1"], 0) or warn "2 $!";
    (-f "$path/3") and warn "2-3";
    read_file("$path/1") eq "1" or warn "2-1";
}

sub dir_test () {
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "3d"], 0) or warn "3 $!";
    -d "$path/1d" and warn "3-1d";
    read_file("$path/3d/1f") eq "1f" or warn "3-3d";
    do_renameat2([$dirhandle, "3d"], [$dirhandle, "1d"], 0) or warn "4 $!";
    -d "$path/3d" and warn "4-3d";
    read_file("$path/1d/1f") eq "1f" or warn "4-1d";
}

sub file_file_test () {
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2"], RENAME_EXCHANGE) or warn "5 $!";
    read_file("$path/1") eq "2" or warn "5-1";
    read_file("$path/2") eq "1" or warn "5-2";
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2"], RENAME_EXCHANGE) or warn "6 $!";
    read_file("$path/1") eq "1" or warn "6-1";
    read_file("$path/2") eq "2" or warn "6-2";
}

sub file_dir_test () {
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2d"], RENAME_EXCHANGE) or warn "7 $!";
    read_file("$path/1/2f") eq "2f" or warn "7-1";
    read_file("$path/2d") eq "1" or warn "7-2";
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2d"], RENAME_EXCHANGE) or warn "8 $!";
    read_file("$path/1") eq "1" or warn "8-1";
    read_file("$path/2d/2f") eq "2f" or warn "8-2";
}

sub dir_file_test () {
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2"], RENAME_EXCHANGE) or warn "7 $!";
    read_file("$path/1d") eq "2" or warn "7-1";
    read_file("$path/2/1f") eq "1f" or warn "7-2";
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2"], RENAME_EXCHANGE) or warn "8 $!";
    read_file("$path/1") eq "1" or warn "8-1";
    read_file("$path/2d/2f") eq "2f" or warn "8-2";
}

sub dir_dir_test () {
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2d"], RENAME_EXCHANGE) or warn "7 $!";
    read_file("$path/1d/2f") eq "2f" or warn "7-1";
    read_file("$path/2d/1f") eq "1f" or warn "7-2";
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2d"], RENAME_EXCHANGE) or warn "8 $!";
    read_file("$path/1d/1f") eq "1f" or warn "8-1";
    read_file("$path/2d/2f") eq "2f" or warn "8-2";
}

sub same_same_test () {
    do_renameat2([$dirhandle, "1"], [$dirhandle, "1"], RENAME_EXCHANGE) or warn "9-f $!";
    read_file("$path/1") eq "1" or warn "9-1";
    do_renameat2([$dirhandle, "2d"], [$dirhandle, "2d"], RENAME_EXCHANGE) or warn "10 $!";
    read_file("$path/2d/2f") eq "2f" or warn "10-2";
}

sub file_noclobber_test () {
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2"], RENAME_NOREPLACE) and warn "11-ff";
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2"], RENAME_NOREPLACE) and warn "11-df";
    do_renameat2([$dirhandle, "1"], [$dirhandle, "2d"], RENAME_NOREPLACE) and warn "11-fd";
    do_renameat2([$dirhandle, "1d"], [$dirhandle, "2d"], RENAME_NOREPLACE) and warn "11-dd";
}

sub link_test () {
    do_renameat2([$dirhandle, "1h1"], [$dirhandle, "1h2"], RENAME_EXCHANGE) or warn "12 $!";
    read_file("$path/1h1") eq "1" or warn "12-1";
    read_file("$path/1h2") eq "1" or warn "12-2";
    do_renameat2([$dirhandle, "1h1"], [$dirhandle, "1h2"], 0) or warn "13 $!";
    read_file("$path/1h1") eq "1" or warn "13-1";
    read_file("$path/1h2") eq "1" or warn "13-2";
    # rename on the same file keeps original!
    do_renameat2([$dirhandle, "1h2"], [$dirhandle, "1"], RENAME_NOREPLACE) and warn "14 $!";
    # rename no replace raises error!
    do_renameat2([$dirhandle, "1"], [$dirhandle, "1"], RENAME_NOREPLACE) and warn "15 $!";
    read_file("$path/1") eq "1" or warn "14-1";
    read_file("$path/1h2") eq "1" or warn "14-2";
}

sub rename_corner_test () {
    mkdir "$path/9d1";
    mkdir "$path/9d2";
    write_file("$path/9f1", "9");
    write_file("$path/9f2", "9");

    # NOREPLACE works, of course
    do_renameat2([$dirhandle, "9d2"], [$dirhandle, "9d1"], RENAME_NOREPLACE) and warn "16-0 d->d $!";

    # a directory does not overwrite a file
    do_renameat2([$dirhandle, "9d1"], [$dirhandle, "9f1"], 0) and warn "16-1 d->f $!";
    # a directory DOES overwrite an empty directory!
    do_renameat2([$dirhandle, "9d2"], [$dirhandle, "9d1"], 0) or warn "16-2 d->d $!";
    (-d "$path/9d2") and warn "16-2 exist";
    (-d "$path/9d1") or warn "16-2 notexist";

    # a directory does not overwrite non-empty director!
    do_renameat2([$dirhandle, "9d1"], [$dirhandle, "2d"], 0) and warn "16-2b d->d $!";

    # a file does not overwrite an empty directory
    do_renameat2([$dirhandle, "9f2"], [$dirhandle, "9d1"], 0) and warn "16-3 d->d $!";
    read_file("$path/9f2") eq "9" or warn "16-3 read";

    do_renameat2([$dirhandle, "1d"], [$dirhandle, "9d1"], 0) or warn "16-4 d->d $!";
    read_file("$path/9d1/1f") eq "1f" or warn "16-4 read";

    do_renameat2([$dirhandle, "9d1"], [$dirhandle, "1d"], 0) or warn "16-4 d->d $!";
    read_file("$path/1d/1f") eq "1f" or warn "16-4 read";

    unlink("$path/9f1") or warn "16-5-1 $!";
    unlink("$path/9f2") or warn "16-5-2 $!";
}

sub run_test () {
    my ($dh, $fh) = prepare;
    say ">>>$dirhandle";
    no strict "refs";
    for my $t (qw(file_test dir_test
	       file_file_test dir_dir_test file_dir_test dir_file_test
	       same_same_test file_noclobber_test link_test
	       rename_corner_test
	     )) {
	print "running $t test \n";
	&{$t}();
    }
    system "ls -lR $path";
    chdir "..";
}

if ($0 eq __FILE__) {
    $_ = $ARGV[0];
    if ($_ eq 'linux') {
	*do_renameat2 = \&renameat2;
	run_test();
    } elsif ($_ eq 'generic') {
	*do_renameat2 = \&File::RenameEx::_renameat2_generic;
	run_test();
    } else {
	die "unknown test";
    }
}
