import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import sqlite3
import json
import os
import logging
import threading
import time
from datetime import datetime
import webbrowser
import re
from collections import Counter
import shutil
from pathlib import Path
import sys
from contextlib import contextmanager

# Import AI APIs
from ai_apis import AIManager

# Import additional libraries
try:
    from wordcloud import WordCloud
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False
    
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

class PromptMiniApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Prompt Mini")
        
        # Load settings first to get window geometry
        self.settings = self.load_settings()
        
        # Set window geometry from settings
        window_geometry = self.settings.get('window_geometry', '1200x800+100+100')
        self.root.geometry(window_geometry)
        
        # Initialize logging
        self.setup_logging()
        
        # Apply log level from settings
        self.apply_log_level()
        
        # Initialize database
        self.init_database()
        
        # Debounce variables
        self.search_debounce_timer = None
        self.text_debounce_timer = None
        
        # Selected items tracking
        self.selected_items = []
        self.current_item = None
        
        # In-place editing state
        self.editing_mode = False
        self.editing_widgets = {}
        self.original_widgets = {}
        
        # Sorting state tracking
        self.sort_column = None
        self.sort_direction = None  # None, 'asc', 'desc'
        
        # Cache for frequently accessed prompts
        self.prompt_cache = {}
        self.logger.info("Initialized prompt cache")
        
        # Create UI
        self.create_menu()
        self.create_main_ui()
        
        # Bind window close event to save geometry
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Load initial data
        self.perform_search()
        
    def setup_logging(self):
        """Setup comprehensive logging system"""
        self.log_handler = logging.StreamHandler()
        self.log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.log_handler.setFormatter(formatter)
        
        # Create logger
        self.logger = logging.getLogger('PromptMini')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.log_handler)
        
        # Capture logs in memory for console display
        self.log_messages = []
        
        class LogCapture(logging.Handler):
            def __init__(self, app):
                super().__init__()
                self.app = app
                
            def emit(self, record):
                msg = self.format(record)
                self.app.log_messages.append((record.levelno, msg))
                if len(self.app.log_messages) > 1000:
                    self.app.log_messages = self.app.log_messages[-500:]
                
                # Update status bar with latest log message (single line)
                if hasattr(self.app, 'status_bar'):
                    # Extract just the message part (after the timestamp and level)
                    parts = msg.split(' - ')
                    if len(parts) >= 3:
                        status_msg = parts[-1].strip()  # Get the actual message
                        self.app.update_status_bar(status_msg)
        
        self.log_capture = LogCapture(self)
        self.log_capture.setFormatter(formatter)
        self.logger.addHandler(self.log_capture)
        
    def load_settings(self):
        """Load settings from settings.json"""
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading settings: {e}")
        
        # Default settings
        default_settings = {
            'export_path': str(Path.home() / 'Downloads'),
            'ai_provider': 'OpenAI',
            'ai_api_key': '',
            'log_level': 'INFO',
            'window_geometry': '1200x800+100+100'  # Default window size and position
        }
        self.save_settings(default_settings)
        return default_settings
        
    def save_settings(self, settings=None):
        """Save settings to settings.json"""
        if settings is None:
            settings = self.settings
        try:
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
            
    def apply_log_level(self):
        """Apply log level from settings"""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        log_level = self.settings.get('log_level', 'INFO')
        if log_level in level_map:
            self.logger.setLevel(level_map[log_level])
            self.log_handler.setLevel(level_map[log_level])
            
    def auto_size_window(self, window, min_width=800, min_height=600, show_window=True):
        """Automatically size window to fit content with minimum dimensions"""
        window.update_idletasks()  # Ensure all widgets are rendered
        
        # Get screen dimensions
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        
        # Calculate required size based on content
        req_width = max(min_width, window.winfo_reqwidth() + 50)  # Add padding
        req_height = max(min_height, window.winfo_reqheight() + 100)  # Add padding
        
        # Limit to 90% of screen size
        max_width = int(screen_width * 0.9)
        max_height = int(screen_height * 0.9)
        
        final_width = min(req_width, max_width)
        final_height = min(req_height, max_height)
        
        # Center the window
        x = (screen_width - final_width) // 2
        y = (screen_height - final_height) // 2
        
        window.geometry(f"{final_width}x{final_height}+{x}+{y}")
        
        # Show the window if requested
        if show_window:
            window.deiconify()
        
        return final_width, final_height
            
    @contextmanager
    def get_db_connection(self):
        """Get database connection with proper context management"""
        conn = None
        try:
            conn = sqlite3.connect('prompt_mini.db', timeout=10.0, check_same_thread=False)
            conn.execute('PRAGMA foreign_keys = ON')
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()

    def init_database(self):
        """Initialize SQLite database with FTS5"""
        try:
            # Initialize the main connection for compatibility
            self.conn = sqlite3.connect('prompt_mini.db', check_same_thread=False)
            self.conn.execute('PRAGMA foreign_keys = ON')
            
            # Create main table - using same structure as database.py
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    Created DATETIME DEFAULT CURRENT_TIMESTAMP,
                    Modified DATETIME DEFAULT CURRENT_TIMESTAMP,
                    Purpose TEXT(255),
                    Prompt TEXT,
                    SessionURLs TEXT,
                    Tags TEXT,
                    Note TEXT
                )
            ''')
            
            # Drop existing FTS table and triggers if they exist with wrong column names
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_after_insert')
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_after_delete') 
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_after_update')
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_ai')
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_ad')
            self.conn.execute('DROP TRIGGER IF EXISTS prompts_au')
            self.conn.execute('DROP TABLE IF EXISTS prompts_fts')
            
            # Create FTS5 virtual table with correct column names
            self.conn.execute('''
                CREATE VIRTUAL TABLE prompts_fts USING fts5(
                    Purpose, Prompt, SessionURLs, Tags, Note,
                    content='prompts',
                    content_rowid='id'
                )
            ''')
            
            # Create triggers to maintain FTS5 index
            self.conn.execute('''
                CREATE TRIGGER prompts_after_insert AFTER INSERT ON prompts BEGIN
                    INSERT INTO prompts_fts(rowid, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES (new.id, new.Purpose, new.Prompt, new.SessionURLs, new.Tags, new.Note);
                END
            ''')
            
            self.conn.execute('''
                CREATE TRIGGER prompts_after_delete AFTER DELETE ON prompts BEGIN
                    INSERT INTO prompts_fts(prompts_fts, rowid, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES ('delete', old.id, old.Purpose, old.Prompt, old.SessionURLs, old.Tags, old.Note);
                END
            ''')
            
            self.conn.execute('''
                CREATE TRIGGER prompts_after_update AFTER UPDATE ON prompts BEGIN
                    INSERT INTO prompts_fts(prompts_fts, rowid, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES ('delete', old.id, old.Purpose, old.Prompt, old.SessionURLs, old.Tags, old.Note);
                    INSERT INTO prompts_fts(rowid, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES (new.id, new.Purpose, new.Prompt, new.SessionURLs, new.Tags, new.Note);
                END
            ''')
            
            # Rebuild FTS index for existing data
            self.conn.execute('INSERT INTO prompts_fts(prompts_fts) VALUES("rebuild")')
            
            self.conn.commit()
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Database initialization error: {e}")
            messagebox.showerror("Database Error", f"Failed to initialize database: {e}")    
        
    def create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        
        file_menu.add_command(label="Export Location", command=self.set_export_location)
        file_menu.add_separator()
        
        # Export View submenu
        export_view_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Export View", menu=export_view_menu)
        export_view_menu.add_command(label="CSV", command=lambda: self.export_view('csv'))
        export_view_menu.add_command(label="PDF", command=lambda: self.export_view('pdf'))
        export_view_menu.add_command(label="TXT", command=lambda: self.export_view('txt'))
        export_view_menu.add_command(label="DOCX", command=lambda: self.export_view('docx'))
        
        # Export All submenu
        export_all_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Export All", menu=export_all_menu)
        export_all_menu.add_command(label="CSV", command=lambda: self.export_all('csv'))
        export_all_menu.add_command(label="PDF", command=lambda: self.export_all('pdf'))
        export_all_menu.add_command(label="TXT", command=lambda: self.export_all('txt'))
        export_all_menu.add_command(label="DOCX", command=lambda: self.export_all('docx'))
        
        file_menu.add_separator()
        file_menu.add_command(label="Backup", command=self.backup_database)
        file_menu.add_command(label="Restore", command=self.restore_database)
        file_menu.add_command(label="Import", command=self.import_database)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Console Log", command=self.show_console_log)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="GitHub", command=lambda: webbrowser.open("https://github.com/matbanik/prompt_mini"))
        
    def create_main_ui(self):
        """Create main user interface"""
        # Search section
        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Help button
        help_btn = ttk.Button(search_frame, text="?", width=3, command=self.show_search_help)
        help_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Search entry
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.on_search_change)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=80)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Search button
        search_btn = ttk.Button(search_frame, text="Search", command=self.perform_search)
        search_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Main content area with resizable panels
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Create PanedWindow for resizable split with better configuration
        try:
            # Try with sashwidth (newer Tkinter versions)
            self.paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL, sashwidth=8, sashrelief=tk.RAISED)
        except tk.TclError:
            # Fallback for older Tkinter versions
            self.paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True)
        
        # Left panel (70%) - Search View (increased to show Tags column fully)
        left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(left_frame, weight=7)  # 70% weight
        
        # Treeview for search results
        columns = ('ID', 'Created', 'Modified', 'Purpose', 'Tags')
        self.tree = ttk.Treeview(left_frame, columns=columns, show='headings', selectmode='extended')
        
        # Configure columns with sorting
        self.tree.heading('ID', text='ID', command=lambda: self.sort_by_column('ID'))
        self.tree.heading('Created', text='Created', command=lambda: self.sort_by_column('Created'))
        self.tree.heading('Modified', text='Modified', command=lambda: self.sort_by_column('Modified'))
        self.tree.heading('Purpose', text='Purpose', command=lambda: self.sort_by_column('Purpose'))
        self.tree.heading('Tags', text='Tags', command=lambda: self.sort_by_column('Tags'))
        
        # Configure columns with better sizing - ensure Tags is fully visible
        self.tree.column('ID', width=40, minwidth=30, stretch=False)
        self.tree.column('Created', width=120, minwidth=100, stretch=False)
        self.tree.column('Modified', width=120, minwidth=100, stretch=False)
        self.tree.column('Purpose', width=200, minwidth=120)  # Increased to give more space
        self.tree.column('Tags', width=150, minwidth=100)  # Increased to ensure full visibility
        
        # Scrollbar for treeview
        tree_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind events
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        self.tree.bind('<Double-1>', self.on_tree_double_click)
        self.tree.bind('<Motion>', self.on_tree_motion)
        self.tree.bind('<Leave>', self.on_tree_leave)
        
        # Add global undo/redo support
        self.root.bind('<Control-z>', self.undo_text)
        self.root.bind('<Control-y>', self.redo_text)
        
        # Tooltip for treeview
        self.tooltip = None
        
        # Right panel (30%) - Item Display (reduced to give more space to left panel)
        right_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(right_frame, weight=3)  # 30% weight
        
        # Action buttons - reorganized for better UX
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Primary action first - New Prompt
        self.new_btn = ttk.Button(btn_frame, text="New Prompt", command=self.new_item)
        self.new_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Group related actions: Duplicate, Change
        self.duplicate_btn = ttk.Button(btn_frame, text="Duplicate", command=self.duplicate_item)
        self.duplicate_btn.pack(side=tk.LEFT, padx=5)
        
        self.change_btn = ttk.Button(btn_frame, text="Change", command=self.change_item)
        self.change_btn.pack(side=tk.LEFT, padx=5)
        
        # Isolate destructive action - Delete with more padding
        self.delete_btn = ttk.Button(btn_frame, text="Delete", command=self.delete_items)
        self.delete_btn.pack(side=tk.LEFT, padx=(20, 0))  # More padding to isolate
        
        # Item display area
        display_frame = ttk.Frame(right_frame)
        display_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create item display widgets
        self.create_item_display(display_frame)
        
        # Status bar at bottom
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)
        
    def update_status_bar(self, message):
        """Update status bar with a message"""
        if hasattr(self, 'status_bar'):
            self.status_bar.config(text=message)
            # Clear the message after 5 seconds
            self.root.after(5000, lambda: self.status_bar.config(text="Ready"))
            
    def sync_scroll(self, scrollbar, line_numbers, *args):
        """Synchronize scrolling between main text and line numbers"""
        # Update the scrollbar
        scrollbar.set(*args)
        
        # Sync line numbers scrolling
        if len(args) >= 2:
            # Get the scroll position (top fraction)
            top = float(args[0])
            # Scroll line numbers to match
            line_numbers.yview_moveto(top)
            
    def sync_scroll_command(self, main_text, line_numbers, *args):
        """Handle scrollbar commands and sync both text widgets"""
        # Apply scroll to main text
        main_text.yview(*args)
        # Apply same scroll to line numbers
        line_numbers.yview(*args)
        
    def create_item_display(self, parent):
        """Create item display widgets"""
        # Date line
        date_frame = ttk.Frame(parent)
        date_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.created_label = ttk.Label(date_frame, text="Created: ", foreground="green")
        self.created_label.pack(side=tk.LEFT)
        
        self.modified_label = ttk.Label(date_frame, text="Modified: ", foreground="blue")
        self.modified_label.pack(side=tk.RIGHT)
        
        # Purpose line
        purpose_frame = ttk.Frame(parent)
        purpose_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(purpose_frame, text="Purpose:").pack(side=tk.LEFT)
        self.purpose_display = ttk.Label(purpose_frame, text="", font=('TkDefaultFont', 9, 'bold'))
        self.purpose_display.pack(side=tk.LEFT, padx=(5, 0))
        
        # Prompt text area with line numbers
        prompt_frame = ttk.Frame(parent)
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Line numbers frame
        line_frame = ttk.Frame(prompt_frame)
        line_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        self.line_numbers = tk.Text(line_frame, width=4, padx=3, takefocus=0,
                                   border=0, state='disabled', wrap='none')
        self.line_numbers.pack(fill=tk.Y, expand=True)
        
        # Prompt text with custom scrollbar
        text_frame = ttk.Frame(prompt_frame)
        text_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.prompt_display = tk.Text(text_frame, wrap=tk.WORD, state='disabled', undo=True, maxundo=50)
        prompt_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        
        # Configure synchronized scrolling
        self.prompt_display.config(yscrollcommand=lambda *args: self.sync_scroll(prompt_scrollbar, self.line_numbers, *args))
        prompt_scrollbar.config(command=lambda *args: self.sync_scroll_command(self.prompt_display, self.line_numbers, *args))
        
        self.prompt_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prompt_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Status bar
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.status_label = ttk.Label(status_frame, text="Char: 0 | Word: 0 | Sentence: 0 | Line: 0 | Tokens: 0")
        self.status_label.pack(side=tk.LEFT)
        
        # Consolidated controls - only Copy and Tune with AI below prompt text
        copy_btn = ttk.Button(status_frame, text="Copy", command=self.copy_to_clipboard)
        copy_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        tune_btn = ttk.Button(status_frame, text="Tune with AI", command=self.tune_with_ai)
        tune_btn.pack(side=tk.RIGHT)
        
        # Session URLs - cleaner design
        urls_label = ttk.Label(parent, text="Session URLs", font=('TkDefaultFont', 9, 'bold'))
        urls_label.pack(anchor=tk.W, pady=(0, 2))
        
        self.urls_display = scrolledtext.ScrolledText(parent, height=7, state='disabled', undo=True, maxundo=50)  # Increased by 4 lines
        self.urls_display.pack(fill=tk.X, pady=(0, 5))
        
        # Tags - cleaner design
        tags_label = ttk.Label(parent, text="Tags", font=('TkDefaultFont', 9, 'bold'))
        tags_label.pack(anchor=tk.W, pady=(0, 2))
        
        self.tags_display = ttk.Frame(parent)
        self.tags_display.pack(fill=tk.X, pady=(0, 5))
        
        # Note - cleaner design
        note_label = ttk.Label(parent, text="Note", font=('TkDefaultFont', 9, 'bold'))
        note_label.pack(anchor=tk.W, pady=(0, 2))
        
        self.note_display = scrolledtext.ScrolledText(parent, height=0, state='disabled', undo=True, maxundo=50)  # Reduced by 7 lines (from 7 to 0, will auto-size)
        self.note_display.pack(fill=tk.BOTH, expand=True, pady=(0, 5))       
 
    def on_search_change(self, *args):
        """Handle search input changes with improved debounce"""
        if hasattr(self, 'search_debounce_timer') and self.search_debounce_timer:
            self.root.after_cancel(self.search_debounce_timer)
        
        # Configurable debounce delay
        delay = 300  # milliseconds
        self.search_debounce_timer = self.root.after(delay, self.perform_search)
        
    def perform_search(self):
        """Perform search using FTS5 with threading optimization"""
        search_term = self.search_var.get().strip()
        
        # Show loading indicator
        if hasattr(self, 'status_bar'):
            self.status_bar.config(text="Searching...")
            self.root.config(cursor="wait")
            self.root.update_idletasks()
        
        def search_worker():
            try:
                with self.get_db_connection() as conn:
                    if search_term:
                        # Use FTS5 search
                        cursor = conn.execute('''
                            SELECT p.id, p.Created, p.Modified, p.Purpose, p.Prompt, p.SessionURLs, p.Tags, p.Note
                            FROM prompts p
                            JOIN prompts_fts fts ON p.id = fts.rowid
                            WHERE prompts_fts MATCH ?
                            ORDER BY p.Modified DESC
                        ''', (search_term,))
                    else:
                        # Show all records
                        cursor = conn.execute('''
                            SELECT id, Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                            FROM prompts
                            ORDER BY Modified DESC
                        ''')
                    
                    results = cursor.fetchall()
                
                # Update UI on main thread
                self.root.after(0, lambda r=results: self._handle_search_results(r, None))
                
            except Exception as e:
                self.logger.error(f"Search error: {e}")
                self.root.after(0, lambda err=e: self._handle_search_results([], err))
        
        # Run search in background thread for better UI responsiveness
        thread = threading.Thread(target=search_worker, daemon=True)
        thread.start()
    
    def _handle_search_results(self, results, error):
        """Handle search results on main thread"""
        # Hide loading indicator
        if hasattr(self, 'status_bar'):
            self.status_bar.config(text="Ready")
            self.root.config(cursor="")
        
        if error:
            messagebox.showerror("Search Error", f"Search failed: {error}")
            return
        
        self.search_results = results
        self.refresh_search_view()
            
    def sort_by_column(self, column):
        """Sort the treeview by the specified column"""
        # Cycle through sort states: None -> asc -> desc -> None
        if self.sort_column == column:
            if self.sort_direction is None:
                self.sort_direction = 'asc'
            elif self.sort_direction == 'asc':
                self.sort_direction = 'desc'
            else:
                self.sort_direction = None
                self.sort_column = None
        else:
            self.sort_column = column
            self.sort_direction = 'asc'
        
        # Update column headers with sort indicators
        self.update_column_headers()
        
        # Refresh the view with sorting applied
        self.refresh_search_view()
        
    def update_column_headers(self):
        """Update column headers with sort direction indicators"""
        columns = ['ID', 'Created', 'Modified', 'Purpose', 'Tags']
        
        for col in columns:
            if col == self.sort_column:
                if self.sort_direction == 'asc':
                    text = f"{col} ↑"
                elif self.sort_direction == 'desc':
                    text = f"{col} ↓"
                else:
                    text = col
            else:
                text = col
            self.tree.heading(col, text=text)
    
    def refresh_search_view(self):
        """Refresh the search results view"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Sort search results if needed
        display_results = self.search_results.copy() if hasattr(self, 'search_results') else []
        
        if self.sort_column and self.sort_direction and display_results:
            # Map column names to data indices
            column_map = {
                'ID': 0,
                'Created': 1,
                'Modified': 2,
                'Purpose': 3,
                'Tags': 6  # Tags are at index 6 in the database row
            }
            
            if self.sort_column in column_map:
                col_index = column_map[self.sort_column]
                reverse = (self.sort_direction == 'desc')
                
                # Special handling for different data types
                if self.sort_column == 'ID':
                    # Sort by integer ID
                    display_results.sort(key=lambda x: int(x[col_index]) if x[col_index] else 0, reverse=reverse)
                elif self.sort_column in ['Created', 'Modified']:
                    # Sort by datetime
                    display_results.sort(key=lambda x: x[col_index] if x[col_index] else '', reverse=reverse)
                else:
                    # Sort by string (Purpose, Tags)
                    display_results.sort(key=lambda x: (x[col_index] or '').lower(), reverse=reverse)
            
        # Add search results
        if display_results:
            for row in display_results:
                item_id, created, modified, purpose, prompt, session_urls, tags, note = row
                created_str = self.format_datetime(created)
                modified_str = self.format_datetime(modified)
                purpose_display = purpose[:50] + "..." if purpose and len(purpose) > 50 else purpose or ""
                
                # Format tags for display
                tags_display = ""
                if tags:
                    try:
                        tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                        tags_display = ', '.join([tag.strip() for tag in tag_list[:3]])  # Show first 3 tags
                        if len(tag_list) > 3:
                            tags_display += "..."
                    except:
                        tags_display = tags[:30] + "..." if len(tags) > 30 else tags
                
                self.tree.insert('', 'end', values=(item_id, created_str, modified_str, purpose_display, tags_display))
                
    def format_datetime(self, dt_str):
        """Format datetime string for display"""
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return dt.strftime('%m-%d-%Y %I:%M%p')
        except:
            return dt_str
            
    def on_tree_select(self, event):
        """Handle tree selection"""
        selection = self.tree.selection()
        self.selected_items = [self.tree.item(item)['values'][0] for item in selection]
        
        # Update button states
        if len(self.selected_items) == 1:
            self.current_item = self.selected_items[0]
            self.update_item_display()
            if not self.editing_mode:
                self.delete_btn.config(text="Delete")
                self.duplicate_btn.config(state='normal')
                self.change_btn.config(state='normal')
        elif len(self.selected_items) > 1:
            if not self.editing_mode:
                self.delete_btn.config(text=f"Delete ({len(self.selected_items)})")
                self.duplicate_btn.config(state='disabled')
                self.change_btn.config(state='disabled')
            self.clear_item_display()
        else:
            if not self.editing_mode:
                self.delete_btn.config(text="Delete")
                self.duplicate_btn.config(state='disabled')
                self.change_btn.config(state='disabled')
            self.clear_item_display()
            
    def on_tree_double_click(self, event):
        """Handle double-click on tree item"""
        if self.current_item:
            self.change_item()
            
    def on_tree_motion(self, event):
        """Handle mouse motion over treeview for tooltips"""
        # Get the item under the cursor
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        
        if item and column:
            # Get column index (column is like '#1', '#2', etc.)
            col_index = int(column[1:]) - 1
            column_names = ['ID', 'Created', 'Modified', 'Purpose', 'Tags']
            
            if col_index < len(column_names):
                col_name = column_names[col_index]
                
                # Show tooltip for Purpose and Tags columns
                if col_name in ['Purpose', 'Tags']:
                    # Get the full text from search results
                    item_values = self.tree.item(item)['values']
                    if item_values and col_index < len(item_values):
                        display_text = item_values[col_index]
                        
                        # Get the full text from search results
                        full_text = self.get_full_text_for_tooltip(item, col_name)
                        
                        # Show tooltip if text is truncated
                        if full_text and len(full_text) > len(display_text):
                            self.show_tooltip(event.x_root, event.y_root, full_text)
                        else:
                            self.hide_tooltip()
                    else:
                        self.hide_tooltip()
                else:
                    self.hide_tooltip()
            else:
                self.hide_tooltip()
        else:
            self.hide_tooltip()
            
    def on_tree_leave(self, event):
        """Handle mouse leaving treeview"""
        self.hide_tooltip()
        
    def get_full_text_for_tooltip(self, item, column_name):
        """Get full text for tooltip from search results"""
        try:
            item_values = self.tree.item(item)['values']
            if not item_values:
                return ""
                
            item_id = item_values[0]  # ID is first column
            
            # Find the item in search results
            if hasattr(self, 'search_results'):
                for row in self.search_results:
                    if str(row[0]) == str(item_id):  # Compare IDs
                        if column_name == 'Purpose':
                            return row[3] or ""  # Purpose is at index 3
                        elif column_name == 'Tags':
                            return row[6] or ""  # Tags is at index 6
            return ""
        except Exception as e:
            self.logger.error(f"Error getting tooltip text: {e}")
            return ""
            
    def show_tooltip(self, x, y, text):
        """Show tooltip window"""
        if self.tooltip:
            self.tooltip.destroy()
            
        self.tooltip = tk.Toplevel(self.root)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x+10}+{y+10}")
        
        # Create tooltip content
        frame = ttk.Frame(self.tooltip, relief=tk.SOLID, borderwidth=1)
        frame.pack()
        
        label = ttk.Label(frame, text=text, background="lightyellow", 
                         foreground="black", wraplength=300, justify=tk.LEFT)
        label.pack(padx=5, pady=5)
        
    def hide_tooltip(self):
        """Hide tooltip window"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
            
    def undo_text(self, event):
        """Handle Ctrl+Z for undo"""
        # Find the focused text widget
        focused = self.root.focus_get()
        if isinstance(focused, tk.Text):
            try:
                focused.edit_undo()
            except tk.TclError:
                pass  # No undo available
        return "break"
        
    def redo_text(self, event):
        """Handle Ctrl+Y for redo"""
        # Find the focused text widget
        focused = self.root.focus_get()
        if isinstance(focused, tk.Text):
            try:
                focused.edit_redo()
            except tk.TclError:
                pass  # No redo available
        return "break"
            
    def update_item_display(self, force_refresh=False):
        """Update the item display panel with caching optimization"""
        if not self.current_item:
            return
        
        try:
            # Check cache first (unless force refresh is requested)
            if not force_refresh and self.current_item in self.prompt_cache:
                row = self.prompt_cache[self.current_item]
                self.logger.debug(f"Using cached data for item {self.current_item}")
            else:
                # Fetch fresh data from database
                with self.get_db_connection() as conn:
                    cursor = conn.execute('''
                        SELECT Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                        FROM prompts WHERE id = ?
                    ''', (self.current_item,))
                    
                    row = cursor.fetchone()
                    if not row:
                        return
                    
                    # Cache the result (limit cache size)
                    if len(self.prompt_cache) > 50:  # Simple cache size limit
                        # Remove oldest entry
                        oldest_key = next(iter(self.prompt_cache))
                        del self.prompt_cache[oldest_key]
                    
                    self.prompt_cache[self.current_item] = row
                    self.logger.debug(f"Fetched and cached fresh data for item {self.current_item}")
                    
            created, modified, purpose, prompt, session_urls, tags, note = row
            
            # Update date labels
            self.created_label.config(text=f"Created: {self.format_datetime(created)}")
            self.modified_label.config(text=f"Modified: {self.format_datetime(modified)}")
            
            # Update purpose
            self.purpose_display.config(text=purpose or "")
            
            # Update prompt text
            self.prompt_display.config(state='normal')
            self.prompt_display.delete(1.0, tk.END)
            if prompt:
                self.prompt_display.insert(1.0, prompt)
            self.prompt_display.config(state='disabled')
            
            # Update line numbers
            self.update_line_numbers(prompt or "")
            
            # Update status
            self.update_status(prompt or "")
            
            # Update URLs
            self.urls_display.config(state='normal')
            self.urls_display.delete(1.0, tk.END)
            if session_urls:
                self.urls_display.insert(1.0, session_urls)
                # Make URLs clickable
                self.make_urls_clickable()
            self.urls_display.config(state='disabled')
                    
            # Update tags
            self.update_tags_display(tags)
            
            # Update note
            self.note_display.config(state='normal')
            self.note_display.delete(1.0, tk.END)
            if note:
                self.note_display.insert(1.0, note)
            self.note_display.config(state='disabled')
            
        except Exception as e:
            self.logger.error(f"Error updating item display: {e}")
            
    def clear_item_display(self):
        """Clear the item display panel"""
        self.created_label.config(text="Created: ")
        self.modified_label.config(text="Modified: ")
        self.purpose_display.config(text="")
        
        self.prompt_display.config(state='normal')
        self.prompt_display.delete(1.0, tk.END)
        self.prompt_display.config(state='disabled')
        
        self.line_numbers.config(state='normal')
        self.line_numbers.delete(1.0, tk.END)
        self.line_numbers.config(state='disabled')
        
        self.status_label.config(text="Char: 0 | Word: 0 | Sentence: 0 | Line: 0 | Tokens: 0")
        
        self.urls_display.config(state='normal')
        self.urls_display.delete(1.0, tk.END)
        self.urls_display.config(state='disabled')
        
        for widget in self.tags_display.winfo_children():
            widget.destroy()
            
        self.note_display.config(state='normal')
        self.note_display.delete(1.0, tk.END)
        self.note_display.config(state='disabled')
        
    def update_line_numbers(self, text):
        """Update line numbers for text display"""
        self.line_numbers.config(state='normal')
        self.line_numbers.delete(1.0, tk.END)
        
        lines = text.split('\n')
        line_nums = '\n'.join(str(i+1) for i in range(len(lines)))
        self.line_numbers.insert(1.0, line_nums)
        
        self.line_numbers.config(state='disabled')
        
    def update_status(self, text):
        """Update status bar with text statistics"""
        char_count = len(text)
        word_count = len(text.split()) if text else 0
        sentence_count = len(re.findall(r'[.!?]+', text)) if text else 0
        line_count = len(text.split('\n')) if text else 0
        token_count = int(word_count * 1.3)  # Rough token estimate
        
        self.status_label.config(text=f"Char: {char_count} | Word: {word_count} | Sentence: {sentence_count} | Line: {line_count} | Tokens: {token_count}")
        
    def update_tags_display(self, tags_str):
        """Update tags display with clickable buttons"""
        # Clear existing tags
        for widget in self.tags_display.winfo_children():
            widget.destroy()
            
        if tags_str:
            try:
                tags = json.loads(tags_str) if tags_str.startswith('[') else tags_str.split(',')
                for tag in tags:
                    tag = tag.strip()
                    if tag:
                        btn = ttk.Button(self.tags_display, text=tag, 
                                       command=lambda t=tag: self.search_by_tag(t))
                        btn.pack(side=tk.LEFT, padx=2, pady=2)
            except:
                pass
                
    def search_by_tag(self, tag):
        """Search by clicking a tag"""
        self.search_var.set(tag)
        self.perform_search()
        
    def copy_to_clipboard(self):
        """Copy prompt text to clipboard"""
        if self.current_item:
            try:
                cursor = self.conn.execute('SELECT Prompt FROM prompts WHERE id = ?', (self.current_item,))
                row = cursor.fetchone()
                if row and row[0]:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(row[0])
                    self.update_status_bar("Prompt text copied to clipboard")
            except Exception as e:
                self.logger.error(f"Copy error: {e}")
                self.update_status_bar(f"Copy failed: {e}")
                
    def make_urls_clickable(self):
        """Make URLs in the text widget clickable"""
        content = self.urls_display.get(1.0, tk.END)
        url_pattern = r'https?://[^\s\n]+'
        
        # Clear existing tags
        self.urls_display.tag_delete("url")
        
        # Find and tag URLs - handle multiline content properly
        import re
        lines = content.split('\n')
        for line_num, line in enumerate(lines):
            for match in re.finditer(url_pattern, line):
                start_idx = f"{line_num + 1}.{match.start()}"
                end_idx = f"{line_num + 1}.{match.end()}"
                tag_name = f"url_{line_num}_{match.start()}"
                self.urls_display.tag_add(tag_name, start_idx, end_idx)
                
                # Configure each URL tag individually
                self.urls_display.tag_config(tag_name, foreground="blue", underline=True)
                
                # Bind events for each URL tag
                self.urls_display.tag_bind(tag_name, "<Enter>", lambda e: self.urls_display.config(cursor="hand2"))
                self.urls_display.tag_bind(tag_name, "<Leave>", lambda e: self.urls_display.config(cursor=""))
                self.urls_display.tag_bind(tag_name, "<Button-1>", lambda e, url=match.group(): webbrowser.open(url))
        
    def on_url_click(self, event):
        """Handle URL clicks - now handled by individual tag bindings in make_urls_clickable"""
        pass   
         
    def show_search_help(self):
        """Show search help dialog"""
        help_text = """Search Tips:

• Use simple keywords to search all fields
• Use quotes for exact phrases: "machine learning"
• Use AND/OR operators: python AND tutorial
• Use wildcards: machine* (matches machine, machines, etc.)
• Search specific fields with FTS5 syntax
• Leave empty to show all records

Examples:
- python
- "data science"
- machine AND learning
- web* OR mobile*
"""
        messagebox.showinfo("Search Help", help_text)
        
    def new_item(self):
        """Create new prompt item"""
        self.open_prompt_window('new')
        
    def duplicate_item(self):
        """Duplicate selected item"""
        if self.current_item:
            self.open_prompt_window('duplicate', self.current_item)
            
    def change_item(self):
        """Change selected item - now uses in-place editing"""
        if self.current_item and not self.editing_mode:
            self.enter_editing_mode()
            
    def delete_items(self):
        """Delete selected items"""
        if not self.selected_items:
            return
            
        count = len(self.selected_items)
        if messagebox.askyesno("Confirm Delete", f"Delete {count} item(s)?"):
            try:
                for item_id in self.selected_items:
                    self.conn.execute('DELETE FROM prompts WHERE id = ?', (item_id,))
                    # CRITICAL FIX: Clear cache for deleted items
                    self.clear_prompt_cache(item_id)
                    
                self.conn.commit()
                self.perform_search()
                
                # Clear the item display if we deleted the currently selected item
                if self.current_item in self.selected_items:
                    self.current_item = None
                    self.clear_item_display()
                
                self.logger.info(f"Deleted {count} items")
            except Exception as e:
                self.logger.error(f"Delete error: {e}")
                messagebox.showerror("Delete Error", f"Failed to delete: {e}")
                
    def tune_with_ai(self):
        """Open AI tuning window"""
        if self.current_item:
            self.open_ai_tuning_window(self.current_item)
            
    def enter_editing_mode(self):
        """Enter in-place editing mode"""
        if not self.current_item or self.editing_mode:
            return
            
        try:
            # Get current data
            with self.get_db_connection() as conn:
                cursor = conn.execute('''
                    SELECT Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                    FROM prompts WHERE id = ?
                ''', (self.current_item,))
                row = cursor.fetchone()
                if not row:
                    return
                    
            created, modified, purpose, prompt, session_urls, tags, note = row
            
            # Make text widgets editable
            self.prompt_display.config(state='normal')
            self.urls_display.config(state='normal')
            self.note_display.config(state='normal')
            
            # Replace tags buttons with editable entry
            for widget in self.tags_display.winfo_children():
                widget.destroy()
            
            self.tags_entry = ttk.Entry(self.tags_display)
            self.tags_entry.pack(fill=tk.X, pady=(0, 5))
            
            # Populate with current tags
            if tags:
                try:
                    tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                    self.tags_entry.insert(0, ', '.join(tag_list))
                except:
                    self.tags_entry.insert(0, tags)
            
            # Replace action buttons with Save/Cancel
            self.replace_action_buttons()
            
            # Set editing mode
            self.editing_mode = True
            
        except Exception as e:
            self.logger.error(f"Error entering editing mode: {e}")
            messagebox.showerror("Edit Error", f"Failed to enter editing mode: {e}")
            
    def replace_action_buttons(self):
        """Replace action buttons with Save/Cancel during editing"""
        # Destroy existing buttons
        for widget in self.new_btn.master.winfo_children():
            if isinstance(widget, ttk.Button):
                widget.destroy()
                
        # Create Save and Cancel buttons
        self.save_btn = ttk.Button(self.new_btn.master, text="Save", command=self.save_edits)
        self.save_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.cancel_btn = ttk.Button(self.new_btn.master, text="Cancel", command=self.cancel_edits)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        
    def save_edits(self):
        """Save edits and exit editing mode"""
        try:
            # Get edited values from current widgets
            purpose = self.purpose_display.cget('text')  # Purpose is a label, not editable in this simplified version
            prompt = self.prompt_display.get(1.0, tk.END).strip()
            session_urls = self.urls_display.get(1.0, tk.END).strip()
            
            # Get tags from the tags entry field
            tags = self.tags_entry.get() if hasattr(self, 'tags_entry') else ""
            
            note = self.note_display.get(1.0, tk.END).strip()
            
            # Process tags
            if tags:
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
                tags_json = json.dumps(tag_list)
            else:
                tags_json = None
                
            # Update database
            now = datetime.now().isoformat()
            with self.get_db_connection() as conn:
                conn.execute('''
                    UPDATE prompts 
                    SET Modified = ?, Purpose = ?, Prompt = ?, SessionURLs = ?, Tags = ?, Note = ?
                    WHERE id = ?
                ''', (now, purpose, prompt, session_urls, tags_json, note, self.current_item))
                conn.commit()
                
            # Clear cache for updated item
            if hasattr(self, 'prompt_cache') and self.current_item in self.prompt_cache:
                del self.prompt_cache[self.current_item]
                
            # Exit editing mode
            self.exit_editing_mode()
            
            # Refresh display
            self.update_item_display(force_refresh=True)
            self.perform_search()
            
            self.logger.info(f"Saved edits for item {self.current_item}")
            
        except Exception as e:
            self.logger.error(f"Error saving edits: {e}")
            messagebox.showerror("Save Error", f"Failed to save edits: {e}")
            
    def cancel_edits(self):
        """Cancel edits and exit editing mode"""
        self.exit_editing_mode()
        self.update_item_display(force_refresh=True)
        
    def exit_editing_mode(self):
        """Exit editing mode and restore original widgets"""
        if not self.editing_mode:
            return
            
        try:
            # Make text widgets read-only again
            self.prompt_display.config(state='disabled')
            self.urls_display.config(state='disabled')
            self.note_display.config(state='disabled')
            
            # Restore tags display (destroy entry and recreate buttons)
            if hasattr(self, 'tags_entry'):
                self.tags_entry.destroy()
                delattr(self, 'tags_entry')
            
            # Restore action buttons
            self.restore_action_buttons()
            
            # Clear editing state
            self.editing_mode = False
            
        except Exception as e:
            self.logger.error(f"Error exiting editing mode: {e}")
            
    def restore_action_buttons(self):
        """Restore original action buttons"""
        # Destroy current buttons
        for widget in self.save_btn.master.winfo_children():
            if isinstance(widget, ttk.Button):
                widget.destroy()
                
        # Recreate original buttons
        self.new_btn = ttk.Button(self.save_btn.master, text="New Prompt", command=self.new_item)
        self.new_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.duplicate_btn = ttk.Button(self.save_btn.master, text="Duplicate", command=self.duplicate_item)
        self.duplicate_btn.pack(side=tk.LEFT, padx=5)
        
        self.change_btn = ttk.Button(self.save_btn.master, text="Change", command=self.change_item)
        self.change_btn.pack(side=tk.LEFT, padx=5)
        
        self.delete_btn = ttk.Button(self.save_btn.master, text="Delete", command=self.delete_items)
        self.delete_btn.pack(side=tk.LEFT, padx=(20, 0))
            
    def open_prompt_window(self, mode, item_id=None):
        """Open prompt editing window"""
        window = tk.Toplevel(self.root)
        window.title(f"{mode.title()} Prompt")
        window.transient(self.root)
        window.grab_set()
        window.withdraw()  # Hide window initially
        
        # Load existing data if needed
        data = None
        if item_id and mode in ['duplicate', 'change']:
            cursor = self.conn.execute('''
                SELECT Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                FROM prompts WHERE id = ?
            ''', (item_id,))
            data = cursor.fetchone()
            
        # Create form
        self.create_prompt_form(window, mode, item_id, data)
        
        # Auto-size window after content is created and show it
        self.root.after(10, lambda: self.auto_size_window(window, 1000, 900, True))
        
    def create_prompt_form(self, window, mode, item_id, data):
        """Create prompt editing form"""
        # Date line
        date_frame = ttk.Frame(window)
        date_frame.pack(fill=tk.X, padx=10, pady=5)
        
        now = datetime.now().strftime('%m-%d-%Y %I:%M%p')
        
        if mode == 'change' and data:
            created_text = f"Created: {self.format_datetime(data[0])}"
        else:
            created_text = f"Created: {now}"
            
        created_label = ttk.Label(date_frame, text=created_text, foreground="green")
        created_label.pack(side=tk.LEFT)
        
        modified_label = ttk.Label(date_frame, text=f"Modified: {now}", foreground="blue")
        modified_label.pack(side=tk.RIGHT)
        
        # Purpose field
        purpose_frame = ttk.Frame(window)
        purpose_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(purpose_frame, text="Purpose:").pack(side=tk.LEFT)
        purpose_var = tk.StringVar()
        if data and data[2]:
            purpose_var.set(data[2])
        purpose_entry = ttk.Entry(purpose_frame, textvariable=purpose_var, width=80)
        purpose_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Prompt text area
        prompt_frame = ttk.Frame(window)
        prompt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Line numbers
        line_frame = ttk.Frame(prompt_frame)
        line_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        line_numbers = tk.Text(line_frame, width=4, padx=3, takefocus=0,
                              border=0, state='disabled', wrap='none')
        line_numbers.pack(fill=tk.Y, expand=True)
        
        # Prompt text with custom scrollbar
        text_frame = ttk.Frame(prompt_frame)
        text_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        prompt_text = tk.Text(text_frame, wrap=tk.WORD)
        text_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        
        # Configure synchronized scrolling
        prompt_text.config(yscrollcommand=lambda *args: self.sync_scroll(text_scrollbar, line_numbers, *args))
        text_scrollbar.config(command=lambda *args: self.sync_scroll_command(prompt_text, line_numbers, *args))
        
        prompt_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        prompt_text.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        if data and data[3]:
            prompt_text.insert(1.0, data[3])
            
        # Status bar
        status_frame = ttk.Frame(window)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        status_label = ttk.Label(status_frame, text="Char: 0 | Word: 0 | Sentence: 0 | Line: 0 | Tokens: 0")
        status_label.pack(side=tk.LEFT)
        
        copy_btn = ttk.Button(status_frame, text="Copy", 
                             command=lambda: self.copy_text_to_clipboard(prompt_text.get(1.0, tk.END)))
        copy_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        tune_btn = ttk.Button(status_frame, text="Tune with AI", 
                             command=lambda: self.tune_text_with_ai(prompt_text))
        tune_btn.pack(side=tk.RIGHT)
        
        # Update status on text change
        def update_form_status(*args):
            text = prompt_text.get(1.0, tk.END)
            self.update_form_line_numbers(line_numbers, text)
            self.update_form_status_label(status_label, text)
            
        prompt_text.bind('<KeyRelease>', update_form_status)
        update_form_status()  # Initial update
        
        # Session URLs
        urls_frame = ttk.LabelFrame(window, text="Session URLs")
        urls_frame.pack(fill=tk.X, padx=10, pady=5)
        
        urls_text = scrolledtext.ScrolledText(urls_frame, height=3)
        urls_text.pack(fill=tk.X, padx=5, pady=5)
        
        # Load existing URLs
        if data and data[4]:
            urls_text.insert(1.0, data[4])
                
        # Tags
        tags_frame = ttk.LabelFrame(window, text="Tags")
        tags_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tags_var = tk.StringVar()
        if data and data[5]:
            try:
                tags = json.loads(data[5]) if data[5].startswith('[') else data[5].split(',')
                tags_var.set(', '.join(tags))
            except:
                tags_var.set(data[5])
                
        tags_entry = ttk.Entry(tags_frame, textvariable=tags_var)
        tags_entry.pack(fill=tk.X, padx=5, pady=5)
        
        # Tag suggestions
        if WORDCLOUD_AVAILABLE:
            suggestions_frame = ttk.Frame(tags_frame)
            suggestions_frame.pack(fill=tk.X, padx=5, pady=2)
            
            self.generate_tag_suggestions(suggestions_frame, tags_var, prompt_text)
            
        # Note
        note_frame = ttk.LabelFrame(window, text="Note")
        note_frame.pack(fill=tk.X, padx=10, pady=5)
        
        note_text = scrolledtext.ScrolledText(note_frame, height=7)
        note_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        if data and data[6]:
            note_text.insert(1.0, data[6])
            
        # Save button
        save_btn = ttk.Button(window, text="Save", 
                             command=lambda: self.save_prompt(window, mode, item_id, 
                                                            purpose_var.get(),
                                                            prompt_text.get(1.0, tk.END).strip(),
                                                            urls_text.get(1.0, tk.END).strip(),
                                                            tags_var.get(),
                                                            note_text.get(1.0, tk.END).strip()))
        save_btn.pack(pady=10)
        
    def update_form_line_numbers(self, line_numbers, text):
        """Update line numbers in form"""
        line_numbers.config(state='normal')
        line_numbers.delete(1.0, tk.END)
        
        lines = text.split('\n')
        line_nums = '\n'.join(str(i+1) for i in range(len(lines)))
        line_numbers.insert(1.0, line_nums)
        
        line_numbers.config(state='disabled')
        
    def update_form_status_label(self, status_label, text):
        """Update status label in form"""
        char_count = len(text)
        word_count = len(text.split()) if text else 0
        sentence_count = len(re.findall(r'[.!?]+', text)) if text else 0
        line_count = len(text.split('\n')) if text else 0
        token_count = int(word_count * 1.3)
        
        status_label.config(text=f"Char: {char_count} | Word: {word_count} | Sentence: {sentence_count} | Line: {line_count} | Tokens: {token_count}")
        
    def copy_text_to_clipboard(self, text):
        """Copy text to clipboard"""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.update_status_bar("Text copied to clipboard")
        
    def tune_text_with_ai(self, text_widget):
        """Tune text with AI from form"""
        text = text_widget.get(1.0, tk.END).strip()
        if text:
            self.open_ai_tuning_window_with_text(text, text_widget)
            
    def generate_tag_suggestions(self, parent, tags_var, prompt_text):
        """Generate tag suggestions using wordcloud"""
        if not WORDCLOUD_AVAILABLE:
            return
            
        def update_suggestions():
            try:
                text = prompt_text.get(1.0, tk.END).strip()
                if not text:
                    return
                    
                # Simple word frequency analysis
                words = re.findall(r'\b\w+\b', text.lower())
                word_freq = Counter(words)
                
                # Remove common words
                common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those'}
                filtered_freq = {word: freq for word, freq in word_freq.items() 
                               if word not in common_words and len(word) > 2}
                
                # Get top suggestions
                suggestions = sorted(filtered_freq.items(), key=lambda x: x[1], reverse=True)[:7]
                
                # Clear existing suggestions
                for widget in parent.winfo_children():
                    widget.destroy()
                    
                # Add suggestion buttons
                for word, freq in suggestions:
                    btn = ttk.Button(parent, text=word, 
                                   command=lambda w=word: self.add_tag_suggestion(tags_var, w))
                    btn.pack(side=tk.LEFT, padx=2, pady=2)
                    
            except Exception as e:
                self.logger.error(f"Tag suggestion error: {e}")
                
        # Update suggestions when prompt text changes
        prompt_text.bind('<KeyRelease>', lambda e: self.root.after(1000, update_suggestions))
        update_suggestions()  # Initial update
        
    def add_tag_suggestion(self, tags_var, word):
        """Add suggested tag to tags field"""
        current_tags = tags_var.get()
        if current_tags:
            tags_var.set(f"{current_tags}, {word}")
        else:
            tags_var.set(word)  
          

        
    def save_prompt(self, window, mode, item_id, purpose, prompt, session_urls, tags, note):
        """Save prompt to database"""
        try:
            now = datetime.now().isoformat()
            
            # Process tags
            if tags:
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
                tags_json = json.dumps(tag_list)
            else:
                tags_json = None
                
            if mode == 'new' or mode == 'duplicate':
                # Insert new record
                self.conn.execute('''
                    INSERT INTO prompts (Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (now, now, purpose, prompt, session_urls, tags_json, note))
            elif mode == 'change':
                # Update existing record
                self.conn.execute('''
                    UPDATE prompts 
                    SET Modified = ?, Purpose = ?, Prompt = ?, SessionURLs = ?, Tags = ?, Note = ?
                    WHERE id = ?
                ''', (now, purpose, prompt, session_urls, tags_json, note, item_id))
                
                # CRITICAL FIX: Invalidate cache for the updated item
                if hasattr(self, 'prompt_cache') and item_id in self.prompt_cache:
                    del self.prompt_cache[item_id]
                    self.logger.info(f"Cache invalidated for item {item_id}")
                
            self.conn.commit()
            window.destroy()
            
            # Refresh search results
            self.perform_search()
            
            # CRITICAL FIX: If we're editing the currently selected item, refresh the display
            if mode == 'change' and item_id == self.current_item:
                # Force refresh of the item display by calling update_item_display with force_refresh=True
                # This will fetch fresh data from the database and bypass the cache
                self.update_item_display(force_refresh=True)
                self.logger.info(f"Refreshed display for current item {item_id}")
            
            self.logger.info(f"Saved prompt ({mode})")
            
        except Exception as e:
            self.logger.error(f"Save error: {e}")
            messagebox.showerror("Save Error", f"Failed to save: {e}")
    
    def clear_prompt_cache(self, item_id=None):
        """Clear prompt cache for specific item or all items"""
        if not hasattr(self, 'prompt_cache'):
            return
            
        if item_id:
            # Clear specific item from cache
            if item_id in self.prompt_cache:
                del self.prompt_cache[item_id]
                self.logger.info(f"Cleared cache for item {item_id}")
        else:
            # Clear entire cache
            self.prompt_cache.clear()
            self.logger.info("Cleared entire prompt cache")
            
    def open_ai_tuning_window(self, item_id):
        """Open AI tuning window for existing item"""
        try:
            cursor = self.conn.execute('SELECT Prompt FROM prompts WHERE id = ?', (item_id,))
            row = cursor.fetchone()
            if row and row[0]:
                self.open_ai_tuning_window_with_text(row[0])
        except Exception as e:
            self.logger.error(f"AI tuning error: {e}")
            messagebox.showerror("AI Tuning Error", f"Failed to open AI tuning: {e}")
            
    def open_ai_tuning_window_with_text(self, text, target_widget=None):
        """Open AI tuning window with specific text"""
        window = tk.Toplevel(self.root)
        window.title("Tune with AI")
        window.transient(self.root)
        window.grab_set()
        window.withdraw()  # Hide window initially
        
        # AI Settings frame at top
        settings_frame = ttk.LabelFrame(window, text="AI Settings")
        settings_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # AI Provider selection
        provider_frame = ttk.Frame(settings_frame)
        provider_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(provider_frame, text="AI Provider:").pack(side=tk.LEFT)
        
        provider_var = tk.StringVar(value=self.settings.get('ai_provider', 'OpenAI'))
        provider_combo = ttk.Combobox(provider_frame, textvariable=provider_var, 
                                     values=list(AIManager._get_default_settings().keys()),
                                     state="readonly", width=15)
        provider_combo.pack(side=tk.LEFT, padx=(5, 10))
        
        # API Key
        ttk.Label(provider_frame, text="API Key:").pack(side=tk.LEFT)
        api_key_var = tk.StringVar(value=self.settings.get('ai_api_key', ''))
        api_key_entry = ttk.Entry(provider_frame, textvariable=api_key_var, show="*", width=20)
        api_key_entry.pack(side=tk.LEFT, padx=(5, 10))
        
        # Get API Key link
        get_key_btn = ttk.Button(provider_frame, text="Get API Key", 
                                command=lambda: self.open_api_key_url(provider_var.get()))
        get_key_btn.pack(side=tk.LEFT, padx=(5, 10))
        
        # Model selection
        ttk.Label(provider_frame, text="Model:").pack(side=tk.LEFT)
        model_var = tk.StringVar()
        model_combo = ttk.Combobox(provider_frame, textvariable=model_var, width=25)
        model_combo.pack(side=tk.LEFT, padx=(5, 5))
        
        edit_models_btn = ttk.Button(provider_frame, text="✏", width=3,
                                    command=lambda: self.edit_models(provider_var.get(), model_var))
        edit_models_btn.pack(side=tk.LEFT, padx=(5, 10))
        
        # Update model when provider changes
        def on_provider_change(*args):
            provider = provider_var.get()
            if provider in AIManager._get_default_settings():
                provider_defaults = AIManager._get_default_settings()[provider]
                
                # Use custom models if available, otherwise use defaults
                if 'custom_models' in self.settings and provider in self.settings['custom_models']:
                    custom_models = self.settings['custom_models'][provider]
                    model_combo['values'] = custom_models
                    default_model = custom_models[0] if custom_models else provider_defaults.get('MODEL', '')
                else:
                    # Use the MODELS_LIST from provider defaults, or fallback to single MODEL
                    models_list = provider_defaults.get('MODELS_LIST', [])
                    if not models_list:
                        models_list = [provider_defaults.get('MODEL', '')] if provider_defaults.get('MODEL') else []
                    model_combo['values'] = models_list
                    default_model = provider_defaults.get('MODEL', '')
                model_var.set(default_model)
                
        provider_var.trace('w', on_provider_change)
        on_provider_change()  # Initial update
        
        # Create two-panel view
        main_frame = ttk.Frame(window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Input panel (left side)
        input_frame = ttk.LabelFrame(main_frame, text="Input")
        input_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # Input line numbers
        input_line_frame = ttk.Frame(input_frame)
        input_line_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        input_line_numbers = tk.Text(input_line_frame, width=4, padx=3, takefocus=0,
                                    border=0, state='disabled', wrap='none')
        input_line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        
        # Input text with custom scrollbar
        input_text_frame = ttk.Frame(input_line_frame)
        input_text_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        input_text = tk.Text(input_text_frame, wrap=tk.WORD)
        input_scrollbar = ttk.Scrollbar(input_text_frame, orient=tk.VERTICAL)
        
        # Configure synchronized scrolling
        input_text.config(yscrollcommand=lambda *args: self.sync_scroll(input_scrollbar, input_line_numbers, *args))
        input_scrollbar.config(command=lambda *args: self.sync_scroll_command(input_text, input_line_numbers, *args))
        
        input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        input_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Set initial input text
        initial_input = f"Please help me improve this AI prompt:\n\n{text}"
        input_text.insert(1.0, initial_input)
        
        # Input status bar
        input_status_frame = ttk.Frame(input_frame)
        input_status_frame.pack(fill=tk.X, padx=5, pady=2)
        
        input_status_label = ttk.Label(input_status_frame, text="")
        input_status_label.pack(side=tk.LEFT)
        
        # Output panel (right side)
        output_frame = ttk.LabelFrame(main_frame, text="Output")
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Copy button for output
        output_btn_frame = ttk.Frame(output_frame)
        output_btn_frame.pack(fill=tk.X, padx=5, pady=2)
        
        copy_output_btn = ttk.Button(output_btn_frame, text="Copy to Clipboard", 
                                    command=lambda: self.copy_text_to_clipboard(output_text.get(1.0, tk.END)))
        copy_output_btn.pack(side=tk.LEFT)
        
        # Output line numbers
        output_line_frame = ttk.Frame(output_frame)
        output_line_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        output_line_numbers = tk.Text(output_line_frame, width=4, padx=3, takefocus=0,
                                     border=0, state='disabled', wrap='none')
        output_line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        
        # Output text with custom scrollbar
        output_text_frame = ttk.Frame(output_line_frame)
        output_text_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        output_text = tk.Text(output_text_frame, wrap=tk.WORD, state='disabled')
        output_scrollbar = ttk.Scrollbar(output_text_frame, orient=tk.VERTICAL)
        
        # Configure synchronized scrolling
        output_text.config(yscrollcommand=lambda *args: self.sync_scroll(output_scrollbar, output_line_numbers, *args))
        output_scrollbar.config(command=lambda *args: self.sync_scroll_command(output_text, output_line_numbers, *args))
        
        output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Output status bar
        output_status_frame = ttk.Frame(output_frame)
        output_status_frame.pack(fill=tk.X, padx=5, pady=2)
        
        output_status_label = ttk.Label(output_status_frame, text="")
        output_status_label.pack(side=tk.LEFT)
        
        # Add Generate AI Response button to provider frame now that widgets exist
        generate_btn = ttk.Button(provider_frame, text="Generate AI Response", 
                                 command=lambda: self.generate_ai_response_with_settings(
                                     input_text, output_text, output_line_numbers, output_status_label,
                                     provider_var.get(), api_key_var.get(), model_var.get()))
        generate_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # Control buttons
        control_frame = ttk.Frame(window)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        if target_widget:
            apply_btn = ttk.Button(control_frame, text="Apply to Original", 
                                  command=lambda: self.apply_ai_result(output_text, target_widget, window))
            apply_btn.pack(side=tk.LEFT, padx=5)
            
        close_btn = ttk.Button(control_frame, text="Close", command=window.destroy)
        close_btn.pack(side=tk.RIGHT, padx=5)
        
        # Update status bars on text change
        def update_input_status(*args):
            text = input_text.get(1.0, tk.END)
            self.update_form_line_numbers(input_line_numbers, text)
            self.update_form_status_label(input_status_label, text)
            
        def update_output_status(*args):
            text = output_text.get(1.0, tk.END)
            self.update_form_line_numbers(output_line_numbers, text)
            self.update_form_status_label(output_status_label, text)
            
        input_text.bind('<KeyRelease>', update_input_status)
        output_text.bind('<KeyRelease>', update_output_status)
        
        # Initial status update
        update_input_status()
        
        # Auto-size window after content is created and show it
        self.root.after(10, lambda: self.auto_size_window(window, 1400, 900, True))
        
    def generate_ai_response(self, input_text, output_text, output_line_numbers, output_status_label):
        """Generate AI response in separate thread"""
        input_prompt = input_text.get(1.0, tk.END).strip()
        if not input_prompt:
            messagebox.showwarning("No Input", "Please enter text to process")
            return
            
        # Disable output text for editing
        output_text.config(state='normal')
        output_text.delete(1.0, tk.END)
        output_text.insert(1.0, "Generating AI response...")
        output_text.config(state='disabled')
        
        def ai_worker():
            try:
                # Get AI settings
                ai_provider = self.settings.get('ai_provider', 'OpenAI')
                ai_api_key = self.settings.get('ai_api_key', '')
                
                if not ai_api_key:
                    self.root.after(0, lambda: messagebox.showerror("AI Error", "AI API key not configured in settings"))
                    return
                    
                # Create AI manager and generate response
                ai_manager = AIManager(tool_name=ai_provider, api_key=ai_api_key)
                response = ai_manager.generate_response(input_prompt)
                
                # Update UI in main thread
                def update_output():
                    output_text.config(state='normal')
                    output_text.delete(1.0, tk.END)
                    output_text.insert(1.0, response)
                    output_text.config(state='disabled')
                    
                    # Update line numbers and status
                    self.update_form_line_numbers(output_line_numbers, response)
                    self.update_form_status_label(output_status_label, response)
                    
                self.root.after(0, update_output)
                
            except Exception as e:
                error_msg = f"AI Error: {e}"
                self.logger.error(error_msg)
                
                def show_error():
                    output_text.config(state='normal')
                    output_text.delete(1.0, tk.END)
                    output_text.insert(1.0, error_msg)
                    output_text.config(state='disabled')
                    
                self.root.after(0, show_error)
                
        # Start AI processing in background thread
        threading.Thread(target=ai_worker, daemon=True).start()
        
    def generate_ai_response_with_settings(self, input_text, output_text, output_line_numbers, output_status_label, provider, api_key, model):
        """Generate AI response with custom settings"""
        input_prompt = input_text.get(1.0, tk.END).strip()
        if not input_prompt:
            messagebox.showwarning("No Input", "Please enter text to process")
            return
            
        if not api_key:
            messagebox.showerror("AI Error", "Please enter an API key")
            return
            
        # Save settings
        self.settings['ai_provider'] = provider
        self.settings['ai_api_key'] = api_key
        self.save_settings()
            
        # Disable output text for editing
        output_text.config(state='normal')
        output_text.delete(1.0, tk.END)
        output_text.insert(1.0, "Generating AI response...")
        output_text.config(state='disabled')
        
        def ai_worker():
            try:
                # Create AI manager with custom settings
                ai_manager = AIManager(tool_name=provider, api_key=api_key)
                
                # Override model if specified
                override_settings = {}
                if model:
                    override_settings['MODEL'] = model
                    
                response = ai_manager.generate_response(input_prompt, override_settings)
                
                # Update UI in main thread
                def update_output():
                    output_text.config(state='normal')
                    output_text.delete(1.0, tk.END)
                    output_text.insert(1.0, response)
                    output_text.config(state='disabled')
                    
                    # Update line numbers and status
                    self.update_form_line_numbers(output_line_numbers, response)
                    self.update_form_status_label(output_status_label, response)
                    
                self.root.after(0, update_output)
                
            except Exception as e:
                error_msg = f"AI Error: {e}"
                self.logger.error(error_msg)
                
                def show_error():
                    output_text.config(state='normal')
                    output_text.delete(1.0, tk.END)
                    output_text.insert(1.0, error_msg)
                    output_text.config(state='disabled')
                    
                self.root.after(0, show_error)
                
        # Start AI processing in background thread
        threading.Thread(target=ai_worker, daemon=True).start()
        
    def open_api_key_url(self, provider):
        """Open URL to get API key for the selected provider"""
        urls = {
            "Google AI": "https://makersuite.google.com/app/apikey",
            "Anthropic AI": "https://console.anthropic.com/account/keys",
            "OpenAI": "https://platform.openai.com/api-keys",
            "Cohere AI": "https://dashboard.cohere.ai/api-keys",
            "HuggingFace AI": "https://huggingface.co/settings/tokens",
            "Groq AI": "https://console.groq.com/keys",
            "OpenRouterAI": "https://openrouter.ai/keys"
        }
        
        if provider in urls:
            webbrowser.open(urls[provider])
        else:
            messagebox.showinfo("API Key", f"Please visit the {provider} website to get your API key")
            
    def edit_models(self, provider, model_var):
        """Edit available models for the selected provider"""
        if provider not in AIManager._get_default_settings():
            return
            
        provider_settings = AIManager._get_default_settings()[provider]
        
        # Use custom models if available, otherwise use defaults
        if 'custom_models' in self.settings and provider in self.settings['custom_models']:
            models_list = self.settings['custom_models'][provider]
            default_model = models_list[0] if models_list else provider_settings.get('MODEL', '')
        else:
            models_list = provider_settings.get('MODELS_LIST', [])
            default_model = provider_settings.get('MODEL', '')
        
        # Create edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Models - {provider}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.withdraw()  # Hide dialog initially
        
        ttk.Label(dialog, text="Available Models (first line is default):").pack(pady=5)
        
        models_text = scrolledtext.ScrolledText(dialog, height=15)
        models_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Populate with current models, default first
        if default_model and default_model in models_list:
            models_list.remove(default_model)
            models_list.insert(0, default_model)
            
        models_text.insert(1.0, '\n'.join(models_list))
        
        def save_models():
            models_content = models_text.get(1.0, tk.END).strip()
            if models_content:
                new_models = [model.strip() for model in models_content.split('\n') if model.strip()]
                if new_models:
                    # Set the first model as default
                    model_var.set(new_models[0])
                    # Save custom models to settings
                    if 'custom_models' not in self.settings:
                        self.settings['custom_models'] = {}
                    self.settings['custom_models'][provider] = new_models
                    self.save_settings()
                    dialog.destroy()
                    
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="Save", command=save_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        # Auto-size dialog after content is created and show it
        self.root.after(10, lambda: self.auto_size_window(dialog, 500, 400, True))
        
    def apply_ai_result(self, output_text, target_widget, window):
        """Apply AI result to target widget"""
        result = output_text.get(1.0, tk.END).strip()
        if result and result != "Generating AI response...":
            target_widget.delete(1.0, tk.END)
            target_widget.insert(1.0, result)
            window.destroy()
            messagebox.showinfo("Applied", "AI result applied to original text")
            
    # Export and backup methods
    def set_export_location(self):
        """Set export location"""
        folder = filedialog.askdirectory(initialdir=self.settings['export_path'])
        if folder:
            self.settings['export_path'] = folder
            self.save_settings()
            messagebox.showinfo("Export Location", f"Export location set to: {folder}")
            
    def export_view(self, format_type):
        """Export currently displayed items"""
        if not hasattr(self, 'search_results') or not self.search_results:
            messagebox.showwarning("No Data", "No items to export")
            return
            
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"prompt_mini_view_{timestamp}.{format_type}"
            filepath = os.path.join(self.settings['export_path'], filename)
            
            if format_type == 'csv':
                self.export_to_csv(self.search_results, filepath)
            elif format_type == 'pdf':
                self.export_to_pdf(self.search_results, filepath)
            elif format_type == 'txt':
                self.export_to_txt(self.search_results, filepath)
            elif format_type == 'docx':
                self.export_to_docx(self.search_results, filepath)
                
            messagebox.showinfo("Export Complete", f"Exported to: {filepath}")
            
        except Exception as e:
            self.logger.error(f"Export error: {e}")
            messagebox.showerror("Export Error", f"Export failed: {e}")
            
    def export_all(self, format_type):
        """Export all items from database"""
        try:
            cursor = self.conn.execute('''
                SELECT id, Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                FROM prompts ORDER BY Modified DESC
            ''')
            all_results = cursor.fetchall()
            
            if not all_results:
                messagebox.showwarning("No Data", "No items to export")
                return
                
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"prompt_mini_all_{timestamp}.{format_type}"
            filepath = os.path.join(self.settings['export_path'], filename)
            
            if format_type == 'csv':
                self.export_to_csv(all_results, filepath)
            elif format_type == 'pdf':
                self.export_to_pdf(all_results, filepath)
            elif format_type == 'txt':
                self.export_to_txt(all_results, filepath)
            elif format_type == 'docx':
                self.export_to_docx(all_results, filepath)
                
            messagebox.showinfo("Export Complete", f"Exported to: {filepath}")
            
        except Exception as e:
            self.logger.error(f"Export error: {e}")
            messagebox.showerror("Export Error", f"Export failed: {e}")        
    
    def export_to_csv(self, data, filepath):
        """Export data to CSV"""
        if not PANDAS_AVAILABLE:
            raise Exception("pandas library not available for CSV export")
            
        df_data = []
        for row in data:
            item_id, created, modified, purpose, prompt, session_urls, tags, note = row
            
            # Parse URLs and tags
            urls_str = session_urls or ""
                    
            tags_str = ""
            if tags:
                try:
                    tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                    tags_str = "; ".join(tag_list)
                except:
                    tags_str = tags
                    
            df_data.append({
                'ID': item_id,
                'Created': created,
                'Modified': modified,
                'Purpose': purpose or "",
                'Prompt': prompt or "",
                'Session URLs': urls_str,
                'Tags': tags_str,
                'Note': note or ""
            })
            
        df = pd.DataFrame(df_data)
        df.to_csv(filepath, index=False)
        
    def export_to_pdf(self, data, filepath):
        """Export data to PDF"""
        if not REPORTLAB_AVAILABLE:
            raise Exception("reportlab library not available for PDF export")
            
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        for row in data:
            item_id, created, modified, purpose, prompt, session_urls, tags, note = row
            
            # Title
            story.append(Paragraph(f"<b>ID: {item_id}</b>", styles['Heading2']))
            story.append(Paragraph(f"Created: {self.format_datetime(created)} | Modified: {self.format_datetime(modified)}", styles['Normal']))
            
            if purpose:
                story.append(Paragraph(f"<b>Purpose:</b> {purpose}", styles['Normal']))
                
            if prompt:
                story.append(Paragraph("<b>Prompt:</b>", styles['Normal']))
                story.append(Paragraph(prompt, styles['Normal']))
                
            # URLs
            if session_urls:
                story.append(Paragraph("<b>Session URLs:</b>", styles['Normal']))
                story.append(Paragraph(session_urls, styles['Normal']))
                    
            # Tags
            if tags:
                try:
                    tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                    story.append(Paragraph(f"<b>Tags:</b> {', '.join(tag_list)}", styles['Normal']))
                except:
                    story.append(Paragraph(f"<b>Tags:</b> {tags}", styles['Normal']))
                    
            if note:
                story.append(Paragraph(f"<b>Note:</b> {note}", styles['Normal']))
                
            story.append(Spacer(1, 20))
            
        doc.build(story)
        
    def export_to_txt(self, data, filepath):
        """Export data to TXT"""
        with open(filepath, 'w', encoding='utf-8') as f:
            for row in data:
                item_id, created, modified, purpose, prompt, session_urls, tags, note = row
                
                f.write(f"ID: {item_id}\n")
                f.write(f"Created: {self.format_datetime(created)} | Modified: {self.format_datetime(modified)}\n")
                
                if purpose:
                    f.write(f"Purpose: {purpose}\n")
                    
                if prompt:
                    f.write(f"\nPrompt:\n{prompt}\n")
                    
                # URLs
                if session_urls:
                    f.write(f"\nSession URLs:\n{session_urls}\n")
                        
                # Tags
                if tags:
                    try:
                        tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                        f.write(f"\nTags: {', '.join(tag_list)}\n")
                    except:
                        f.write(f"\nTags: {tags}\n")
                        
                if note:
                    f.write(f"\nNote: {note}\n")
                    
                f.write("\n" + "="*80 + "\n\n")
                
    def export_to_docx(self, data, filepath):
        """Export data to DOCX"""
        if not DOCX_AVAILABLE:
            raise Exception("python-docx library not available for DOCX export")
            
        doc = Document()
        doc.add_heading('Prompt Mini Export', 0)
        
        for row in data:
            item_id, created, modified, purpose, prompt, session_urls, tags, note = row
            
            # Title
            doc.add_heading(f'ID: {item_id}', level=2)
            doc.add_paragraph(f"Created: {self.format_datetime(created)} | Modified: {self.format_datetime(modified)}")
            
            if purpose:
                p = doc.add_paragraph()
                p.add_run('Purpose: ').bold = True
                p.add_run(purpose)
                
            if prompt:
                p = doc.add_paragraph()
                p.add_run('Prompt:').bold = True
                doc.add_paragraph(prompt)
                
            # URLs
            if session_urls:
                p = doc.add_paragraph()
                p.add_run('Session URLs:').bold = True
                doc.add_paragraph(session_urls)
                    
            # Tags
            if tags:
                try:
                    tag_list = json.loads(tags) if tags.startswith('[') else tags.split(',')
                    p = doc.add_paragraph()
                    p.add_run('Tags: ').bold = True
                    p.add_run(', '.join(tag_list))
                except:
                    p = doc.add_paragraph()
                    p.add_run('Tags: ').bold = True
                    p.add_run(tags)
                    
            if note:
                p = doc.add_paragraph()
                p.add_run('Note: ').bold = True
                p.add_run(note)
                
            doc.add_page_break()
            
        doc.save(filepath)
        
    def backup_database(self):
        """Backup database"""
        try:
            # Check if database has data
            cursor = self.conn.execute('SELECT COUNT(*) FROM prompts')
            count = cursor.fetchone()[0]
            
            if count == 0:
                messagebox.showinfo("No Data", "There is no data to backup")
                return
                
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"prompt_mini_backup_{timestamp}.bck"
            backup_path = os.path.join(self.settings['export_path'], backup_filename)
            
            # Copy database file
            shutil.copy2('prompt_mini.db', backup_path)
            
            messagebox.showinfo("Backup Complete", f"Backup created: {backup_path}")
            self.logger.info(f"Database backed up to {backup_path}")
            
        except Exception as e:
            self.logger.error(f"Backup error: {e}")
            messagebox.showerror("Backup Error", f"Backup failed: {e}")
            
    def restore_database(self):
        """Restore database from backup"""
        backup_file = filedialog.askopenfilename(
            title="Select Backup File",
            filetypes=[("Backup files", "*.bck"), ("All files", "*.*")],
            initialdir=self.settings['export_path']
        )
        
        if not backup_file:
            return
            
        if messagebox.askyesno("Confirm Restore", 
                              "This will replace all current data. Are you sure?"):
            try:
                # Close current connection
                self.conn.close()
                
                # Replace database file
                shutil.copy2(backup_file, 'prompt_mini.db')
                
                # Reconnect to database
                self.init_database()
                
                # Refresh view
                self.perform_search()
                
                messagebox.showinfo("Restore Complete", "Database restored successfully")
                self.logger.info(f"Database restored from {backup_file}")
                
            except Exception as e:
                self.logger.error(f"Restore error: {e}")
                messagebox.showerror("Restore Error", f"Restore failed: {e}")
                
    def import_database(self):
        """Import records from backup file with new IDs"""
        backup_file = filedialog.askopenfilename(
            title="Select Backup File to Import",
            filetypes=[("Backup files", "*.bck"), ("All files", "*.*")],
            initialdir=self.settings['export_path']
        )
        
        if not backup_file:
            return
            
        try:
            # Connect to the backup database
            import_conn = sqlite3.connect(backup_file)
            
            # Get records from backup
            cursor = import_conn.execute('''
                SELECT Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note
                FROM prompts
                ORDER BY id
            ''')
            import_records = cursor.fetchall()
            import_conn.close()
            
            if not import_records:
                messagebox.showinfo("No Data", "The backup file contains no records to import")
                return
            
            # Analyze potential duplicates
            duplicate_count = self.analyze_duplicates(import_records)
            
            # Show confirmation dialog with duplicate information
            if self.show_import_confirmation(len(import_records), duplicate_count):
                self.perform_import(import_records)
                
        except Exception as e:
            self.logger.error(f"Import error: {e}")
            messagebox.showerror("Import Error", f"Failed to read backup file: {e}")
            
    def analyze_duplicates(self, import_records):
        """Analyze how many potential duplicates will be created"""
        duplicate_count = 0
        
        try:
            # Get existing records from current database
            cursor = self.conn.execute('''
                SELECT Purpose, Prompt, SessionURLs, Tags, Note
                FROM prompts
            ''')
            existing_records = cursor.fetchall()
            
            # Convert to sets for comparison (excluding Created/Modified which will be different)
            existing_set = set()
            for record in existing_records:
                # Create a comparable tuple (Purpose, Prompt, SessionURLs, Tags, Note)
                comparable = (
                    record[0] or '',  # Purpose
                    record[1] or '',  # Prompt
                    record[2] or '',  # SessionURLs
                    record[3] or '',  # Tags
                    record[4] or ''   # Note
                )
                existing_set.add(comparable)
            
            # Check import records against existing ones
            for record in import_records:
                # Skip Created/Modified (indices 0,1) and compare the rest
                comparable = (
                    record[2] or '',  # Purpose
                    record[3] or '',  # Prompt
                    record[4] or '',  # SessionURLs
                    record[5] or '',  # Tags
                    record[6] or ''   # Note
                )
                if comparable in existing_set:
                    duplicate_count += 1
                    
        except Exception as e:
            self.logger.error(f"Duplicate analysis error: {e}")
            # If analysis fails, assume worst case
            duplicate_count = len(import_records)
            
        return duplicate_count
        
    def show_import_confirmation(self, total_records, duplicate_count):
        """Show import confirmation dialog with duplicate information"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm Import")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.withdraw()  # Hide initially
        
        # Main message
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Warning icon and title
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(title_frame, text="⚠️", font=('TkDefaultFont', 16)).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="Import Confirmation", 
                 font=('TkDefaultFont', 12, 'bold')).pack(side=tk.LEFT, padx=(10, 0))
        
        # Import details
        details_frame = ttk.LabelFrame(main_frame, text="Import Details")
        details_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(details_frame, text=f"Records to import: {total_records}").pack(anchor=tk.W, padx=10, pady=5)
        ttk.Label(details_frame, text=f"Potential duplicates: {duplicate_count}").pack(anchor=tk.W, padx=10, pady=5)
        ttk.Label(details_frame, text=f"New unique records: {total_records - duplicate_count}").pack(anchor=tk.W, padx=10, pady=5)
        
        # Warning message
        warning_frame = ttk.LabelFrame(main_frame, text="Warning")
        warning_frame.pack(fill=tk.X, pady=(0, 15))
        
        warning_text = """This import will add all records from the backup file with new IDs.
        
If there are potential duplicates, you will have multiple copies of the same content in your database.
        
All imported records will have new creation and modification timestamps.
        
This action cannot be undone automatically."""
        
        ttk.Label(warning_frame, text=warning_text, wraplength=400, justify=tk.LEFT).pack(padx=10, pady=10)
        
        # Result variable
        result = {'confirmed': False}
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        def confirm_import():
            result['confirmed'] = True
            dialog.destroy()
            
        def cancel_import():
            result['confirmed'] = False
            dialog.destroy()
        
        ttk.Button(btn_frame, text="Cancel", command=cancel_import).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Import Anyway", command=confirm_import).pack(side=tk.RIGHT)
        
        # Auto-size and show dialog
        self.root.after(10, lambda: self.auto_size_window(dialog, 500, 400, True))
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result['confirmed']
        
    def perform_import(self, import_records):
        """Perform the actual import of records"""
        try:
            imported_count = 0
            current_time = datetime.now().isoformat()
            
            for record in import_records:
                # Skip original Created/Modified, use current timestamp
                _, _, purpose, prompt, session_urls, tags, note = record
                
                # Insert with new ID and current timestamps
                self.conn.execute('''
                    INSERT INTO prompts (Created, Modified, Purpose, Prompt, SessionURLs, Tags, Note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (current_time, current_time, purpose, prompt, session_urls, tags, note))
                
                imported_count += 1
            
            self.conn.commit()
            
            # Refresh the view
            self.perform_search()
            
            # Show success message
            self.update_status_bar(f"Successfully imported {imported_count} records")
            messagebox.showinfo("Import Complete", 
                              f"Successfully imported {imported_count} records with new IDs")
            self.logger.info(f"Imported {imported_count} records from backup")
            
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Import execution error: {e}")
            messagebox.showerror("Import Error", f"Import failed: {e}")
                
    def show_console_log(self):
        """Show console log window"""
        log_window = tk.Toplevel(self.root)
        log_window.title("Console Log")
        log_window.transient(self.root)
        log_window.withdraw()  # Hide window initially
        
        # Log level selection
        level_frame = ttk.Frame(log_window)
        level_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(level_frame, text="Log Level:").pack(side=tk.LEFT)
        
        level_var = tk.StringVar(value=self.settings.get('log_level', 'INFO'))
        level_combo = ttk.Combobox(level_frame, textvariable=level_var, 
                                  values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                                  state="readonly", width=10)
        level_combo.pack(side=tk.LEFT, padx=(5, 0))
        
        # Log display
        log_text = scrolledtext.ScrolledText(log_window, state='disabled')
        log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        def update_log_display():
            """Update log display based on selected level"""
            level_map = {
                "DEBUG": logging.DEBUG,
                "INFO": logging.INFO,
                "WARNING": logging.WARNING,
                "ERROR": logging.ERROR,
                "CRITICAL": logging.CRITICAL
            }
            
            selected_level = level_map[level_var.get()]
            
            log_text.config(state='normal')
            log_text.delete(1.0, tk.END)
            
            for level, message in self.log_messages:
                if level >= selected_level:
                    log_text.insert(tk.END, message + '\n')
                    
            log_text.config(state='disabled')
            log_text.see(tk.END)
            
        def on_level_change(e):
            # Save log level to settings
            self.settings['log_level'] = level_var.get()
            self.save_settings()
            update_log_display()
            
        level_combo.bind('<<ComboboxSelected>>', on_level_change)
        update_log_display()  # Initial display
        
        # Auto-refresh log every 2 seconds
        def auto_refresh():
            if log_window.winfo_exists():
                update_log_display()
                log_window.after(2000, auto_refresh)
                
        auto_refresh()
        
        # Auto-size window after content is created and show it
        self.root.after(10, lambda: self.auto_size_window(log_window, 800, 600, True))
        
    def on_closing(self):
        """Handle application closing - save window geometry"""
        try:
            # Save current window geometry
            geometry = self.root.geometry()
            self.settings['window_geometry'] = geometry
            self.save_settings()
            self.logger.info(f"Saved window geometry: {geometry}")
        except Exception as e:
            self.logger.error(f"Error saving window geometry: {e}")
        finally:
            # Close database connection and destroy window
            if hasattr(self, 'conn'):
                self.conn.close()
            self.root.destroy()
    
    def run(self):
        """Run the application"""
        try:
            self.root.mainloop()
        finally:
            if hasattr(self, 'conn'):
                self.conn.close()

if __name__ == "__main__":
    app = PromptMiniApp()
    app.run()