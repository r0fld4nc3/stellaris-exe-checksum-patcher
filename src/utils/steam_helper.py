# built-ins
import os
from pathlib import Path
from utils import registry_helper
from typing import Union

from conf_globals import settings, OS, LOG_LEVEL
from logger import create_logger
import vdf

log = create_logger("Steam Helper", LOG_LEVEL)

# KEY_LOCAL_MACHINE
GAME_INSTALL_LOCATION_KEY = "InstallLocation"

# KEY_LOCAL_MACHINE
STEAM_REGISTRY_PATH_32 = r"SOFTWARE\Valve\Steam"
STEAM_REGISTRY_PATH_64 = r"SOFTWARE\WOW6432Node\Valve\Steam"
STEAM_INSTALL_LOCATION_KEY = "InstallPath"
STEAM_STEAMAPPS_FOLDER = "steamapps"
STEAM_APP_MANIFEST_FILE_PREFIX = "appmanifest"
LIBRARY_FOLDERS_VDF_FILE = "libraryfolders.vdf"
STEAM_LIBRARY_FOLDERS_FILE_TRAIL = Path("config") / LIBRARY_FOLDERS_VDF_FILE # Trail to join to steam install main path

LINUX_DISTRO_PATHS = [
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    # Path.home() / ".steam"
]

MACOS_DISTRO_PATHS = [
    Path.home() / "Library" / "Application Support" / "Steam"
]


class SteamHelper:
    def __init__(self):
        self.steam_install = None
        self.steam_library_paths = []

    @staticmethod
    def _vdf_line_contains(vdf_line, argument_to_check) -> list:
        vdf_line = str(vdf_line).lstrip().rstrip()
        log.debug(f"{vdf_line} contains {argument_to_check}")
        # steamlog.log_debug(f"{str(argument_to_check).upper()} in {vdf_line.upper()} = {str(argument_to_check).upper() in vdf_line.upper()}")
        if str(argument_to_check).upper() in vdf_line.upper():
            return vdf_line.split('"')

        return []

    def get_game_install_info_from_name(self, game_name) -> dict:
        # Parse Steam appmanifests (.acf files) in case of windows
        # For linux, get libraries and find the installation folder

        log.info(f"Getting installation details for game: {game_name}")

        if not self.steam_install:
            self.steam_install = self.get_steam_install_path()
            if not self.steam_install:
                return {}

        log.info(f"Steam install path: {self.steam_install}")

        if not self.steam_library_paths:
            self.steam_library_paths = self.get_steam_libraries()
            if not self.steam_library_paths or self.steam_library_paths == []:
                log.error("No Steam Libraries found.")
                return {}

        log.info(f"Steam library paths: {self.steam_library_paths}")

        for lib in self.steam_library_paths:
            log.info(f"Checking Library \"{lib}\"")
            for file in os.listdir(lib):
                fname = file
                file = os.path.join(lib, fname)

                if not os.path.isfile(file):
                    log.debug(f"Not a file: {file}")
                    continue

                if STEAM_APP_MANIFEST_FILE_PREFIX not in fname:
                    continue

                app_id = self.get_from_vdf_file(file, "appid")[0] # List of AppIDs
                title = self.get_from_vdf_file(file, "name")[0] # 1 Name

                # Value to look for seems to always be in index 3
                # title = line_name[3]
                # app_id = line_app_id[3]
                log.debug(f"{app_id}: {title}")
                if title == game_name:
                    log.debug(f"Found title match: {title} with App Id {app_id} in {fname} in library {lib}")
                    _fwd_slashed_path = str(Path(os.path.join(lib, f"common/{title}"))).replace('\\', '/').replace('\\\\', '/')
                    log.info(f'Found game install in {_fwd_slashed_path}')
                    return {
                        "title": title,
                        "app-id": app_id,
                        "steam-library": lib
                    }

        log.error(f"Unable to determine installation information for {game_name}")
        return {}

    def recursive_dict_find_value(self, dict_to_find, key_to_find, stop_on_find=False):
        matches = []
        for key, val in dict_to_find.items():
            # if isinstance(val, dict):
            #     steamlog.debug(f"\n{key}: {json.dumps(val, indent=2)}")
            # else:
            #     steamlog.debug(f"{key}: {val}")
            if key == key_to_find:
                matches.append(val)
                log.debug(f"Found {val} in {key}")
                if stop_on_find:
                    return matches
            elif isinstance(val, dict):
                recurse_matches = self.recursive_dict_find_value(val, key_to_find)
                if recurse_matches is not None:
                    matches.extend([f"{k_value}" for k_value in recurse_matches])
        return matches

    def get_from_vdf_file(self, vdf_file, key, stop_on_find=False) -> list:
        """
        Retrieve values from Steam's .vdf and .acf files.

        :param vdf_file:
        :param key:
        :param stop_on_find:
        :return: A list of matching parameters.
        """

        log.debug(f"From {Path(vdf_file).name} getting values of key \"{key}\"")

        vdf_fh = vdf.load(open(vdf_file))
        values_out = self.recursive_dict_find_value(vdf_fh, key, stop_on_find)

        # for k, v in vdf_fh.items():
        #     print(f"{k=}: {v=}")
        #
        # values_out = []
        #
        # for line in vdf_fh:
        #     line = line.lstrip().rstrip()
        #
        #     value = self._vdf_line_contains(line, key)
        #
        #     if value:
        #         for v in value:
        #             values_out.append(v)

        log.info(f"Gathered: {values_out}")
        return values_out

    def get_steam_libraries(self) -> Union[list, bool]:
        log.info("Getting available Steam Libraries...")

        library_file = ''

        if not self.steam_install:
            self.steam_install = self.get_steam_install_path()
            if not self.steam_install:
                return False

        if OS.WINDOWS:
            library_file = os.path.join(self.steam_install, STEAM_LIBRARY_FOLDERS_FILE_TRAIL)
        else:
            for root, dirs, files in os.walk(self.steam_install):
                if "config" in dirs:
                    library_file = os.path.join(root, STEAM_LIBRARY_FOLDERS_FILE_TRAIL)
                    break

        if not os.path.exists(library_file):
            log.error("Could not locate Steam Library file.")
            return False

        path_list = self.get_from_vdf_file(library_file, "path")

        if not path_list:
            return False

        # So far, path seems to be in the 2nd index of the list but let's iterate over list and check for valid path
        for item in path_list:
            if os.path.isdir(item):
                item = os.path.join(item, STEAM_STEAMAPPS_FOLDER)
                if item not in self.steam_library_paths:
                    self.steam_library_paths.append(os.path.abspath(item))

        log.debug(f"Known paths: {self.steam_library_paths}")

        return self.steam_library_paths

    def get_game_install_path(self, game_name) -> Union[Path, bool]:
        log.info(f"Acquiring {game_name} installation...")

        install_details = self.get_game_install_info_from_name(game_name)

        if not install_details:
            return False

        title_name = install_details.get("title")
        install_folder = Path(install_details.get("steam-library")) / "common" / title_name

        return install_folder

    def get_steam_install_path(self) -> Path:
        log.info("Acquiring Steam installation...")

        saved_path = settings.get_steam_install_path()
        if saved_path:
            if Path(saved_path).exists():
                self.steam_install = saved_path
                log.info(f"Got Steam install path from Settings")
                return self.steam_install

        if OS.WINDOWS:
            # Try 64-bit first
            steam = registry_helper.read_key(STEAM_REGISTRY_PATH_64, STEAM_INSTALL_LOCATION_KEY)

            # Try 32-bit if 64 failed.
            if not steam:
                steam = registry_helper.read_key(STEAM_REGISTRY_PATH_32, STEAM_INSTALL_LOCATION_KEY)
        elif OS.LINUX:
            steam = None
            for distro_path in LINUX_DISTRO_PATHS:
                if Path(distro_path).exists():
                    steam = distro_path
                    break
        elif OS.MACOS:
            steam = None
            for distro_path in MACOS_DISTRO_PATHS:
                log.info(f"Path exists: {distro_path.exists()} \"{distro_path}\"")
                if Path(distro_path).exists():
                    steam = distro_path
                    break
        else:
            steam = None

        if steam:
            self.steam_install = steam
            settings.set_steam_install_path(str(self.steam_install))
        else:
            log.error("Unable to acquire Steam installation.")
        
        return steam
        