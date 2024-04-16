#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright © 2024 midrare
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the
# Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute,
# sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall
# be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from __future__ import annotations

__author__: str = 'midrare'
__license__: str = 'MIT'
__version__: str = '0.1.0'

import argparse
import configparser
import enum
import hashlib
import itertools
import json
import os
import pathlib
import platform
import re
import struct
import subprocess
import sys
import typing

try:
    import winreg
except ImportError:
    winreg = None


EXITCODE_SUCCESS: int = 0
EXITCODE_FAILED_TO_ACQUIRE_ENV: int = 254

REG_UNINSTALL32: str = (
    "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
REG_UNINSTALL64: str = (
    "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
REG_INSTALL_LOC: str = "InstallLocation"
IGNORE_VARIABLES: list[str] = [
    "PWD",
    "CMD_DURATION_MS", # nushell
    "LAST_EXIT_CODE", # nushell
    "PROMPT",
    "PROMPT_COMMAND",
    "PROMPT_COMMAND_RIGHT",
    "PROMPT_INDICATOR",
    "PROMPT_INDICATOR_VI_INSERT",
    "PROMPT_INDICATOR_VI_NORMAL",
    "PROMPT_MULTILINE_INDICATOR",
    "WT_PROFILE_ID",
    "WT_SESSION",
]


class VisualStudioAppPlatform(enum.StrEnum):
    DESKTOP = "Desktop"
    UWP = "UWP"


class Action(enum.StrEnum):
    DUMP = "dump"
    LIST = "list"
    RUN = "run"


class DevEnvError(Exception):
    pass


class ProgramNotFoundError(DevEnvError):
    pass


class EnvironmentDumpError(DevEnvError):
    pass


class Arch(enum.StrEnum):
    X86 = "x86", "x86"
    X64 = "x64", "x64"
    ARM = "ARM", "ARM"
    ARM64 = "ARM64", "ARM64"

    def __new__(cls, value: typing.Any, vs_arg: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.vs_arg = vs_arg  # pyright: ignore
        return member


class SemanticVersion:
    def __init__(self, version: str) -> None:
        m = re.match(
            r"^([0-9]+)\.([0-9]+)\.([0-9]+)" +
            r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?" +
            r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$",
            version,
        )

        if not m:
            raise ValueError(
                f'"{version}" is not a valid semantic version string.')

        self.major: int = int(m.group(1))
        self.minor: int = int(m.group(2))
        self.patch: int = int(m.group(3))
        self.prerelease: float | str = 0
        self.build: float | str = 0

        if m.group(4):
            self.prerelease = m.group(4)
            try:
                self.prerelease = float(m.group(4))
            except ValueError:
                pass

        if m.group(5):
            self.build = m.group(5)
            try:
                self.build = float(m.group(5))
            except ValueError:
                pass

    def _to_tuple(self) -> tuple[int, int, int, float, float]:
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease if not isinstance(self.prerelease, str) else 0,
            self.build if not isinstance(self.build, str) else 0,
        )

    def __cmp__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented

        self_t = self._to_tuple()
        other_t = other._to_tuple()

        if self_t < other_t:
            return -1
        elif self_t > other_t:
            return 1
        elif self_t == other_t:
            return 0
        return NotImplemented

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() == other._to_tuple()

    def __ne__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() != other._to_tuple()

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() < other._to_tuple()

    def __le__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() <= other._to_tuple()

    def __gt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() > other._to_tuple()

    def __ge__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._to_tuple() >= other._to_tuple()


class EnvironmentCache:
    def __init__(self, cache_name: str):
        self._cache_dir: str = os.path.join(self._get_cache_dir(), "devenv", cache_name)
        self._envs_dir: str = os.path.join(self._cache_dir, "env")

    @classmethod
    def _get_cache_dir(cls) -> str:
        if platform.system() == "Windows":
            return os.path.expandvars("%LOCALAPPDATA%")
        elif platform.system() == "Darwin":
            return os.path.expanduser("~/Library/Caches")
        else:
            return os.getenv("XDG_CACHE_HOME") or \
                os.path.expanduser("~/.cache")

    @classmethod
    def _read_json(cls, path: str) -> None | list | dict:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass

        return None

    def _to_cached_env_path(
        self,
        toolchain: str,
        config: str,
    ) -> str:
        return os.path.join(self._envs_dir, toolchain, f"{config}.env.json")

    def read_env(
        self,
        toolchain: str,
        config: str,
    ) -> None | dict[str, str]:
        cached_env_path = self._to_cached_env_path(toolchain, config)
        cached_env = self._read_json(cached_env_path)

        if cached_env is None:
            return None

        if not isinstance(cached_env, dict):
            return None

        return cached_env

    def write_env(self, toolchain: str, config: str, env: dict[str, str]):
        cached_env_path = self._to_cached_env_path(toolchain, config)
        cached_env_dir = os.path.dirname(cached_env_path)

        os.makedirs(cached_env_dir, exist_ok=True)

        with open(cached_env_path, "w") as f:
            json.dump(env, f, indent=2)


def get_host_arch() -> Arch:
    is_host_64bit = struct.calcsize("P") * 8 == 64

    if platform.system() == "Darwin":
        # on macOS, platform.uname().version is different from other platforms
        # https://stackoverflow.com/q/7491391
        is_arm = "ARM" in platform.uname().version
    else:
        # XXX I don't know if this even works as I have no ARM machine to test
        is_arm = "ARM" in platform.machine().upper()

    if is_arm:
        arch = Arch.ARM
        if is_host_64bit:
            arch = Arch.ARM64
    else:
        arch = Arch.X86
        if is_host_64bit:
            arch = Arch.X64

    return arch



def _is_reg_key_match(
    prog_key: int,
    prog: dict[str, bool | int | str],
    regex: bool = False,
) -> bool:
    if not winreg:
        return False

    is_match = True
    for crit_key, crit_val in prog.items():
        try:
            val, _ = winreg.QueryValueEx(prog_key, crit_key)
            val = val.strip(" \v\t'\"")
        except FileNotFoundError:
            is_match = False
            break

        if not regex:
            if isinstance(crit_val, bool) or isinstance(crit_val, int):
                try:
                    is_match = int(val) == int(crit_val)
                except ValueError:
                    is_match = False
            else:
                is_match = val == crit_val
        else:
            try:
                is_match = bool(re.match(crit_val, val))  # type: ignore
            except TypeError:
                pass

        if not is_match:
            break

    return is_match


def _read_reg_uninst_paths(
    root: int,
    uninst_path: str,
    prog: dict[str, bool | int | str],
    regex: bool = False,
) -> list[str]:
    if not winreg:
        return []

    install_locs = []
    try:
        with winreg.OpenKey(root, uninst_path) as h_uninst:
            for i in itertools.count():
                try:
                    prog_uid = winreg.EnumKey(h_uninst, i)
                except OSError:
                    # no more keys
                    break

                try:
                    with winreg.OpenKey(h_uninst, prog_uid) as h_prog:
                        # noinspection PyTypeChecker
                        if _is_reg_key_match(
                                h_prog, prog, regex):  # type: ignore
                            try:
                                loc, _ = winreg.QueryValueEx(
                                    h_prog, REG_INSTALL_LOC)
                                loc = loc.strip(" \v\t'\"")
                                install_locs.append(loc)
                                break
                            except FileNotFoundError:
                                pass
                except OSError:
                    pass
    except OSError:
        pass

    return install_locs


def read_winreg_uninstall_paths(prog: dict[str, bool | int | str],
                                regex: bool = False) -> list[str]:
    if not winreg:
        return []
    return (_read_reg_uninst_paths(winreg.HKEY_CURRENT_USER, REG_UNINSTALL32,
                                   prog, regex) +
            _read_reg_uninst_paths(winreg.HKEY_CURRENT_USER, REG_UNINSTALL64,
                                   prog, regex) +
            _read_reg_uninst_paths(winreg.HKEY_LOCAL_MACHINE, REG_UNINSTALL32,
                                   prog, regex) +
            _read_reg_uninst_paths(winreg.HKEY_LOCAL_MACHINE, REG_UNINSTALL64,
                                   prog, regex))


def read_winreg_uninstall_path(prog: dict[str, bool | int | str],
                               regex: bool = False) -> None | str:
    locs = read_winreg_uninstall_paths(prog, regex)
    return locs[0] if locs else None


def _argparse_caseins_choice_type(
        choices: list[str]) -> typing.Callable[[str], str]:
    lowercase_to_normalcase = {s.lower(): s for s in choices}

    def check(arg: str) -> str:
        arg_lower = arg.lower()
        if arg_lower in lowercase_to_normalcase:
            return lowercase_to_normalcase[arg_lower]
        raise argparse.ArgumentTypeError(f'Unrecognized choice "{arg}".')

    return check


def _argparse_path_type(
    exists: bool | None,
    type_: str | None,
    alt: str | typing.List[str] | None = None,
) -> typing.Callable[[str], str]:
    if isinstance(alt, str):
        alt = [alt]
    if not alt:
        alt = []

    def check(arg: str) -> str:
        if arg in alt:
            return arg

        if exists is True:
            if not os.path.exists(arg):
                raise argparse.ArgumentTypeError(f'"{arg}" does not exist.')
            elif type_ == "file" and not os.path.isfile(arg):
                raise argparse.ArgumentTypeError(f'"{arg}" is not a file.')
            elif type_ == "dir" and not os.path.isdir(arg):
                raise argparse.ArgumentTypeError(f'"{arg}" is not a directory.')
        elif exists is False:
            if os.path.exists(arg):
                raise argparse.ArgumentTypeError(f'"{arg}" already exists.')
        else:
            if (type_ == "file" and os.path.exists(arg) and
                    not os.path.isfile(arg)):
                raise argparse.ArgumentTypeError(
                    f'"{arg}" exists and is not a file.')
            elif (type_ == "dir" and os.path.exists(arg) and
                  not os.path.isdir(arg)):
                raise argparse.ArgumentTypeError(
                    f'"{arg}" exists and is not a directory.')

        return arg

    return check


class VisualStudio:
    TIMEOUT_SECS: int = 30

    def __init__(self, root: str | pathlib.Path):
        if isinstance(root, str):
            root = pathlib.Path(root)

        self._root: pathlib.Path = root
        try:
            ini_path = self._find_vsdev_ini()
            cfg = configparser.ConfigParser()
            cfg.read(str(ini_path))
        except (FileNotFoundError, KeyError, ValueError):
            raise ProgramNotFoundError(
                '"{root}" is not a Visual Studio program directory.')

        self._uid: str = cfg["Info"]["InstallationID"]
        self._name: str = cfg["Info"]["InstallationName"]
        self._version: str = cfg["Info"]["SemanticVersion"]
        self._arch: str = cfg["Info"]["ProductArch"]

    @property
    def root(self) -> str:
        return str(self._root)

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def arch(self) -> str:
        return self._arch

    def _find_vsdev_cmd(self) -> None | pathlib.Path:
        rel = next(self._root.glob("Common*/Tools/VsDevCmd.bat"), None)
        return self._root.joinpath(rel) if rel else None

    def _find_vsdev_ini(self) -> None | pathlib.Path:
        rel = next(self._root.glob("Common*/IDE/devenv.isolation.ini"), None)
        return self._root.joinpath(rel) if rel else None

    def dump_environment_vars(
        self,
        args: list[str],
    ) -> dict[str, str]:
        env = {}

        bat = self._find_vsdev_cmd()
        if not bat:
            raise EnvironmentDumpError("Failed to find env startup script.")

        # see $VISUALSTUDIO/Common7/Tools/vsdevcmd/core/parse_cmd.bat for
        # valid command-line arguments
        try:
            output = subprocess.run(
                [bat, "-no_logo"] + args + ["&", "set"],
                capture_output=True,
                text=True,
                shell=True,
                timeout=self.TIMEOUT_SECS,
            ).stdout
        except subprocess.TimeoutExpired:
            raise EnvironmentDumpError("Environment dump timed out.")

        for line in output.splitlines():
            if not line.startswith("["):  # errors come in form of "[ERR]: msg"
                t = line.split("=", maxsplit=1)
                if t and len(t) >= 2:
                    env[t[0]] = t[1]

        if not env.get("VSCMD_VER"):
            raise EnvironmentDumpError(
                "Environment dump failed to capture Visual Studio variables.")

        for name in IGNORE_VARIABLES:
            env.pop(name, None)

        return env


class VisualStudioInstaller:
    TIMEOUT_SECS: int = 30

    def __init__(self, root: str | pathlib.Path):
        if isinstance(root, str):
            root = pathlib.Path(root)

        if not root.is_dir():
            raise FileNotFoundError(f'"{root}" is not a directory.')

        self._root: pathlib.Path = root

    def _find_vswhere(self) -> None | pathlib.Path:
        vswhere = self._root.joinpath("vswhere.exe")
        if not vswhere.is_file():
            vswhere = self._root.joinpath("vswhere")
        if not vswhere.is_file():
            vswhere = None
        return vswhere

    def _run_vswhere(self, vswhere: pathlib.Path) -> list[dict]:
        if not vswhere.is_file():
            raise FileNotFoundError('"{vswhere}" is not a file.')

        vsdevs = []
        output = ""

        try:
            output = subprocess.run(
                [vswhere, "-utf8", "-format", "json"],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECS,
                shell=True,
            ).stdout
        except subprocess.TimeoutExpired:
            pass

        vsdevs.extend(json.loads(output))

        return vsdevs

    def get_visual_studio_roots(self) -> list[str]:
        vsdevs = []

        if vswhere := self._find_vswhere():
            vsdevs.extend(self._run_vswhere(vswhere))

        # ...\Microsoft Visual Studio\2022\Professional\Common7\IDE\devenv.exe
        paths = []
        for vsdev in vsdevs:
            if (prod_path := vsdev.get("productPath")) and (m := re.match(
                    r"^(.+)[\\/]Common[^\\/]*[\\/]IDE[\\/][^\\/]+$",
                    prod_path,
                    re.IGNORECASE,
            )):
                paths.append(m.group(1))

        return paths


def read_visual_studios_from_winreg() -> list[VisualStudio]:
    locs = read_winreg_uninstall_paths(
        {"DisplayName": r"^Visual Studio\s+(?:[a-zA-Z0-9]+\s+)?[0-9]{4}$"},
        regex=True,
    )
    return [VisualStudio(p) for p in locs]


def read_visual_studios_from_installer() -> list[VisualStudio]:
    vstudios = []
    if loc := read_winreg_uninstall_path(
            {"DisplayName": "Microsoft Visual Studio Installer"}):
        vsi = VisualStudioInstaller(loc)
        vstudios.extend(VisualStudio(p) for p in vsi.get_visual_studio_roots())
    return vstudios


def find_visual_studios() -> list[VisualStudio]:
    from_vsinstaller = read_visual_studios_from_installer()
    from_winreg = read_visual_studios_from_winreg()

    d = {vs.uid: vs for vs in from_winreg}
    d.update({vs.uid: vs for vs in from_vsinstaller})

    return list(d.values())


def find_visual_studio() -> None | VisualStudio:
    vstudios = find_visual_studios()
    vstudios.sort(key=lambda o: SemanticVersion(o.version), reverse=True)
    return vstudios[0] if vstudios else None


def find_visual_studio_by_uid(uid: str) -> None | VisualStudio:
    for candidate in find_visual_studios():
        if candidate.uid == uid:
            return candidate
    return None


def find_visual_studio_by_path(path: str | pathlib.Path) -> None | VisualStudio:
    try:
        return VisualStudio(path)
    except ProgramNotFoundError:
        pass
    return None


def _clean_arg(name: str,
               value: None | bool | int | float | str = None,
               ) -> tuple[str, None | bool | int | float | str]:
    name = name.lstrip(" \v\t/-").strip()

    if m := re.match(r"^(?:no|disable)[_-]([a-zA-Z0-9_-]+)$", name):
        name = m.group(1).replace("-", "_")
        if value is None:
            value = False
        else:
            value = not value
    if m := re.match(r"^(?:enable[_-])?([a-zA-Z0-9_-]+)$", name):
        name = m.group(1).replace("-", "_")
        if value is None:
            value = True
        else:
            value = not value
    elif m := re.match(r"^([a-zA-Z0-9_-]+)=(.+)$", name):
        name = m.group(1).replace("-", "_")
        value = m.group(2)

        if m := re.match(r'"(.+)"', value):
            value = m.group(1)
        elif m := re.match(r"\'(.+)\'", value):
            value = m.group(1)

        if value.lower() in ["true", "false"]:
            value = bool(value)
        else:
            try:
                value = float(value)
            except ValueError:
                try:
                    value = int(value)
                except ValueError:
                    pass

    return name, value


def _calc_checksum(o: typing.Any) -> str:
    checksum = hashlib.md5()

    if isinstance(o, (tuple, list)):
        for e in sorted(o):
            checksum.update(str(e).encode('utf-8'))
    elif isinstance(o, dict):
        checksum.update(json.dumps(sorted(list(o.items()))).encode('utf-8'))
    else:
        checksum.update(str(o).encode('utf-8'))

    return checksum.hexdigest()


def get_visual_studio_env_vars(
    vstudio: VisualStudio,
    vstudio_args: None | list[str] = None,
    read_cache: bool = True,
    write_cache: bool = False,
) -> dict[str, str]:
    vstudio_args = vstudio_args or []
    env = None
    env_cache = EnvironmentCache("visualstudio")

    args_hash = _calc_checksum([_clean_arg(e) for e in vstudio_args])
    env_hash = _calc_checksum(
        {k: v for k, v in os.environ.items() if k not in IGNORE_VARIABLES})
    config = f"{vstudio.version}-{args_hash}-{env_hash}"

    if not env and read_cache:
        env = env_cache.read_env(vstudio.uid, config)

    if not env:
        env = vstudio.dump_environment_vars(vstudio_args)
        if write_cache:
            env_cache.write_env(vstudio.uid, config, env)

    return env


def _add_cache_option(parser: argparse.ArgumentParser):
    # noinspection PyTypeChecker
    parser.add_argument(
        "--read-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="""read environment variables from cache if
        present (default: %(default)s)""")

    # noinspection PyTypeChecker
    parser.add_argument(
        "--write-cache",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="""write environment variables to cache if
        absent (default: %(default)s). Be careful that your
        environment variables do not contain sensitive info
        as these will also be captured in the cache""")


def _add_run_action(actions: argparse._SubParsersAction) -> argparse.ArgumentParser:
    runner = actions.add_parser(
        Action.RUN,
        help="run command under developer environment",
        epilog=f"""
        Will exit {EXITCODE_FAILED_TO_ACQUIRE_ENV} on failure to
        acquire environment.

        If the environment is sucessfully acquired and the command is run,
        the exit code will be the exit code returned by the command.
        """)
    runner.add_argument(
        "--shell",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="use shell during execution (default: %(default)s)")

    runner.add_argument(
        "--cwd",
        metavar="DIR",
        type=_argparse_path_type(exists=True, type_="dir"),
        help="start program in the specified dir. Must exist",
    )
    runner.add_argument("cmd", help="command to run")
    runner.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="remaining arguments will be passed as arguments to the command",
    )

    _add_cache_option(runner)

    return runner


def _add_dump_action(actions: argparse._SubParsersAction) -> argparse.ArgumentParser:
    dumper = actions.add_parser(
        Action.DUMP, help="dump environment variables")

    # noinspection PyTypeChecker
    dumper.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="output in json format (default: %(default)s)",
    )

    _add_cache_option(dumper)

    return dumper


def _add_vs_options(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-i",
        "--instance",
        metavar="INST",
        help="""
        which Visual Studio installation to use.
        Can be either path to Visual Studio (e.g.
        C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional)
        or UID (e.g. 49b3d031). If not specified, will default to the
        newest version found
        """,
    )
    parser.add_argument(
        "--app-platform",
        metavar="PLAT",
        type=_argparse_caseins_choice_type(list(VisualStudioAppPlatform)),
        choices=list(VisualStudioAppPlatform),
        help="app platform target type (default: autodetect)",
    )
    parser.add_argument(
        "--winsdk",
        metavar="VER",
        type=str,
        help="version of Windows SDK to use (default: autodetect)",
    )
    parser.add_argument(
        "--host-arch",
        metavar="ARCH",
        type=_argparse_caseins_choice_type(list(Arch)),
        choices=list(Arch),
        help="host arch (default: autodetect)",
    )
    parser.add_argument(
        "--target-arch",
        metavar="ARCH",
        type=_argparse_caseins_choice_type(list(Arch)),
        choices=list(Arch),
        help="target arch (default: autodetect)",
    )


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run/dump/list Visual Studio developer environments")
    actions = parser.add_subparsers(
        dest="action",
        help="action to perform",
        required=True)

    actions.add_parser(Action.LIST, help="show detected installations")

    runner = _add_run_action(actions)
    dumper = _add_dump_action(actions)

    _add_vs_options(runner)
    _add_vs_options(dumper)

    return parser.parse_args(args)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    if args.action == Action.LIST:
        vstudios = find_visual_studios()
        for vs in vstudios:
            print(f"{vs.uid} {vs.name} {vs.arch} {vs.root}")
        return EXITCODE_SUCCESS
    elif args.action in [Action.RUN, Action.DUMP]:
        if args.instance and re.match(r"^[a-zA-Z0-9]{8}$",
                                           args.instance):
            vstudio = find_visual_studio_by_uid(args.instance)
        elif args.instance:
            vstudio = find_visual_studio_by_path(args.instance)
        else:
            vstudio = find_visual_studio()
        if not vstudio:
            raise ProgramNotFoundError("Failed to find Visual Studio.")

        vs_args = []

        if args.app_platform:
            vs_args.append(f"-app_platform={args.app_platform}")
        if args.winsdk:
            vs_args.append(f"-winsdk={args.winsdk}")

        host_arch = args.host_arch or get_host_arch()
        if host_arch:
            vs_args.append(f"-host_arch={host_arch}")

        target_arch = args.target_arch or get_host_arch()
        if target_arch:
            vs_args.append(f"-arch={target_arch}")

        env_vars = get_visual_studio_env_vars(
            vstudio,
            vs_args,
            args.read_cache,
            args.write_cache)

        if args.action == Action.RUN:
            if not env_vars:
                print("Failed to acquire vsdev environment.", file=sys.stderr)
                return EXITCODE_FAILED_TO_ACQUIRE_ENV

            return subprocess.run(
                [args.cmd] + args.args,
                shell=args.shell,
                cwd=args.cwd,
                env=env_vars,
            ).returncode
        elif args.action == Action.DUMP:
            if env_vars:
                if args.json:
                    print(json.dumps(env_vars, indent=2))
                else:
                    for k, v in env_vars.items():
                        print(f"{k}={v}")
            return EXITCODE_SUCCESS

    raise Exception(f"Unrecognized action {args.action}.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

