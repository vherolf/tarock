from cx_Freeze import setup, Executable
import sys

build_exe_options = {
    "packages": ["PyQt6", "matplotlib", "numpy"],
    "excludes": [],
    "include_files": ["player_numbers.csv", "result.csv"]
}

base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="TarockTournamentOrganizer",
    version="1.0",
    description="Tarock Tournament Organizer",
    options={"build_exe": build_exe_options},
    executables=[Executable("tarockmanager.py", base=base)]
)
