import os
import sys
import tempfile
import uuid
import json
import time
from tkinter import *
from tkinter import filedialog, messagebox, colorchooser, simpledialog, font, ttk

AUTOSAVE_INTERVAL_MS = 30_000  # autosave every 30 seconds
AUTOSAVE_PREFIX = "advanced_text_editor_autosave_"
AUTOSAVE_META_EXT = ".meta.json"

class TabData:
    def __init__(self, frame, text_widget, file_path=None, autosave_id=None):
        self.frame = frame
        self.text = text_widget
        self.file_path = file_path
        self.autosave_id = autosave_id or str(uuid.uuid4())

class AdvancedEditor:
    def __init__(self, root):
        self.root = root
        root.title("Texter")
        root.geometry("1000x700")

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        self.tabs = {}  # tab_id -> TabData
        self.current_font = StringVar(value="Helvetica")
        self.current_font_size = IntVar(value=12)
        self.bold_active = False
        self.italic_active = False
        self.underline_active = False
        self.wrap_on = BooleanVar(value=True)
        self.dark_mode = BooleanVar(value=False)

        self.file_menu_actions = {}
        self._build_menus()
        self._build_statusbar()
        self._bind_shortcuts()
        self._create_tab()  # start with one tab

        # Autosave setup
        self.autosave_dir = tempfile.gettempdir()
        self._recover_autosaves_on_startup()
        self._schedule_autosave()

    # ---------- Tab management ----------
    def _create_tab(self, title="Untitled", content="", file_path=None, recovered=False, autosave_id=None):
        frame = Frame(self.notebook)
        text = Text(frame, undo=True, wrap="word" if self.wrap_on.get() else "none")
        text.pack(fill="both", expand=True)
        text.insert("1.0", content)
        text.bind("<KeyRelease>", self._on_text_change)
        text.bind("<ButtonRelease>", self._update_status)
        apply_font = font.Font(family=self.current_font.get(), size=self.current_font_size.get(),
                               weight="bold" if self.bold_active else "normal",
                               slant="italic" if self.italic_active else "roman",
                               underline=1 if self.underline_active else 0)
        text.config(font=apply_font)
        tab_id = self.notebook.add(frame, text=title if not recovered else f"Recovered - {title}")
        td = TabData(frame, text, file_path=file_path, autosave_id=autosave_id)
        self.tabs[frame] = td
        self.notebook.select(frame)
        self._update_status()
        return td

    def _close_current_tab(self):
        sel = self.notebook.select()
        if not sel:
            return
        frame = self.root.nametowidget(sel)
        td = self.tabs.get(frame)
        if td:
            if messagebox.askyesno("Close tab", "Close this tab? Unsaved changes will be lost."):
                self._remove_autosave_file(td)
                self.notebook.forget(frame)
                del self.tabs[frame]
                if not self.tabs:
                    self._create_tab()

    def _new_tab(self, event=None):
        self._create_tab()

    def _open_in_new_tab(self, event=None):
        path = filedialog.askopenfilename()
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        title = os.path.basename(path)
        self._create_tab(title=title, content=content, file_path=path)

    def _save_current_tab(self, event=None):
        td = self._get_current_tabdata()
        if not td:
            return
        if td.file_path:
            self._write_file(td.file_path, td.text.get("1.0", "end-1c"))
            self._update_tab_title(td)
        else:
            self._save_current_tab_as()

    def _save_current_tab_as(self, event=None):
        td = self._get_current_tabdata()
        if not td:
            return
        path = filedialog.asksaveasfilename()
        if not path:
            return
        self._write_file(path, td.text.get("1.0", "end-1c"))
        td.file_path = path
        self._update_tab_title(td)
        self._remove_autosave_file(td)  # clear autosave metadata since user saved

    def _write_file(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        messagebox.showinfo("Saved", f"Saved to {path}")

    def _update_tab_title(self, td):
        title = os.path.basename(td.file_path) if td.file_path else "Untitled"
        self.notebook.tab(td.frame, text=title)

    def _get_current_tabdata(self):
        sel = self.notebook.select()
        if not sel:
            return None
        frame = self.root.nametowidget(sel)
        return self.tabs.get(frame)

    # ---------- Status bar ----------
    def _build_statusbar(self):
        self.status = StringVar()
        self.status_label = Label(self.root, textvariable=self.status, anchor="w")
        self.status_label.grid(row=1, column=0, sticky="we")

    def _update_status(self, event=None):
        td = self._get_current_tabdata()
        if not td:
            self.status.set("")
            return
        cursor_pos = td.text.index(INSERT)
        row, col = cursor_pos.split(".")
        content = td.text.get("1.0", "end-1c")
        words = len(content.split())
        chars = len(content)
        tab_title = os.path.basename(td.file_path) if td.file_path else self.notebook.tab(td.frame, option="text")
        self.status.set(f"{tab_title} | Ln {row} | Col {int(col)+1} | Words {words} | Chars {chars}")

    def _on_text_change(self, event=None):
        self._update_status()

    # ---------- Autosave ----------
    def _autosave_all_tabs(self):
        for td in list(self.tabs.values()):
            try:
                content = td.text.get("1.0", "end-1c")
                fname = AUTOSAVE_PREFIX + td.autosave_id + ".txt"
                fpath = os.path.join(self.autosave_dir, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
                meta = {
                    "file_path": td.file_path,
                    "timestamp": time.time(),
                    "title": os.path.basename(td.file_path) if td.file_path else self.notebook.tab(td.frame, option="text")
                }
                meta_path = fpath + AUTOSAVE_META_EXT
                with open(meta_path, "w", encoding="utf-8") as m:
                    json.dump(meta, m)
            except Exception:
                pass  # fail autosave silently
        self._schedule_autosave()

    def _schedule_autosave(self):
        self.root.after(AUTOSAVE_INTERVAL_MS, self._autosave_all_tabs)

    def _list_autosave_files(self):
        files = []
        for name in os.listdir(self.autosave_dir):
            if name.startswith(AUTOSAVE_PREFIX) and name.endswith(".txt"):
                files.append(os.path.join(self.autosave_dir, name))
        return files

    def _recover_autosaves_on_startup(self):
        autosave_files = self._list_autosave_files()
        if not autosave_files:
            return
        to_recover = []
        for fpath in autosave_files:
            meta_path = fpath + AUTOSAVE_META_EXT
            try:
                with open(meta_path, "r", encoding="utf-8") as m:
                    meta = json.load(m)
            except Exception:
                meta = {"file_path": None, "title": "Recovered"}
            to_recover.append((fpath, meta))
        if not to_recover:
            return
        if not messagebox.askyesno("Recover files", f"Found {len(to_recover)} autosave file(s). Recover them?"):
            return
        for fpath, meta in to_recover:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""
            title = meta.get("title") or "Recovered"
            file_path = meta.get("file_path")
            autosave_id = os.path.basename(fpath)[len(AUTOSAVE_PREFIX):-4]
            self._create_tab(title=title, content=content, file_path=file_path, recovered=True, autosave_id=autosave_id)
            # remove autosave after recovery
            try:
                os.remove(fpath)
                mp = fpath + AUTOSAVE_META_EXT
                if os.path.exists(mp):
                    os.remove(mp)
            except Exception:
                pass

    def _remove_autosave_file(self, td):
        fname = AUTOSAVE_PREFIX + td.autosave_id + ".txt"
        fpath = os.path.join(self.autosave_dir, fname)
        metapath = fpath + AUTOSAVE_META_EXT
        for p in (fpath, metapath):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # ---------- Menus and tools ----------
    def _build_menus(self):
        menu_bar = Menu(self.root)
        self.root.config(menu=menu_bar)

        file_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New Tab", command=self._new_tab, accelerator="Ctrl+T")
        file_menu.add_command(label="Open in New Tab", command=self._open_in_new_tab, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self._save_current_tab, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As", command=self._save_current_tab_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", command=self._close_current_tab, accelerator="Ctrl+W")
        file_menu.add_command(label="Exit", command=self._exit_editor, accelerator="Ctrl+Q")

        edit_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", command=self._undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self._redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", command=self._cut, accelerator="Ctrl+X")
        edit_menu.add_command(label="Copy", command=self._copy, accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste", command=self._paste, accelerator="Ctrl+V")
        edit_menu.add_command(label="Select All", command=self._select_all, accelerator="Ctrl+A")
        edit_menu.add_command(label="Clear All", command=self._clear_all)

        format_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Format", menu=format_menu)
        font_menu = Menu(format_menu, tearoff=0)
        for f in ["Helvetica", "Courier", "Times", "Arial", "Consolas"]:
            font_menu.add_radiobutton(label=f, variable=self.current_font, command=lambda f=f: self._set_font_family(f))
        format_menu.add_cascade(label="Font", menu=font_menu)

        size_menu = Menu(format_menu, tearoff=0)
        for s in [8, 10, 12, 14, 16, 18, 20, 24, 28]:
            size_menu.add_radiobutton(label=str(s), variable=self.current_font_size, command=lambda s=s: self._set_font_size(s))
        format_menu.add_cascade(label="Size", menu=size_menu)
        format_menu.add_command(label="Text Color", command=self._set_text_color)
        format_menu.add_separator()
        format_menu.add_command(label="Bold", command=self._toggle_bold)
        format_menu.add_command(label="Italic", command=self._toggle_italic)
        format_menu.add_command(label="Underline", command=self._toggle_underline)

        view_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="View", menu=view_menu)
        view_menu.add_checkbutton(label="Word Wrap", variable=self.wrap_on, command=self._toggle_wrap)
        view_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self._toggle_dark_mode)

        tools_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Find / Replace", command=self._find_replace)

        help_menu = Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", "Texter - Text Editor\nBuilt with Python\nBy Shreyash Srivastva"))

    # ---------- Edit helpers ----------
    def _undo(self): 
        td = self._get_current_tabdata()
        if td: td.text.edit_undo()
    def _redo(self): 
        td = self._get_current_tabdata()
        if td: td.text.edit_redo()
    def _cut(self):
        td = self._get_current_tabdata()
        if td: td.text.event_generate("<<Cut>>")
    def _copy(self):
        td = self._get_current_tabdata()
        if td: td.text.event_generate("<<Copy>>")
    def _paste(self):
        td = self._get_current_tabdata()
        if td: td.text.event_generate("<<Paste>>")
    def _select_all(self, event=None):
        td = self._get_current_tabdata()
        if td:
            td.text.tag_add("sel", "1.0", "end")
            return "break"
    def _clear_all(self):
        td = self._get_current_tabdata()
        if td:
            td.text.delete("1.0", "end")

    # ---------- Format helpers ----------
    def _apply_format_to_current(self):
        td = self._get_current_tabdata()
        f = font.Font(family=self.current_font.get(), size=self.current_font_size.get(),
                      weight="bold" if self.bold_active else "normal",
                      slant="italic" if self.italic_active else "roman",
                      underline=1 if self.underline_active else 0)
        if td:
            td.text.config(font=f)

    def _toggle_bold(self):
        self.bold_active = not self.bold_active
        self._apply_format_to_current()

    def _toggle_italic(self):
        self.italic_active = not self.italic_active
        self._apply_format_to_current()

    def _toggle_underline(self):
        self.underline_active = not self.underline_active
        self._apply_format_to_current()

    def _set_font_family(self, fam):
        self.current_font.set(fam)
        self._apply_format_to_current()

    def _set_font_size(self, s):
        self.current_font_size.set(s)
        self._apply_format_to_current()

    def _set_text_color(self):
        color = colorchooser.askcolor()[1]
        td = self._get_current_tabdata()
        if color and td:
            td.text.config(fg=color)

    # ---------- View helpers ----------
    def _toggle_wrap(self):
        td = self._get_current_tabdata()
        for td in self.tabs.values():
            td.text.config(wrap="word" if self.wrap_on.get() else "none")

    def _toggle_dark_mode(self):
        if self.dark_mode.get():
            for td in self.tabs.values():
                td.text.config(bg="#1e1e1e", fg="#ffffff", insertbackground="white")
            self.status_label.config(bg="#2e2e2e", fg="white")
        else:
            for td in self.tabs.values():
                td.text.config(bg="white", fg="black", insertbackground="black")
            self.status_label.config(bg="SystemButtonFace", fg="black")

    # ---------- Find/Replace ----------
    def _find_replace(self):
        find_str = simpledialog.askstring("Find", "Find:")
        if not find_str:
            return
        replace_str = simpledialog.askstring("Replace", "Replace with (leave blank to skip):")
        td = self._get_current_tabdata()
        if not td:
            return
        content = td.text.get("1.0", "end-1c")
        if replace_str is not None:
            new_content = content.replace(find_str, replace_str)
            td.text.delete("1.0", "end")
            td.text.insert("1.0", new_content)
        else:
            td.text.tag_remove("highlight", "1.0", "end")
            start = "1.0"
            while True:
                start = td.text.search(find_str, start, stopindex="end")
                if not start:
                    break
                end = f"{start}+{len(find_str)}c"
                td.text.tag_add("highlight", start, end)
                start = end
            td.text.tag_config("highlight", background="yellow", foreground="black")

    # ---------- Shortcuts & exit ----------
    def _bind_shortcuts(self):
        self.root.bind("<Control-t>", lambda e: self._new_tab())
        self.root.bind("<Control-o>", lambda e: self._open_in_new_tab())
        self.root.bind("<Control-s>", lambda e: self._save_current_tab())
        self.root.bind("<Control-w>", lambda e: self._close_current_tab())
        self.root.bind("<Control-q>", lambda e: self._exit_editor())
        self.root.bind("<Control-a>", lambda e: self._select_all())

    def _exit_editor(self):
        if messagebox.askyesno("Exit", "Close the editor?"):
            # cleanup autosave files for tabs with no content or saved
            for td in list(self.tabs.values()):
                # if saved to disk then remove autosave
                if td.file_path:
                    self._remove_autosave_file(td)
            self.root.destroy()

if __name__ == "__main__":
    root = Tk()
    app = AdvancedEditor(root)
    root.mainloop()
