import tkinter as tk
from tkinter import filedialog
import sys
import argparse
import subprocess
import os
from flask import jsonify


def run_dialog(mode):
    from app import app
    try:
        result = subprocess.run(
            [sys.executable, "dialog_runner.py", mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        output = result.stdout.decode().strip()

        if mode == "multi":
            paths = [line for line in output.splitlines() if line]
            app.logger.debug("Got multiple paths: %s", paths)
            if paths:
                return jsonify({"paths": paths})
            else:
                return jsonify({"error": "No files selected"}), 400

        # Single path case (file, folder, save)
        if output and (os.path.exists(output) or mode == "save"):
            app.logger.debug("Got path of: %s from user.", output)
            return jsonify({"path": output})
        else:
            return jsonify({"error": "No selection made"}), 400

    except Exception as e:
        app.logger.error("Exception in run_dialog: %s", e, exc_info=True)
        return jsonify({"error": "An internal error has occurred."}), 500


"""


    DO NOT CHANGE THE PRINT STATMENTS IN THIS TO THE LOGGER, IT WILL BREAK IT


"""


def show_dialog(mode):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    match mode:
        case "file":
            path = filedialog.askopenfilename(title="Select a file")
        case "multi":
            paths = filedialog.askopenfilenames(title="Select one or more files")
            if paths:
                for p in paths:
                    print(p)
            return  # skip the rest
        case "folder":
            path = filedialog.askdirectory(title="Select a folder")
        case "save":
            path = filedialog.asksaveasfilename(title="Save file as")
        case _:
            print(f"Unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)

    if path:
        print(path)

def main():
    parser = argparse.ArgumentParser(description="Launch a native file dialog")
    parser.add_argument("mode", choices=["file", "multi", "folder", "save"], help="Dialog mode")
    args = parser.parse_args()

    show_dialog(args.mode)

if __name__ == "__main__":
    main()
