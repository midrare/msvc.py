import os
import pathlib
import re
import subprocess

from .vstudioenv import EnvironmentDumpError
from .vstudioenv import ProgramNotFoundError
from .vstudioenv import VisualStudioError
from .vstudioenv import find_visual_studio_by_path
from .vstudioenv import find_visual_studios
from .vstudioenv import find_visual_studio_by_uid
from .vstudioenv import get_visual_studio_env_vars


def dump(
    vstudio: str | pathlib.Path,
    vstudio_args: None | list[str] = None,
    use_cache: bool = True,
) -> dict[str, str]:
    vstudio_instance = None
    if isinstance(vstudio, str) and re.match(r"[a-zA-Z0-9]{8}", vstudio):
        vstudio_instance = find_visual_studio_by_uid(vstudio)
    else:
        vstudio_instance = find_visual_studio_by_path(vstudio)

    if not vstudio_instance:
        raise ProgramNotFoundError(f'Visual Studio "{vstudio}" not found.')

    return get_visual_studio_env_vars(
        vstudio_instance,
        vstudio_args,
        use_cache,
    )


def run(
    vstudio: str | pathlib.Path,
    cmd: list[str],
    shell: bool = False,
    cwd: None | str | pathlib.Path = None,
) -> int:
    if not vstudio:
        raise ValueError("Visual Studio not specified")
    if not cmd:
        raise ValueError("Command not provided.")

    env = dump(vstudio)

    # have to update os.environ b/c passing the "env" param to subprocess.run()
    # doesn't include the new $PATH when looking for the command executable
    apply_env = set(env.items()) - set(os.environ.items())
    unapply_env = set(os.environ.items()) - set(env.items())

    os.environ.update(apply_env)
    exit_code = subprocess.run(cmd, shell=shell, cwd=cwd).returncode
    os.environ.update(unapply_env)

    return exit_code


def list() -> list[tuple[str, str]]:
    return [(vs.uid, vs.root) for vs in find_visual_studios()]


__all__ = [
    "EnvironmentDumpError",
    "ProgramNotFoundError",
    "VisualStudioError",
    "run",
    "dump",
    "list",
]
