import os
import sys
import winreg

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "SpotifyAutoSkipper"


def _get_exe_path():
    """Get the path to use for the startup registry entry."""
    if getattr(sys, 'frozen', False):
        # PyInstaller .exe
        return sys.executable
    else:
        # Running as script — use pythonw to avoid console window
        python_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(python_dir, "pythonw.exe")
        script = os.path.abspath(sys.argv[0])
        if os.path.exists(pythonw):
            return f'"{pythonw}" "{script}"'
        return f'"{sys.executable}" "{script}"'


def enable_startup():
    """Add the app to Windows startup via registry."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _get_exe_path())
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def disable_startup():
    """Remove the app from Windows startup."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return True  # Already removed
    except OSError:
        return False


def is_startup_enabled():
    """Check if the app is set to start with Windows."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup(enabled):
    """Enable or disable startup based on boolean."""
    if enabled:
        return enable_startup()
    else:
        return disable_startup()
