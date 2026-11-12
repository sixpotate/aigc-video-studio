"""Prefer installed Chrome without changing the Windows default browser."""
import json,os,pathlib,subprocess,webbrowser
from settings import APP_DIR,CREATE_NO_WINDOW

def chrome_path():
    candidates=[]
    try:candidates.append(json.loads((APP_DIR/'browser.json').read_text('utf-8'))['chrome_path'])
    except (OSError,ValueError,KeyError):pass
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            for key in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'):
                try:
                    with winreg.OpenKey(hive,key) as handle:candidates.append(winreg.QueryValue(handle,None))
                except OSError:pass
    for env in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        if os.environ.get(env):candidates.append(str(pathlib.Path(os.environ[env])/'Google/Chrome/Application/chrome.exe'))
    for item in candidates:
        if isinstance(item,str):
            path=pathlib.Path(item.strip('"'))
            if path.name.lower()=='chrome.exe' and path.is_file():return path
    return None

def open_studio(url):
    chrome=chrome_path()
    if chrome:
        subprocess.Popen([str(chrome),url],creationflags=CREATE_NO_WINDOW)
        return True
    return webbrowser.open(url)
