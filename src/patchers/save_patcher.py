import sys
import os
import shutil
import requests
import base64
from pathlib import Path
import zipfile
import tempfile

# 3rd Party
from conf_globals import settings, OS, LOG_LEVEL
from logger import create_logger

log = create_logger("Save Patcher", LOG_LEVEL)


def get_current_dir():
    if getattr(sys, "frozen", False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(__file__)

    return application_path


def get_user_save_folder():
    log.info("Attempting to locate Stellaris save game folder.")
    documents_dir = ''

    # Windows
    if OS.WINDOWS or OS.MACOS:
        log.info("Locating for Windows system.")
        documents_dir = Path.home() / "Documents" / "Paradox Interactive" / "Stellaris" / "save games"
    # Unix
    elif OS.LINUX:
        # TODO: IT COULD BE INSTALLED ON OTHER DRIVES
        # FIND libraryfolders.vdf IN .steam/root/config
        # GET THE OTHER DRIVES IN THE libraryfolders.vdf
        # ITERATE THROUGH THOSE DRIVES TO FIND THE save games FOLDER.

        pdx_dir = ''

        home_steam = Path.home() / ".steam"

        log.info("Locating for Linux\\Unix system.")
        for root, dirs, files in os.walk(home_steam):
            log.debug(f"{root}")
            log.debug(f"\t{dirs}")
            if Path(root).name == "Paradox Interactive":
                print(f"Found in {root}")
                pdx_dir = root
                break
            for usr_dir in dirs:
                if Path(usr_dir).name == "Paradox Interactive":
                    print(f"Found in {usr_dir}")
                    pdx_dir = usr_dir
                    break

        if pdx_dir:
            documents_dir = Path(pdx_dir) / "Stellaris" / "save games"
    elif OS.MACOS:
        pass
    # Uh oh
    else:
        log.error("Unable to acquire target system.")
        pass

    if not Path(documents_dir).exists():
        log.info(f"Unable to find documents dir. Current try: \"{documents_dir}\"")
        documents_dir = os.path.dirname(sys.executable)
    else:
        log.info(f"Found {documents_dir}")

    return documents_dir


def repair_save(save_file):
    # .sav
    save_dir = Path(save_file).parent
    save_file_name = Path(save_file).name
    save_file_times = (os.stat(save_file).st_atime, os.stat(save_file).st_mtime)

    log.info(f"Save Directory: {save_dir}")
    log.info(f"Save Name: {save_file_name}")

    # Repair directory
    repair_dir = save_dir / "save_repair"
    Path(repair_dir).mkdir(parents=True, exist_ok=True)
    log.debug(f"Repair Directory: {repair_dir}")

    # Backup directory
    # backup_dir = Path(get_current_dir()) / "saves_backup" / save_dir.name
    backup_dir = settings.get_config_dir() / "saves_backup" / save_dir.name
    backup_save_file = Path(backup_dir) / save_file_name
    Path(backup_dir).mkdir(parents=True, exist_ok=True)

    # Create Backup of the save
    try:
        log.info(f"Backup Directory: {backup_dir}")
        shutil.copy2(save_file, backup_save_file)
        log.info(f"Backed up {save_file_name} to {backup_save_file}")
    except Exception as e:
        log.error(e)

    # Try to unzip the save file
    try:
        with zipfile.ZipFile(save_file, 'r') as zip_file:
            zip_file.extractall(repair_dir)
    except Exception as e:
        log.error(e)

    # Store files and their access times
    files_access_times = {}
    for file in Path(repair_dir).iterdir():
        files_access_times[file.name] = (os.stat(file).st_atime, os.stat(file).st_mtime)

    # gamestate
    gamestate_file = Path(repair_dir) / "gamestate"

    # meta
    meta_file = Path(repair_dir) / "meta"

    # =======================================================
    # =================== GAMESTATE BLOCK ===================
    # =======================================================
    with open(gamestate_file, 'r', encoding="utf-8") as f:
        file = f.read()

    file_contents = file.splitlines()
    new_file_contents = file_contents.copy()

    # Pull up to date achievements
    achievements = pull_latest_achivements_file()

    if not achievements or achievements == '':
        log.error("Unable to fix save as achievements could not be retrieved.")
        return False

    # ==========================================================
    # =================== ACHIEVEMENTS BLOCK ===================
    # ==========================================================
    achievements_line_start = -1
    achievements_line_end = -1
    existing_achievements = False
    clusters_found = False
    is_proper_file = False

    # For each change we must iterate the file contents
    # As the insert changes the indices around and as such we must re iterate to account
    # For the new indices.
    # Achievement
    for i, line in enumerate(file_contents):
        if achievements_line_start == -1 and "achievement={" in line:
            existing_achievements = True
            achievements_line_start = i
            log.debug(f"Achievements line found: {i}")

        # If existing achievements line, the next } will be the closing bracket
        if existing_achievements and achievements_line_end == -1:
            if "}" in line:
                achievements_line_end = i
                log.debug(f"Achievements line close found: {i}")
                break

        # Deal with new contents directly.
        if not existing_achievements and "clusters={" in line:
            log.debug(f"clusters in line {i}.")
            clusters_found = True
            new_file_contents.insert(i, achievements)
            break

    # Ironman flag
    # For ironman=yes
    # We must parse the file to find galaxy={ section
    # In galaxy section, we must find name=
    # Immediately below name= there should be a line for ironman
    # If it isn't and if we don't find ironman= anywhere in the file
    # Insert ironman=yes at index of name= + 1, so it is the line directly below name=
    has_ironman_flag = False
    _has_passed_galaxy_line = False

    # Check for ironman flag existing once before full parse
    if "ironman=yes" in file_contents:
        has_ironman_flag = True

    if not has_ironman_flag:
        for i, line in enumerate(file_contents):
            if "galaxy={" in line:
                log.debug("Passed galaxy={")
                _has_passed_galaxy_line = True

            if _has_passed_galaxy_line:
                if "name=" in line:
                    log.debug("Found name= in galaxy={")
                    log.info("Setting ironman flag to yes.")
                    new_file_contents.insert(i+1, "\tironman=yes") # Must be a tabbed insert
                    break

    # Double check conditions are met to be able to write the proper file
    if existing_achievements or clusters_found:
        is_proper_file = True

    if not is_proper_file:
        log.error(f"The file {save_file_name} is not a proper file.")
        return False

    # Overwrite achievements line with updated contents
    if existing_achievements:
        offset = achievements_line_end - achievements_line_start
        log.debug(f"Line Offset: {offset}")
        if offset > 1:
            for i in range(offset+1): # offset +1 to include the ending line
                # Popping achievement line start means that once the line is popped,
                # the remaining lines will fill that spot, therefore the index is the same
                log.debug(f"Pop {new_file_contents[achievements_line_start]}")
                new_file_contents.pop(achievements_line_start)

            log.debug(f"Inserting achievements at {new_file_contents[achievements_line_start]}")
            new_file_contents.insert(achievements_line_start, achievements)
        else:
            new_file_contents[achievements_line_start] = achievements

    # ==============================================================
    # =================== END ACHIEVEMENTS BLOCK ===================
    # ==============================================================

    temp_file = Path(tempfile.gettempdir()) / "gamestate"
    with open(temp_file, 'w', encoding="utf-8") as new_file:
        new_file.write('\n'.join(new_file_contents))

    # Replace extracted gamestate with temp gamestate
    shutil.copy(temp_file, gamestate_file)

    # ==================================================
    # =================== META BLOCK ===================
    # ==================================================
    log.debug("Repairing meta")
    with open(meta_file, 'r', encoding="utf-8") as f:
        file = f.read()

    file_contents = file.splitlines()
    new_file_contents = file_contents.copy()

    if "ironman=yes" not in new_file_contents:
        log.debug(f"\n{new_file_contents}")
        log.debug("ironman=yes not found in meta file.")
        new_file_contents.append("ironman=yes")
        log.debug(f"\n{new_file_contents}")

    temp_file = Path(tempfile.gettempdir()) / "meta"
    with open(temp_file, 'w', encoding="utf-8") as new_file:
        new_file.write('\n'.join(new_file_contents))

    # Replace extracted meta with temp meta
    shutil.copy(temp_file, meta_file)

    # Rebuild .sav file
    with zipfile.ZipFile(save_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in Path(repair_dir).iterdir():
            # Fix files access times to their originals
            fname = file.name
            if fname in files_access_times.keys():
                os.utime(file, files_access_times.get(fname, None))
            with open(file, 'r', encoding="utf-8") as fread:
                zf.writestr(Path(file).name, fread.read())

    # Set access times from original
    os.utime(save_file, save_file_times)

    shutil.rmtree(repair_dir)

    log.info("Finished repairing save.")
    return True

def pull_latest_achivements_file():
    log.info("Pulling latest Achievements file from GitHub repository.")

    owner = "r0fld4nc3"
    repo_name = "Stellaris-Exe-Checksum-Patcher"
    download_cancelled = False

    repo = f"{owner}/{repo_name}"
    url = f"https://api.github.com/repos/{repo}/contents/StellarisChecksumPatcher/achievements/achievements.txt"
    log.debug(url)

    try:
        response = requests.get(url, timeout=60)
    except requests.ConnectionError as con_err:
        log.error(f"Unable to establish connection to update repo.")
        log.error(con_err)
        return False

    if not response.status_code == 200:
        log.error("Not a valid repository.")

    achievements_file = Path(os.path.dirname(__file__)).parent / "achievements" / "achievements.txt"
    try:
        pulled_release = response.json()["content"]
        achievements = base64.b64decode(pulled_release).decode("utf-8")
        log.debug(f"Decoded: {achievements}")
        # Update local achievements file
        log.info("Updating achievements file with repo content.")
        try:
            with open(achievements_file, 'w', encoding="utf-8") as ach_f:
                ach_f.write(achievements)
        except Exception as e:
            log.error(f"Error writing to achievements file.\nError: {e}")
    except Exception as e:
        log.info(f"Error in pulling achievements from repo. Falling back to physical file.\nError: {e}")
        log.debug(response.json())
        # Fallback to physical file
        log.debug(f"Achievements file: {achievements_file}")

        try:
            with open(achievements_file, 'r', encoding="utf-8") as ach_f:
                achievements = ach_f.read()
        except Exception as e:
            log.error(f"Error in accessing achievements file.\nError: {e}")
            achievements = ''

    return achievements


