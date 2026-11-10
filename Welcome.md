# Welcome to MD Reader

A clean reader for Markdown files. Switch between **Preview** and **Raw** with the tabs at the top, and turn on **Edit** whenever you want to change something.

> [!TIP]
> Hover any table cell and click the copy icon to copy just that cell. Hover above a table to copy the whole table, ready to paste into Excel.

## Quick tour

| Feature | How to use it | Shortcut |
|---|---|---|
| Preview / Raw | Tabs in the middle of the top bar | `Ctrl+1` / `Ctrl+2` |
| Edit mode | The **Edit** switch (off by default) | `Ctrl+E` |
| Copy a cell | Hover a cell, click the copy icon | |
| Find | Search icon, top right | `Ctrl+F` |
| Tabs | One tab per file, + for a new one | `Ctrl+T` / `Ctrl+W` |
| Dark / light | Sun / moon icon | `Ctrl+Shift+D` |
| Settings | Gear icon | `Ctrl+,` |

## What renders

Things you'd expect from GitHub-style Markdown:
- **Bold**, *italic*, ~~strikethrough~~, ==highlight==, `inline code`
- Links like [python.org](https://www.python.org) and plain URLs: https://github.com
- Nested lists with 2-space indents
  - like this one
    - and deeper
- Task lists
  - [x] Read-only by default
  - [x] Copy buttons on table cells
  - [ ] Your next idea

1. Numbered lists
2. Keep their numbers
   1. And nest too

### Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"

print(greet("MD Reader"))
```

### Quotes and alerts

> Simplicity is prerequisite for reliability.
> — Edsger W. Dijkstra

> [!NOTE]
> GitHub alerts (`[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`) are supported.

> [!WARNING]
> Unsaved changes are marked with a dot in the title. You'll be asked before anything is lost.

---

Footnotes work too.[^1]

[^1]: Like this one.
