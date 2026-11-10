# MD Reader

A clean, modern Markdown reader and editor for Windows.

- **Home screen** with its own **Home** button at the left of the tab row (`Alt+Home`): open a file, start a new one, continue where you left off, or pick a recent file. Closing the last tab brings you back here.
- **File menu** (top left): new, open, open recent, save, save as, reload, export, show in folder, close tab, close all tabs.
- **Tabs**: open as many .md files as you like, one tab each (`Ctrl+T` new, `Ctrl+W` close, `Ctrl+Tab` next, middle-click closes, drag to reorder). Double-clicking more .md files adds tabs to the open window instead of opening new windows.
- **Preview / Raw** switch in the middle of the top bar (`Ctrl+1` / `Ctrl+2`).
- **Read-only by default.** Flip the **Edit** switch (`Ctrl+E`) any time. Editing in Preview shows the editor beside a live preview.
- **Copy table cells.** Hover any cell and click the copy icon. Hover a table and click **Copy table** to copy the whole table (pastes into Excel). Code blocks get a Copy button too.
- **Dark and light themes** (sun/moon icon or `Ctrl+Shift+D`), or follow Windows. Six accent colours.
- **Settings** (gear icon): Make default, Install / Uninstall, text size, fonts, page width, table copy buttons, start in edit mode, live preview, sync scrolling, word wrap, what to show when the app opens (home screen or last files), auto-reload.
- Find (`Ctrl+F`), recent files, drag and drop, export to HTML or PDF, unsaved-changes warning, reload when a file changes on disk.

## Get the app (EXE)
1. Have Python 3 with PySide6 and PyInstaller installed (or internet once so the script can get them).
2. Double-click **Build EXE.bat**. It makes `dist\MD Reader\MD Reader.exe` (keep that whole folder together).
3. Run `MD Reader.exe`. It asks **Install** or **Portable**, like HK-Master:
   - **Just for me**: installs to `%LOCALAPPDATA%\Programs\MD Reader`.
   - **All users** (shield icon): installs to `Program Files\MD Reader`; Windows asks for permission.
   - **Set as default .md reader / editor** and **Add a desktop shortcut** are switches in the same window.
   - **Portable** runs that copy without installing.
4. The installed app shows up in **Windows Settings > Apps** and can be uninstalled there, or from **Settings > Uninstall…** inside the app (it asks whether to also delete your settings).

About the default app: Windows 10/11 don't let programs silently take over a file type you've already assigned to another app. If .md files were set to open in something else, MD Reader shows Windows' own "How do you want to open .md files?" window once; pick **MD Reader** and click **Always**.

## Run without building (Python script)
Double-click **Run MD Reader.bat**.

Both .bat files work **without internet**. They find Python on their own (py launcher, PATH, or the usual install folders, preferring a copy that already has PySide6), and install markdown, pygments and pymdown-extensions from the **wheels** folder next to them. They only go online if PySide6 or PyInstaller is missing, and only after a quick check shows the internet is reachable. **Make default** in Settings works here too; installing needs the EXE.

## Shortcuts
| Keys | Action |
|---|---|
| `Ctrl+O` | Open files |
| `Ctrl+T` / `Ctrl+N` | New tab |
| `Ctrl+W` | Close tab |
| `Ctrl+Shift+W` | Close all tabs |
| `Alt+Home` | Home screen |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / save as |
| `Ctrl+E` | Edit on / off |
| `Ctrl+1` / `Ctrl+2` | Preview / Raw |
| `Ctrl+F` | Find |
| `Ctrl+Shift+D` | Dark / light |
| `Ctrl+,` | Settings |
| `Ctrl +` / `Ctrl -` / `Ctrl+0` | Zoom |
| `F5` | Reload from disk |

Settings live in `settings.json` next to the app when portable, or in `%APPDATA%\MD Reader` when installed.

## License
MD Reader is free software, licensed under the [GNU General Public License v3.0 or later](LICENSE). You can use, change and share it; if you share a changed version, it must stay under the GPL with its source available.
