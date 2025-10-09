import json
import sys
from flask import Flask, render_template, request, jsonify
import html
from flask_cors import CORS
import os
import werkzeug.utils
import subprocess
import uuid
from config import (
    load_config,
    save_config,
    reset_config,
    run_config_task,
    run_all_config_tasks,
    get_config_setting,
    set_config_setting,
    delete_config_setting,
    read_json_from_path,
    write_json_to_path
)
from dialog_runner import run_dialog

# setup
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# constants
NUMBER_OF_SAMPLE_TYPES = 8
NUMBER_OF_SAMPLES_PER_SLOT = 10  # Number of samples to read
SAMPLE_CATEGORIES = [
    "1-kick",
    "2-snare",
    "3-perc",
    "4-fx",
    "5-bass",
    "6-lead",
    "7-arpeggio",
    "8-chord",
]
sample_data = [
    [{"path": None} for _ in range(NUMBER_OF_SAMPLES_PER_SLOT)]
    for _ in range(NUMBER_OF_SAMPLE_TYPES)
]

# Create necessary directories
UPLOAD_FOLDER = "uploads"
CONVERTED_FOLDER = "converted"
SYN_CONVERTED_FOLDER = "converted/synth"
DRUM_CONVERTED_FOLDER = "converted/drum"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)
os.makedirs(SYN_CONVERTED_FOLDER, exist_ok=True)
os.makedirs(DRUM_CONVERTED_FOLDER, exist_ok=True)

# Helper function to convert audio files to OP-Z compatible format
def convert_audio_file(input_path, output_path, sample_type):
    """
    Convert an audio file to OP-Z compatible AIFF format.

    Args:
        input_path: Path to the input audio file
        output_path: Path where the converted file should be saved
        sample_type: Either "drum" (12s max) or "synth" (6s max)

    Returns:
        True if conversion succeeds

    Raises:
        Exception if conversion fails
    """
    max_duration = 12 if sample_type == "drum" else 6
    ffmpeg_path = get_config_setting("FFMPEG_PATH", "ffmpeg")

    ffmpeg_cmd = [
        ffmpeg_path,
        "-i",
        input_path,
        "-af",
        "loudnorm",  # normalize audio
        "-t",
        str(max_duration),  # trim to correct duration
        "-ac",
        "1",  # force mono
        "-ar",
        "44100",  # sample rate 44.1k
        "-sample_fmt",
        "s16",  # 16-bit samples
        output_path,
    ]

    subprocess.run(ffmpeg_cmd, check=True)
    return True

# Helper function to determine sample type from category
def get_sample_type_from_category(category):
    """
    Determine if a category is a drum or synth sample.

    Categories 1-4 (kick, snare, perc, fx) are drum samples (12s max).
    Categories 5-8 (bass, lead, arpeggio, chord) are synth samples (6s max).

    Args:
        category: Category string like "1-kick" or "8-chord"

    Returns:
        "drum" or "synth"
    """
    drum_categories = ["1-kick", "2-snare", "3-perc", "4-fx"]
    return "drum" if category in drum_categories else "synth"

# run before server startup at the end of this file
def app_startup_tasks():
    # config
    load_config()
    run_all_config_tasks()  # Initialize config settings
    # fetch and set the os config
    set_config_setting("OS", get_os())



def get_os():
    if sys.platform.startswith("win"):
        app.logger.info("Detected OS: Windows")
        return "windows"
    elif sys.platform.startswith("darwin"):
        app.logger.info("Detected OS: macOS")
        return "macos"
    else:
        app.logger.info("Detected OS: Linux")
        return "linux"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/sampleconverter")
def sampleconverter():
    return render_template("sampleconverter.html")

@app.route("/samplemanager")
def samplemanager():
    return render_template("samplemanager.html")

@app.route("/configeditor")
def configeditor():
    return render_template("configeditor.html")

@app.route("/utilitysettings")
def utilitysettings():
    return render_template("utilitysettings.html")

@app.route("/read-samples")
def read_opz():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    sample_data = []
    app.logger.info(f"Reading samples from: {OPZ_MOUNT_PATH}")

    for category in SAMPLE_CATEGORIES:
        category_data = []
        for slot in range(NUMBER_OF_SAMPLES_PER_SLOT):
            slot_name = f"{slot + 1:02d}"  # "01", "02", ..., "10"
            slot_path = os.path.join(OPZ_MOUNT_PATH, "samplepacks", category, slot_name)

            sample_info = {"path": None}

            if os.path.isdir(slot_path):
                files = [f for f in os.listdir(slot_path) if os.path.isfile(os.path.join(slot_path, f))]
                if files:
                    sample_info["path"] = os.path.join(slot_path, files[0])
                    sample_info["filename"] = files[0]
                    sample_info["filesize"] = os.path.getsize(os.path.join(slot_path, files[0]))

            category_data.append(sample_info)
        sample_data.append(category_data)

    return jsonify({"sampleData": sample_data, "categories": SAMPLE_CATEGORIES})

@app.route("/upload-sample", methods=["POST"])
def upload_sample():
    category = request.form.get("category")
    slot = request.form.get("slot")
    file = request.files.get("file")

    if not category or not slot or not file:
        return {"error": "Missing category, slot, or file"}, 400

    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    # Make sure the directory exists
    target_dir = os.path.join(OPZ_MOUNT_PATH, "samplepacks", category, f"{int(slot)+1:02d}")
    os.makedirs(target_dir, exist_ok=True)

    # Clean the filename and determine if conversion is needed
    original_filename = werkzeug.utils.secure_filename(file.filename)
    file_ext = os.path.splitext(original_filename)[1].lower()
    needs_conversion = file_ext != ".aiff"

    # Final filename will always be .aiff
    base_name = os.path.splitext(original_filename)[0]
    final_filename = base_name + ".aiff"
    final_path = os.path.join(target_dir, final_filename)

    temp_path = None

    try:
        # Delete any existing sample(s) in this slot
        for existing_file in os.listdir(target_dir):
            existing_path = os.path.join(target_dir, existing_file)
            if os.path.isfile(existing_path):
                os.remove(existing_path)

        if needs_conversion:
            # Save to temp location, convert, then delete temp
            temp_path = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()) + "_" + original_filename)
            file.save(temp_path)

            # Determine sample type from category
            sample_type = get_sample_type_from_category(category)

            # Convert to final location
            convert_audio_file(temp_path, final_path, sample_type)
        else:
            # Already .aiff, save directly
            file.save(final_path)

        return {
            "status": "uploaded",
            "path": html.escape(final_path),
            "filename": html.escape(final_filename),
            "filesize": os.path.getsize(final_path),
        }, 200

    except subprocess.CalledProcessError as e:
        app.logger.error(f"Conversion error: {e}")
        return {"error": "Audio conversion failed"}, 500
    except Exception as e:
        app.logger.error(f"Upload error: {e}")
        return {"error": "File save failed"}, 500
    finally:
        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.route("/delete-sample", methods=["DELETE"])
def delete_sample():
    data = request.get_json()
    sample_path = data.get("path")

    if not sample_path or not os.path.isfile(sample_path):
        return {"error": "Invalid path"}, 400

    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    # prevent deleting files outside the samplepacks directory, probably not needed but just in case
    if not sample_path.startswith(os.path.join(OPZ_MOUNT_PATH, "samplepacks")):
        return {"error": "Unauthorized path"}, 403

    try:
        os.remove(sample_path)
        return {"status": "deleted"}, 200
    except Exception as e:
        app.logger.error(f"Error deleting file: {e}")
        return {"error": "Failed to delete file"}, 500

@app.route("/move-sample", methods=["POST"])
def move_sample():
    source_path = request.form.get("source_path")
    target_category = request.form.get("target_category")
    target_slot = request.form.get("target_slot")

    if not source_path or not target_category or target_slot is None:
        return {"error": "Missing required fields"}, 400

    if not os.path.isfile(source_path):
        return {"error": "Source file doesn't exist"}, 404

    # Resolve destination path
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    filename = os.path.basename(source_path)
    target_dir = os.path.join(OPZ_MOUNT_PATH, "samplepacks", target_category, f"{int(target_slot)+1:02d}")
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, filename)

    try:
        # Check if there's an existing file in the target slot
        existing_files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
        if existing_files:
            # Assume one sample per folder — just grab the first one
            existing_target = os.path.join(target_dir, existing_files[0])

            # Swap paths if moving between different slots
            if os.path.abspath(source_path) != os.path.abspath(existing_target):
                # Move target sample to source's original folder
                source_dir = os.path.dirname(source_path)
                swapped_target = os.path.join(source_dir, os.path.basename(existing_target))
                os.rename(existing_target, swapped_target)

        # Move new file into target slot (overwriting any remaining copy of itself)
        os.rename(source_path, target_path)

        from html import escape
        return {"status": "moved", "path": escape(target_path)}, 200

    except Exception as e:
        app.logger.error(f"Move error: {e}")
        return {"error": "Move failed"}, 500

@app.route("/convert", methods=["POST"])
def convert_sample():
    file = request.files["file"]
    sample_type = request.form["type"]

    if file.filename == "":
        return jsonify({"error": "No file uploaded"}), 400

    # Save uploaded file temporarily
    input_path = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()) + "_" + file.filename)
    file.save(input_path)

    # Set output filename (for sample converter page, saves to converted/ folder)
    output_filename = os.path.splitext(os.path.basename(file.filename))[0] + ".aiff"
    output_path = os.path.join(CONVERTED_FOLDER, sample_type, output_filename)

    try:
        # Use shared conversion function
        convert_audio_file(input_path, output_path, sample_type)
        return jsonify({"message": f"Converted to {output_filename} successfully."})
    except subprocess.CalledProcessError as e:
        app.logger.error(f"Subprocess Error: {e}")
        return jsonify({"error": "Conversion failed"}), 500
    except Exception as e:
        app.logger.error("Unknown error while attempting to run the FFMPEG subprocess.")
        if os.name == "nt":
            app.logger.warning("Windows detected. This error is often due to a misconfigured FFMPEG path. Double check it.")
        app.logger.error(f"Error details: {e}")
        return jsonify({"error": "Conversion failed"}), 500
    finally:
        # Clean up input file
        if os.path.exists(input_path):
            os.remove(input_path)
            app.logger.info("Removed unconverted uploaded file")
        else:
            app.logger.warning("Did not find uploaded file and it was not removed")

# open the sample converter's converted folder in the file explorer
@app.route("/open-explorer", methods=["POST"])
def open_explorer():
    folder_path = os.path.join(os.path.abspath("."), CONVERTED_FOLDER)
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", folder_path])
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", folder_path])
        else:  # Linux and others
            subprocess.Popen(["xdg-open", folder_path])

        return jsonify({"status": "opened", "path": folder_path}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Flask routes to run dialogs for file/folder selection

@app.route("/get-user-file-path")
def get_user_file():
    app.logger.info("Getting file path from user")
    return run_dialog("file")

@app.route("/get-user-folder-path")
def get_user_folder():
    app.logger.info("Getting Folder Path from user")
    return run_dialog("folder")

@app.route("/get-save-location-path")
def get_save_location():
    app.logger.info("Get save location path - redundant?")
    return run_dialog("save")

@app.route("/get-user-multiple-file-paths")
def get_user_multiple_files():
    app.logger.info("Getting multiple file paths from user")
    return run_dialog("multi")

# Flask routes to manage config for the sample manager app
# needs the _route because *something*_config_setting already exists in config.py

@app.route('/set-config-setting', methods=['POST'])
def set_config_setting_route():
    try:
        data = request.json
        app.logger.debug("Incoming JSON data: " + str(data))

        config_option = data.get("config_option")
        config_value = data.get("config_value")

        if config_option is None or config_value is None:
            return jsonify({"error": "Missing 'config_option' or 'config_value'"}), 400

        set_config_setting(config_option, config_value)
        run_config_task(config_option)
        return jsonify({"success": True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500

@app.route('/get-config-setting')
def get_config_setting_route():
    config_option = request.args.get("config_option")

    if config_option is None:
        app.logger.warning("Tried to get config setting without any config option sent.")
        return jsonify({"error": "Missing 'config_option' parameter"}), 400

    config_value = get_config_setting(config_option, "")
    if config_value == "":
        app.logger.warning("Did not find a config entry for " + str(config_option) + " or it is an empty string.")
    app.logger.debug("Returning Config value of " + str(config_value) + " for " + str(config_option))
    return jsonify({"success": True, "config_value": config_value})


@app.route('/remove-config-setting', methods=['POST'])
def remove_config_setting_route():
    data = request.json
    config_option = data.get("config_option")

    if config_option is None:
        return jsonify({"error": "Missing 'config_option'"}), 400

    if delete_config_setting(config_option):
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Config option not found"}), 404


# Flask routes to edit config files on the OP-Z
@app.route('/get-config/general')
def get_general_config():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    general_json_path = os.path.join(OPZ_MOUNT_PATH, 'config', 'general.json')
    return jsonify(read_json_from_path(general_json_path))

@app.route('/get-config/midi')
def get_midi_config():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    midi_json_path = os.path.join(OPZ_MOUNT_PATH, 'config', 'midi.json')
    return jsonify(read_json_from_path(midi_json_path))

@app.route('/save-config/general', methods=['POST'])
def save_general_config():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    general_json_path = os.path.join(OPZ_MOUNT_PATH, 'config', 'general.json')
    data = request.get_json()
    write_json_to_path(general_json_path, data)
    return '', 204

@app.route('/save-config/midi', methods=['POST'])
def save_midi_config():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    midi_json_path = os.path.join(OPZ_MOUNT_PATH, 'config', 'midi.json')
    data = request.get_json()
    write_json_to_path(midi_json_path, data)
    return '', 204

@app.route('/reset-config', methods=['POST'])
def reset_config_flask():
    delete_config_setting("OPZ_MOUNT_PATH", save=False)
    reset_config()
    return jsonify({"success": True, "message": "Configuration reset successfully"})

if __name__ == "__main__":
    app_startup_tasks()
    app.run(debug=False)
