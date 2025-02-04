(do {
    let filename = "msvc.py"
    let relfile = [($env.CURRENT_FILE | path dirname), $filename] | path join
    let sysfile = which $filename | get path | get -i 0
    let file = (if ($relfile | path exists) { $relfile } else { $sysfile })

    if ($file == null or not ($file | path exists)) {
        error make {
            msg: $"($filename) not found in current directory or in $PATH",
        }
    } 
    
    mut env_ = do { ^python $file dump --read-cache --write-cache --json } | from json
    if ($env_ != null and 'Path' in $env_) {
        $env_ = $env_ | update Path { |it| $it.Path | split row (char esep) }
    }
    if ($env_ != null and 'PATH' in $env_) {
        $env_ = $env_ | update PATH { |it| $it.PATH | split row (char esep) }
    }

    $env_ | default {}
}) | load-env
