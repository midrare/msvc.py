# msvc.py
Run one-shot commands under Visual Studio developer prompt. Use any shell with Visual Studio developer prompt. Dump developer prompt environment variables.

For fast startup, use the `--read-cache` and `--write-cache` options. **The cache will contain all environment variables in plaintext, so make sure you don't have any sensitive data in your environment variables when using `--write-cache`.** The cache will be automatically regenerated when the underlying Visual Studio installation is detected to be updated.

## Examples
```bash
# one-shot under VS dev prompt
> ./msvc.py run cl /nologo hello.c
Microsoft (R) C/C++ Optimizing Compiler Version 19.37.32825 for x64
Copyright (C) Microsoft Corporation.  All rights reserved.

hello.c
Microsoft (R) Incremental Linker Version 14.37.32825.0
Copyright (C) Microsoft Corporation.  All rights reserved.

/out:hello.exe
hello.obj
```

```bash
# list installed visual studio instances
> ./msvc.py list
953270db VisualStudio/17.7.6+34221.43 x64 C:\Program Files\Microsoft Visual Studio\2022\Professional
```

```bash
# dump visual studio environment variables (truncated for brevity)
> ./msvc.py dump
...
VCIDEInstallDir=C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\VC\
VCINSTALLDIR=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\
VCPKG_DEFAULT_TRIPLET=x64-windows
VCToolsInstallDir=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.37.32822\
VCToolsRedistDir=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Redist\MSVC\14.36.32532\
VCToolsVersion=14.37.32822
VisualStudioVersion=17.0
VS170COMNTOOLS=C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\
VSCMD_ARG_app_plat=Desktop
VSCMD_ARG_HOST_ARCH=x64
VSCMD_ARG_no_logo=1
VSCMD_ARG_TGT_ARCH=x64
VSCMD_VER=17.7.6
...
```

```bash
# start a visual studio developer prompt with nushell
> nu -e 'python "./msvc.py" dump --read-cache --write-cache --json | from json | load-env'
```

