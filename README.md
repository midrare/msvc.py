# msvc.py
Run one-shot commands under Visual Studio developer prompt. Use any shell with Visual Studio developer prompt. Dump developer prompt environment variables.

For fast startup, use the `--read-cache` and `--write-cache` options. **The cache will contain all environment variables in plaintext, so make sure you don't have any sensitive data in your environment variables when using `--write-cache`.** The cache will be automatically regenerated when the underlying Visual Studio installation is detected to be updated.

## Examples
Start a Visual Studio developer prompt with nushell:
`nu.exe -e 'python "C:\\bin\\msvc.py" dump --read-cache --write-cache --json | from json | load-env'`

