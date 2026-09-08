#!/usr/bin/ruby

require_relative '../rename_ex'

$is_win32 = Fiddle.respond_to?(:win32_last_error)

include RenameEx
extend RenameEx
$do_renameat2 = self.method(:renameat2)

def write_file(env, fname, content)
  open(env.prefix + fname, "w") { |f|
    f.print(content)
  }
end

def read_file(env, fname, check: nil)
  s = nil
  open(env.prefix + fname, "r") { |f|
    s = f.read()
  }
  print("    reading #{env.prefix + fname} => #{s.inspect}\n")
  if check
    return s == check
  else
    return s
  end
end

def prepare(tmpdir, use_fd: false)
  if use_fd
    fd = Dir.open(tmpdir).fileno
    prefix = tmpdir + "/"
  else
    fd = nil
    prefix = ""
    Dir.chdir(tmpdir)
  end

  env = Struct.new(:prefix, :fd).new
  env.prefix = prefix
  env.fd = fd
        
  Dir.mkdir(prefix + "1d")
  Dir.mkdir(prefix + "2d")
  write_file(env, "1", "1")
  write_file(env, "2", "2")
  File.link(prefix + "1", prefix + "1h1")
  File.link(prefix + "1", prefix + "1h2")
  write_file(env, "1d/1f", "1f")
  write_file(env, "2d/2f", "2f")

  return env
end

def try_renameat2(env, src, dest, flags, msg: "", success: true)
  begin
    $do_renameat2.call(src, dest,
                        from_dir_fd: env.fd, to_dir_fd: env.fd, flags: flags)
  rescue SystemCallError => e
    print("renameat2(#{src.inspect}, #{dest.inspect}, flags:#{flags}) => #{e}\n")
    if success
      warn("test $#{msg} failed: #{e}")
    end
    return
  end
  print("renameat2(#{src.inspect}, #{dest.inspect}, flags:#{flags}) => OK\n")
  if success
  else
    warn("test $#{msg} failed: no error (should fail)")
  end
end

def check_file(env, f, check, msg: "")
  begin
    r = read_file(env, f)
    if r != check
      warn("test $#{msg} failed: content mismatch: #{r.inspect} <> #{check.inspect}")
    end
  rescue RuntimeError => e
    warn(f"test $#{msg} failed: #{e}")
  end
end

def check_filetest(env, fun, a, msg: "", success: true)
  begin
    r = fun.call(env.prefix + a)
    if r != success
      warn("test $#{msg} failed: filetest mismatch: #{r.inspect} <> #{success.inspect}")
    end
  rescue RuntimeError => e
    warn(f"test $#{msg} failed: #{e}")
  end
end
    
def try_ok(env, f, a, msg:"", success:true)
  begin
    f.call(env.prefix + a)
  rescue RuntimeError => e
    if success
      warn("test $#{msg} failed #{e}")
    end
    return
  end
  if not success
    warn(f"test $#{msg} failed: no error (should fail)")
  end
end

def depends_on_arch(a, m)
  m.each { |k, v| return v if RUBY_PLATFORM.include?(k) }
  return a
end

def file_test(env)
    try_renameat2(env, "1", "3", 0, msg:"1")
    check_filetest(env, FileTest.method(:exist?), "1", msg:"1-1", success:false)
    check_file(env, "3", "1", msg:"1-3")
    try_renameat2(env, "3", "1", 0, msg:"2")
    check_filetest(env, FileTest.method(:exist?), "3", msg:"2-3", success:false)
    check_file(env, "1", "1", msg:"2-1")
end

def dir_test(env)
    try_renameat2(env, "1d", "3d", 0, msg:"3")
    check_filetest(env, FileTest.method(:exist?), "1d", msg:"3-1d", success:false)
    check_file(env, "3d/1f", "1f", msg:"3-3d")
    try_renameat2(env, "3d", "1d", 0, msg:"4")
    check_filetest(env, FileTest.method(:exist?), "3d", msg:"4-3d", success:false)
    check_file(env, "1d/1f", "1f", msg:"4-1d")
end

def file_file_test(env)
    try_renameat2(env, "1", "2", RENAME_EXCHANGE, msg:"5")
    check_file(env, "1", "2", msg:"5-1")
    check_file(env, "2", "1", msg:"5-2")
    try_renameat2(env, "1", "2", RENAME_EXCHANGE, msg:"6")
    check_file(env, "1", "1", msg:"6-1")
    check_file(env, "2", "2", msg:"6-2")
end

def file_dir_test(env)
    try_renameat2(env, "1", "2d", RENAME_EXCHANGE, msg:"7")
    check_file(env, "1/2f", "2f", msg:"7-1")
    check_file(env, "2d", "1", msg:"7-2")
    try_renameat2(env, "1", "2d", RENAME_EXCHANGE, msg:"8")
    check_file(env, "1", "1", msg:"8-1")
    check_file(env, "2d/2f", "2f", msg:"8-2")
end

def dir_file_test(env)
    try_renameat2(env, "1d", "2", RENAME_EXCHANGE, msg:"7")
    check_file(env, "1d", "2", msg:"7-1")
    check_file(env, "2/1f", "1f", msg:"7-2")
    try_renameat2(env, "1d", "2", RENAME_EXCHANGE, msg:"8")
    check_file(env, "1", "1", msg:"8-1")
    check_file(env, "2d/2f", "2f", msg:"8-2")
end

def dir_dir_test(env)
    try_renameat2(env, "1d", "2d", RENAME_EXCHANGE, msg:"7")
    check_file(env, "1d/2f", "2f", msg:"7-1")
    check_file(env, "2d/1f", "1f", msg:"7-2")
    try_renameat2(env, "1d", "2d", RENAME_EXCHANGE, msg:"8")
    check_file(env, "1d/1f", "1f", msg:"8-1")
    check_file(env, "2d/2f", "2f", msg:"8-2")
end

def same_same_test (env)
    try_renameat2(env, "1", "1", RENAME_EXCHANGE, msg:"9-f")
    check_file(env, "1", "1", msg:"9-1")
    try_renameat2(env, "2d", "2d", RENAME_EXCHANGE, msg:"10")
    check_file(env, "2d/2f", "2f", msg:"10-2")
end

def file_noclobber_test (env)
    try_renameat2(env, "1", "2", RENAME_NOREPLACE, success:false, msg:"11-ff")
    try_renameat2(env, "1d", "2", RENAME_NOREPLACE, success:false, msg:"11-df")
    try_renameat2(env, "1", "2d", RENAME_NOREPLACE, success:false, msg:"11-fd")
    try_renameat2(env, "1d", "2d", RENAME_NOREPLACE, success:false, msg:"11-dd")
end

def link_test (env)
    try_renameat2(env, "1h1", "1h2", RENAME_EXCHANGE, msg:"12")
    check_file(env, "1h1", "1", msg:"12-1")
    check_file(env, "1h2", "1", msg:"12-2")
    try_renameat2(env, "1h1", "1h2", 0, msg:"13")
    check_file(env, "1h1", "1", msg:"13-1")
    check_file(env, "1h2", "1", msg:"13-2")
    # rename on the same file keeps original!

    try_renameat2(env, "1h2", "1", RENAME_NOREPLACE, success:false, msg:"14")
    # rename no replace raises error!

    try_renameat2(env, "1", "1", RENAME_NOREPLACE,
                  success: depends_on_arch(false, {"darwin" => true}), msg:"15")
    check_file(env, "1", "1", msg:"14-1")
    check_file(env, "1h2", "1", msg:"14-2")
end

def rename_corner_test (env)
    Dir.mkdir(env.prefix + "9d1")
    Dir.mkdir(env.prefix + "9d2")
    Dir.mkdir(env.prefix + "9d3")
    write_file(env, "9f1", "9")
    write_file(env, "9f2", "9")

    # NOREPLACE works, of course
    try_renameat2(env, "9d2", "9d1", RENAME_NOREPLACE, success:false, msg:"16-0 d->d")

    # a directory does not overwrite a file (on Win32, does)
    try_renameat2(env, "9d3", "9f3", 0, success:($is_win32), msg:"16-1 d->f")

    # a directory DOES overwrite an empty directory! (on Win32, doesn't)
    if not $is_win32
      try_renameat2(env, "9d2", "9d1", 0, msg:"16-2 d->d")
      check_filetest(env, FileTest.method(:exist?), "9d2", success:false, msg:"16-2 exist")
      check_filetest(env, FileTest.method(:exist?), "9d1", msg:"16-2 notexist")
    end

    # a directory does not overwrite non-empty directory
    try_renameat2(env, "9d1", "2d", 0, success:false, msg:"16-2b d->d")

    # a file does not overwrite an empty directory
    try_renameat2(env, "9f2", "9d1", 0, success:false, msg:"16-3 d->d")
    if not $is_win32
      check_file(env, "9f2", "9", msg:"16-3 read")
    end

    if not $is_win32
      try_renameat2(env, "1d", "9d1", 0, msg:"16-4 d->d")
      check_file(env, "9d1/1f", "1f", msg:"16-4 read")

      try_renameat2(env, "9d1", "1d", 0, msg:"16-4 d->d")
      check_file(env, "1d/1f", "1f", msg:"16-4 read")
    end
    try_ok(env, File.method(:delete), "9f1", msg:"16-5-1")
    try_ok(env, File.method(:delete), "9f2", msg:"16-5-2")
end

def run_test (use_fd)
  Dir.mktmpdir { |d|
    begin
      env = prepare(d, use_fd: use_fd)
      file_test(env)
      dir_test(env)
      file_file_test(env)
      dir_dir_test(env)
      file_dir_test(env)
      dir_file_test(env)
      same_same_test(env)
      file_noclobber_test(env)
      link_test(env)
      rename_corner_test(env)
    ensure
      Dir.chdir("/")
    end
  }
end

for opt in ARGV
  print "\n==== Running Ruby test #{opt}\n"
  if opt == 'native'
    run_test(false)
  elsif opt == 'native-fd'
    run_test(true)
  elsif opt == 'generic'
    RenameEx.module_eval("module_function :_renameat2_generic")
    $do_renameat2 = self.method(:_renameat2_generic)
    run_test(false)
  else
    p "unknown test"
  end
end
