import tkinter as tk
from tkinter import filedialog
import sys
import argparse
import subprocess
import os
from flask import Blueprint, jsonify, current_app

# Create Blueprint for dialog routes
dialog_bp = Blueprint('dialog', __name__)

def run_dialog(mode):
    try:
        result = subprocess.run(
            [sys.executable, "dialogs.py", mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        output = result.stdout.decode().strip()

        if mode == "multi":
            paths = [line for line in output.splitlines() if line]
            current_app.logger.debug("Got multiple paths: %s", paths)
            if paths:
                return jsonify({"paths": paths})
            else:
                return jsonify({"error": "No files selected"}), 400

        # Single path case (file, folder, save)
        if output and (os.path.exists(output) or mode == "save"):
            current_app.logger.debug("Got path of: %s from user.", output)
            return jsonify({"path": output})
        else:
            return jsonify({"error": "No selection made"}), 400

    except Exception as e:
        current_app.logger.error("Exception in run_dialog: %s", e, exc_info=True)
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

# Flask routes to run dialogs for file/folder selection

@dialog_bp.route("/get-user-file-path")
def get_user_file():
    current_app.logger.info("Getting file path from user")
    return run_dialog("file")

@dialog_bp.route("/get-user-folder-path")
def get_user_folder():
    current_app.logger.info("Getting Folder Path from user")
    return run_dialog("folder")

@dialog_bp.route("/get-save-location-path")
def get_save_location():
    current_app.logger.info("Get save location path - redundant?")
    return run_dialog("save")

@dialog_bp.route("/get-user-multiple-file-paths")
def get_user_multiple_files():
    current_app.logger.info("Getting multiple file paths from user")
    return run_dialog("multi")

def main():
    parser = argparse.ArgumentParser(description="Launch a native file dialog")
    parser.add_argument("mode", choices=["file", "multi", "folder", "save"], help="Dialog mode")
    args = parser.parse_args()

    show_dialog(args.mode)

if __name__ == "__main__":
    main()
