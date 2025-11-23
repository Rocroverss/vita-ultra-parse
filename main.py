import tkinter as tk
from tkinter import ttk

class VitaDeckGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Vitadeck")
        self.geometry("1000x600")
        self.configure(bg="#2b2b2b")

        self.create_widgets()

    def create_widgets(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Logging Tab
        logging_frame = ttk.Frame(notebook)
        notebook.add(logging_frame, text="Logging")

        log_text = tk.Text(logging_frame, wrap="word", bg="#1e1e1e", fg="#d0d0d0")
        log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(logging_frame, command=log_text.yview)
        scrollbar.pack(side="right", fill="y")
        log_text.configure(yscrollcommand=scrollbar.set)

        # Sidebar Controls
        sidebar = tk.Frame(self, bg="#2b2b2b")
        sidebar.place(relx=0.8, rely=0, relwidth=0.2, relheight=1)

        # PS Vita IP
        tk.Label(sidebar, text="PS Vita IP", bg="#2b2b2b", fg="white", font=("Arial", 10)).pack(pady=5)
        ip_entry = tk.Entry(sidebar)
        ip_entry.insert(0, "192.168.1.21")
        ip_entry.pack(pady=5, fill="x", padx=10)
        tk.Button(sidebar, text="Reconnect").pack(pady=5, fill="x", padx=10)

        # Core dumps
        tk.Label(sidebar, text="Core dumps", bg="#2b2b2b", fg="white", font=("Arial", 10)).pack(pady=10)
        tk.Button(sidebar, text="Fetch and parse").pack(pady=5, fill="x", padx=10)
        tk.Button(sidebar, text="Fetch and parse (VCP)").pack(pady=5, fill="x", padx=10)

        # Run Executable
        tk.Label(sidebar, text="Run executable", bg="#2b2b2b", fg="white", font=("Arial", 10)).pack(pady=10)
        exe_entry = tk.Entry(sidebar)
        exe_entry.insert(0, "D:/Repos/demos/test/bu")
        exe_entry.pack(pady=5, fill="x", padx=10)

        appid_entry = tk.Entry(sidebar)
        appid_entry.insert(0, "APPL00001")
        appid_entry.pack(pady=5, fill="x", padx=10)

        tk.Checkbutton(sidebar, text="Use temporary App ID", bg="#2b2b2b", fg="white").pack(pady=5, padx=10)

        tk.Button(sidebar, text="Upload and launch").pack(pady=5, fill="x", padx=10)

        # Quick Commands
        tk.Label(sidebar, text="Quick commands", bg="#2b2b2b", fg="white", font=("Arial", 10)).pack(pady=10)
        tk.Button(sidebar, text="Quit all apps").pack(pady=5, fill="x", padx=10)
        tk.Button(sidebar, text="Reboot").pack(pady=5, fill="x", padx=10)

if __name__ == "__main__":
    app = VitaDeckGUI()
    app.mainloop()
