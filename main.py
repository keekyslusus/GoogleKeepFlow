import sys
from pathlib import Path
import webbrowser
import logging
from logging.handlers import RotatingFileHandler
import subprocess

plugindir = Path(__file__).parent.resolve()
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / 'lib'
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from flox import Flox
import gkeepapi


class GoogleKeepPlugin(Flox):
    def __init__(self):
        super().__init__()
        self.keep = None

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        log_handler = RotatingFileHandler(
            plugindir / "plugin.log",
            maxBytes=1*1024*1024,
            backupCount=1,
            encoding='utf-8'
        )
        log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        self.logger.addHandler(log_handler)
        self.logger.setLevel(logging.INFO)

    def query(self, query_text):
        email = self.settings.get('email', '').strip()
        master_token = self.settings.get('master_token', '').strip()

        if not email or not master_token:
            self.add_item(
                title="GoogleKeepFlow not configured",
                subtitle="Open plugin settings to configure email and master token",
                icon="keep.png"
            )
            self.add_item(
                title="Get Master Token",
                subtitle="Click to open token generator website gkeeptokengenerator.duckdns.org",
                icon="keep.png",
                method=self.open_token_generator,
                parameters=[]
            )
            return

        if not query_text.strip():
            self.add_item(
                title="GoogleKeepFlow",
                subtitle="Type text to add as a note, or 'list' to view recent notes",
                icon="keep.png"
            )
            return

        if query_text.strip().lower() == 'list':
            self.list_notes(email, master_token)
            return

        self.add_item(
            title=f"Add note: {query_text}",
            subtitle="Press Enter to add to Google Keep",
            icon="keep.png",
            method=self.add_note,
            parameters=[email, master_token, query_text]
        )

    def list_notes(self, email, master_token):
        self.logger.info("Listing notes...")

        try:
            max_notes = int(self.settings.get('max_notes_to_show', '10'))
        except:
            max_notes = 10

        try:
            keep = gkeepapi.Keep()
            keep.authenticate(email, master_token, sync=True)
            self.logger.info("Loaded notes successfully")

            all_notes = keep.all()
            notes = sorted([n for n in all_notes if not n.trashed and not n.archived],
                          key=lambda x: x.timestamps.updated,
                          reverse=True)[:max_notes]

            if not notes:
                self.add_item(
                    title="No notes found",
                    subtitle="Create your first note!",
                    icon="keep.png"
                )
                return

            for note in notes:
                if note.title:
                    title = note.title.replace('\n', ' ').strip()
                    subtitle = note.text.replace('\n', ' | ').strip()[:100]
                    if len(note.text) > 100:
                        subtitle += "..."
                else:
                    lines = note.text.split('\n')
                    title = lines[0][:50].strip()
                    if len(lines[0]) > 50:
                        title += "..."
                    if len(lines) > 1:
                        subtitle = ' | '.join(lines[1:])[:100].strip()
                        if len(' '.join(lines[1:])) > 100:
                            subtitle += "..."
                    else:
                        subtitle = "Click to open in Google Keep"

                self.add_item(
                    title=title,
                    subtitle=subtitle if subtitle else "Click to open in Google Keep",
                    icon="keep.png",
                    method=self.open_note,
                    parameters=[note.id]
                )

        except Exception as e:
            self.logger.error(f"Failed to list notes: {type(e).__name__}: {e}")
            self.add_item(
                title="Failed to load notes",
                subtitle=str(e),
                icon="keep.png"
            )

    def add_note(self, email, master_token, text):
        self.logger.info(f"Adding note: {text[:50]}...")

        worker_script = plugindir / "sync_worker.py"
        # checkbox returns boolean, convert to string for subprocess
        show_notifications = str(self.settings.get('show_notifications', True))

        try:
            startupinfo = None
            creationflags = 0
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

            subprocess.Popen(
                [sys.executable, str(worker_script), email, master_token, text, show_notifications],
                startupinfo=startupinfo,
                creationflags=creationflags,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            self.logger.info("Sync worker started")
            return "Note added!"
        except Exception as e:
            self.logger.error(f"Failed to start sync worker: {type(e).__name__}: {e}")
            return f"Failed: {str(e)}"

    def authenticate(self, email, master_token):
        if self.keep is not None:
            return True

        if not email or not master_token:
            return False

        try:
            self.keep = gkeepapi.Keep()
            self.keep.authenticate(email, master_token, sync=False)
            self.logger.info("Authentication successful")
            return True
        except Exception as e:
            self.logger.error(f"Authentication failed: {type(e).__name__}: {e}")
            self.keep = None
            return False

    def open_note(self, note_id):
        self.logger.info(f"Opening note: {note_id}")
        url = f"https://keep.google.com/u/0/#NOTE/{note_id}"
        webbrowser.open(url)
        return "Opening note in browser..."

    def open_token_generator(self):
        webbrowser.open('https://gkeeptokengenerator.duckdns.org')
        return "Opening token generator in browser..."

if __name__ == "__main__":
    GoogleKeepPlugin().run()