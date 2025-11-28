import os
import subprocess
import uuid
import html
import werkzeug.utils
from flask import Blueprint, request, jsonify, current_app
from config import get_config_setting
from sample_converter import convert_audio_file, UPLOAD_FOLDER

# Create Blueprint
sample_manager_bp = Blueprint('sample_manager', __name__)

# Constants
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


# Device storage constants
OPZ_STORAGE_KB = 24000  # 24 MB in KB
OP1_STORAGE_KB = 512000  # 512 MB in KB

# OP-1 sample/patch limits
OP1_DRUM_SAMPLE_LIMIT = 42
OP1_SYNTH_SAMPLE_LIMIT = 42
OP1_PATCH_LIMIT = 100


def get_device_config(device=None):
    """Get mount path and display name for the specified device.

    Args:
        device: "opz" or "op1". If None, uses SELECTED_DEVICE from config.

    Returns:
        tuple: (mount_path, device_name)
    """
    if device is None:
        device = get_config_setting("SELECTED_DEVICE")
    if device == "op1":
        return get_config_setting("OP1_MOUNT_PATH"), "OP-1"
    return get_config_setting("OPZ_MOUNT_PATH"), "OP-Z"


def sanitize_and_validate_path(allowed_base, *path_components):
    """
    Sanitize path components and validate the resulting path is within an allowed directory.
    Prevents path traversal attacks and dangerous characters.

    Args:
        allowed_base: The allowed base directory
        *path_components: Path components to sanitize and join.
                          Each component is sanitized with secure_filename.

    Returns:
        tuple: (is_valid: bool, safe_path: str or None, error: str or None)
    """
    # Sanitize each path component
    sanitized_components = []
    for component in path_components:
        if not component:
            return False, None, "Path component cannot be empty"

        # Use werkzeug's secure_filename to strip dangerous characters
        sanitized = werkzeug.utils.secure_filename(str(component))

        if not sanitized:
            return False, None, f"Invalid path component: '{component}'"

        # Ensure no path separators remain (defense in depth)
        if os.sep in sanitized or '/' in sanitized or '\\' in sanitized:
            return False, None, "Path component cannot contain separators"

        sanitized_components.append(sanitized)

    # Build the full path
    full_path = os.path.join(allowed_base, *sanitized_components)

    # Normalize to resolve any remaining ../ sequences
    normalized_path = os.path.normpath(os.path.abspath(full_path))
    normalized_base = os.path.normpath(os.path.abspath(allowed_base))

    # Validate path is within allowed base
    if not (normalized_path == normalized_base or
            normalized_path.startswith(normalized_base + os.sep)):
        return False, None, "Path is outside allowed directory"

    return True, normalized_path, None


def validate_full_path(full_path, allowed_base):
    """
    Validate that a full path is within an allowed directory.
    Use this for paths received from the frontend (not constructed from components).

    Args:
        full_path: The complete path to validate
        allowed_base: The allowed base directory

    Returns:
        tuple: (is_valid: bool, normalized_path: str or None, error: str or None)
    """
    if not full_path:
        return False, None, "Path cannot be empty"

    # Normalize to resolve any ../ sequences
    normalized_path = os.path.normpath(os.path.abspath(full_path))
    normalized_base = os.path.normpath(os.path.abspath(allowed_base))

    # Validate path is within allowed base
    if not (normalized_path == normalized_base or
            normalized_path.startswith(normalized_base + os.sep)):
        return False, None, "Path is outside allowed directory"

    return True, normalized_path, None


def get_device_storage_info(device, mount_path):
    """
    Calculate storage usage for the specified device.

    Args:
        device: "opz" or "op1"
        mount_path: Path to the device mount directory

    Returns:
        dict with 'used' and 'total' in KB
    """
    total_bytes = 0

    if device == "opz":
        # OP-Z: Only scan samplepacks directory
        scan_path = os.path.join(mount_path, "samplepacks")
        total_storage = OPZ_STORAGE_KB
    else:
        # OP-1: Scan entire mount path
        scan_path = mount_path
        total_storage = OP1_STORAGE_KB

    if os.path.exists(scan_path):
        for root, dirs, files in os.walk(scan_path):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    total_bytes += os.path.getsize(filepath)
                except OSError:
                    pass

    return {
        "used": total_bytes // 1024,  # Convert bytes to KB
        "total": total_storage
    }


def validate_device_folder_structure(device, mount_path):
    """
    Validate that the provided path contains the expected device folder structure.

    Args:
        device: "opz" or "op1"
        mount_path: Path to the device mount directory

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    device_name = "OP-1" if device == "op1" else "OP-Z"

    if not mount_path:
        return False, f"{device_name} mount path not set. Please select your {device_name} mount directory in Utility Settings."

    if not os.path.exists(mount_path):
        return False, f"{device_name} mount path does not exist: {mount_path}"

    if device == "op1":
        # OP-1: Check for drum/ and synth/ directories
        drum_path = os.path.join(mount_path, "drum")
        synth_path = os.path.join(mount_path, "synth")

        if not os.path.exists(drum_path) or not os.path.isdir(drum_path):
            return False, "Invalid OP-1 folder: 'drum' directory not found."

        if not os.path.exists(synth_path) or not os.path.isdir(synth_path):
            return False, "Invalid OP-1 folder: 'synth' directory not found."
    else:
        # OP-Z: Check for samplepacks/ directory with category folders
        samplepacks_path = os.path.join(mount_path, "samplepacks")
        if not os.path.exists(samplepacks_path):
            return False, "Invalid OP-Z folder: 'samplepacks' directory not found. Please select the root OP-Z mount directory."

        if not os.path.isdir(samplepacks_path):
            return False, "Invalid OP-Z folder: 'samplepacks' exists but is not a directory."

        # Check if at least some expected category folders exist
        missing_categories = []
        for category in SAMPLE_CATEGORIES:
            category_path = os.path.join(samplepacks_path, category)
            if not os.path.exists(category_path):
                missing_categories.append(category)

        # If all categories are missing, it's probably not an OP-Z folder
        if len(missing_categories) == len(SAMPLE_CATEGORIES):
            return False, "Invalid OP-Z folder: No sample category folders found in 'samplepacks' directory."

    return True, None


@sample_manager_bp.route("/read-samples")
def read_opz():
    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    current_app.logger.info(f"Reading samples from: {OPZ_MOUNT_PATH}")

    # Validate the OP-Z folder structure
    is_valid, error_message = validate_device_folder_structure("opz", OPZ_MOUNT_PATH)
    if not is_valid:
        current_app.logger.warning(f"OP-Z folder validation failed: {error_message}")
        return jsonify({
            "validation_error": error_message,
            "sampleData": [],
            "categories": SAMPLE_CATEGORIES
        })

    sample_data = []
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

    # Add storage info
    storage = get_device_storage_info("opz", OPZ_MOUNT_PATH)

    return jsonify({"sampleData": sample_data, "categories": SAMPLE_CATEGORIES, "storage": storage})

@sample_manager_bp.route("/upload-sample", methods=["POST"])
def upload_sample():
    """Upload a sample to OP-Z or OP-1."""
    device = request.form.get("device", get_config_setting("SELECTED_DEVICE"))
    file = request.files.get("file")

    if not file:
        return {"error": "Missing file"}, 400

    mount_path, device_name = get_device_config(device)

    if device == "op1":
        # OP-1: Uses target_path (e.g., "drum/electronic")
        target_path = request.form.get("target_path")
        if not target_path:
            return {"error": "Missing target_path"}, 400

        parts = target_path.split("/")
        if len(parts) != 2 or parts[0] not in ["drum", "synth"]:
            return {"error": "Invalid target_path format"}, 400

        parent_folder, subdir = parts

        if subdir == "user":
            return {"error": "Cannot upload to 'user' directory"}, 403

        # Validate folder structure
        is_valid, error_message = validate_device_folder_structure("op1", mount_path)
        if not is_valid:
            return {"error": error_message}, 400

        # Check limits before upload
        counts = get_op1_counts(mount_path)
        if parent_folder == "drum" and counts["drum_samples"] >= OP1_DRUM_SAMPLE_LIMIT:
            return {"error": f"Drum sample limit reached ({OP1_DRUM_SAMPLE_LIMIT})"}, 400
        elif parent_folder == "synth" and counts["synth_samples"] >= OP1_SYNTH_SAMPLE_LIMIT:
            return {"error": f"Synth sample limit reached ({OP1_SYNTH_SAMPLE_LIMIT})"}, 400

        # Sanitize and validate path (prevents path traversal and dangerous characters)
        is_valid, safe_target_dir, error = sanitize_and_validate_path(mount_path, parent_folder, subdir)
        if not is_valid:
            return {"error": error}, 403

        sample_type = "drum" if parent_folder == "drum" else "synth"
        file_extension = ".aif"
        overwrite_existing = False
    else:
        # OP-Z: Uses category and slot
        category = request.form.get("category")
        slot = request.form.get("slot")

        if not category or not slot:
            return {"error": "Missing category or slot"}, 400

        # Validate category against allowed list
        if category not in SAMPLE_CATEGORIES:
            return {"error": "Invalid category"}, 400

        # Sanitize and validate path (prevents path traversal and dangerous characters)
        samplepacks_base = os.path.join(mount_path, "samplepacks")
        is_valid, safe_target_dir, error = sanitize_and_validate_path(
            samplepacks_base, category, f"{int(slot)+1:02d}"
        )
        if not is_valid:
            return {"error": error}, 403

        sample_type = get_sample_type_from_category(category)
        file_extension = ".aiff"
        overwrite_existing = True

    os.makedirs(safe_target_dir, exist_ok=True)

    # Clean the filename and determine if conversion is needed
    original_filename = werkzeug.utils.secure_filename(file.filename)
    file_ext = os.path.splitext(original_filename)[1].lower()
    needs_conversion = file_ext not in [".aif", ".aiff"]

    # Final filename
    base_name = os.path.splitext(original_filename)[0]
    final_filename = base_name + file_extension
    final_path = os.path.join(safe_target_dir, final_filename)

    # OP-1: Avoid overwriting by adding counter
    if not overwrite_existing:
        counter = 1
        while os.path.exists(final_path):
            final_filename = f"{base_name}_{counter}{file_extension}"
            final_path = os.path.join(safe_target_dir, final_filename)
            counter += 1

    temp_path = None

    try:
        # OP-Z: Delete existing files in slot before uploading
        if overwrite_existing:
            for existing_file in os.listdir(safe_target_dir):
                existing_path = os.path.join(safe_target_dir, existing_file)
                if os.path.isfile(existing_path):
                    os.remove(existing_path)

        if needs_conversion:
            temp_path = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()) + "_" + original_filename)
            file.save(temp_path)
            convert_audio_file(temp_path, final_path, sample_type)
        else:
            file.save(final_path)

        return {
            "status": "uploaded",
            "path": html.escape(final_path),
            "filename": html.escape(final_filename),
            "filesize": os.path.getsize(final_path),
        }, 200

    except subprocess.CalledProcessError as e:
        current_app.logger.error(f"Conversion error: {e}")
        return {"error": "Audio conversion failed"}, 500
    except Exception as e:
        current_app.logger.error(f"Upload error: {e}")
        return {"error": "File save failed"}, 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@sample_manager_bp.route("/delete-sample", methods=["DELETE"])
def delete_sample():
    """Delete a sample from OP-Z or OP-1."""
    data = request.get_json()
    sample_path = data.get("path")
    device = data.get("device", get_config_setting("SELECTED_DEVICE"))

    if not sample_path:
        return {"error": "Invalid path"}, 400

    mount_path, device_name = get_device_config(device)

    # Determine allowed base directory
    if device == "op1":
        allowed_base = mount_path
    else:
        allowed_base = os.path.join(mount_path, "samplepacks")

    # Validate path is within allowed directory (prevents path traversal)
    is_valid, safe_path, error = validate_full_path(sample_path, allowed_base)
    if not is_valid:
        return {"error": "Unauthorized path"}, 403

    if not os.path.isfile(safe_path):
        return {"error": "Invalid path"}, 400

    # OP-1: Check if in "user" directory (read-only)
    if device == "op1":
        rel_path = os.path.relpath(safe_path, mount_path)
        parts = rel_path.split(os.sep)
        if len(parts) >= 2 and parts[1] == "user":
            return {"error": "Cannot delete from 'user' directory"}, 403

    try:
        os.remove(safe_path)
        return {"status": "deleted"}, 200
    except Exception as e:
        current_app.logger.error(f"Error deleting {device_name} file: {e}")
        return {"error": "Failed to delete file"}, 500

@sample_manager_bp.route("/move-sample", methods=["POST"])
def move_sample():
    source_path = request.form.get("source_path")
    target_category = request.form.get("target_category")
    target_slot = request.form.get("target_slot")

    if not source_path or not target_category or target_slot is None:
        return {"error": "Missing required fields"}, 400

    OPZ_MOUNT_PATH = get_config_setting("OPZ_MOUNT_PATH")
    samplepacks_base = os.path.join(OPZ_MOUNT_PATH, "samplepacks")

    # Validate source path is within samplepacks (full path from frontend)
    is_valid, safe_source_path, error = validate_full_path(source_path, samplepacks_base)
    if not is_valid:
        return {"error": "Invalid source path"}, 403

    if not os.path.isfile(safe_source_path):
        return {"error": "Source file doesn't exist"}, 404

    # Validate target_category against allowed list
    if target_category not in SAMPLE_CATEGORIES:
        return {"error": "Invalid category"}, 400

    # Sanitize and validate destination path
    filename = os.path.basename(safe_source_path)
    is_valid, safe_target_dir, error = sanitize_and_validate_path(
        samplepacks_base, target_category, f"{int(target_slot)+1:02d}"
    )
    if not is_valid:
        return {"error": error}, 403

    os.makedirs(safe_target_dir, exist_ok=True)
    target_path = os.path.join(safe_target_dir, filename)

    try:
        # Check if there's an existing file in the target slot
        existing_files = [f for f in os.listdir(safe_target_dir) if os.path.isfile(os.path.join(safe_target_dir, f))]
        if existing_files:
            # Assume one sample per folder — just grab the first one
            existing_target = os.path.join(safe_target_dir, existing_files[0])

            # Swap paths if moving between different slots
            if os.path.abspath(safe_source_path) != os.path.abspath(existing_target):
                # Move target sample to source's original folder
                source_dir = os.path.dirname(safe_source_path)
                swapped_target = os.path.join(source_dir, os.path.basename(existing_target))
                os.rename(existing_target, swapped_target)

        # Move new file into target slot (overwriting any remaining copy of itself)
        os.rename(safe_source_path, target_path)

        return {"status": "moved", "path": html.escape(target_path)}, 200

    except Exception as e:
        current_app.logger.error(f"Move error: {e}")
        return {"error": "Move failed"}, 500

@sample_manager_bp.route("/open-device-directory")
def open_device_directory():
    """Open the device mount directory in the file explorer."""
    device = request.args.get("device", "opz")

    if device == "op1":
        mount_path = get_config_setting("OP1_MOUNT_PATH")
        device_name = "OP-1"
    else:
        mount_path = get_config_setting("OPZ_MOUNT_PATH")
        device_name = "OP-Z"

    if not mount_path or not os.path.exists(mount_path):
        return {"error": f"{device_name} directory not found"}, 404

    try:
        import platform
        system = platform.system()

        if system == "Windows":
            os.startfile(mount_path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", mount_path])
        else:  # Linux
            subprocess.run(["xdg-open", mount_path])

        return {"status": "opened"}, 200
    except Exception as e:
        current_app.logger.error(f"Error opening {device_name} directory: {e}")
        return {"error": "Failed to open directory"}, 500


# ============================================================================
# OP-1 Sample Manager Functions
# ============================================================================

def parse_op1_file_type(filepath):
    """
    Parse an AIF file to determine its OP-1 type by looking for embedded JSON.

    Returns:
        - "drum_sample": In drum/ folder, no JSON or type="drum"
        - "synth_sample": In synth/ folder, no JSON or type="sampler"
        - "drum_patch": In drum/ folder, type="dbox"
        - "synth_patch": In synth/ folder, type is not "sampler" (e.g., "digital")
        - None: If file cannot be read
    """
    try:
        with open(filepath, 'rb') as f:
            content = f.read()

        # Look for the OP-1 JSON marker
        marker = b'op-1'
        marker_pos = content.find(marker)

        if marker_pos == -1:
            # No OP-1 JSON found - it's a plain sample
            return "sample"

        # Find the JSON after the marker
        # The JSON starts after "op-1" and some bytes
        json_start = content.find(b'{', marker_pos)
        if json_start == -1:
            return "sample"

        # Find the end of the JSON (matching brace)
        brace_count = 0
        json_end = json_start
        for i in range(json_start, len(content)):
            if content[i:i+1] == b'{':
                brace_count += 1
            elif content[i:i+1] == b'}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break

        # Parse the JSON
        import json
        json_str = content[json_start:json_end].decode('utf-8', errors='ignore')
        data = json.loads(json_str)

        file_type = data.get("type", "")

        # Return the type for classification
        if file_type == "drum":
            return "sample"  # drum type means it's a processed sample
        elif file_type == "sampler":
            return "sample"  # sampler type is also a sample
        elif file_type == "dbox":
            return "drum_patch"
        elif file_type:
            return "synth_patch"  # Any other type (digital, etc.) is a synth patch
        else:
            return "sample"

    except Exception as e:
        current_app.logger.error(f"Error parsing OP-1 file type for {filepath}: {e}")
        return "sample"  # Default to sample if we can't parse


def get_op1_file_category(filepath, parent_folder):
    """
    Determine the category of an OP-1 file based on its type and parent folder.

    Args:
        filepath: Path to the AIF file
        parent_folder: "drum" or "synth"

    Returns:
        "drum_sample", "synth_sample", or "patch"
    """
    file_type = parse_op1_file_type(filepath)

    if file_type == "drum_patch" or file_type == "synth_patch":
        return "patch"
    elif parent_folder == "drum":
        return "drum_sample"
    else:
        return "synth_sample"


def get_op1_counts(op1_mount_path):
    """
    Count samples and patches in the OP-1 directories.
    Note: "user" directories are excluded from counts as they are special.

    Returns:
        dict with drum_samples, synth_samples, and patches counts
    """
    counts = {
        "drum_samples": 0,
        "synth_samples": 0,
        "patches": 0
    }

    for parent_folder in ["drum", "synth"]:
        folder_path = os.path.join(op1_mount_path, parent_folder)
        if not os.path.exists(folder_path):
            continue

        for subdir in os.listdir(folder_path):
            # Skip "user" directories - they're special and don't count toward limits
            if subdir == "user":
                continue

            subdir_path = os.path.join(folder_path, subdir)
            if not os.path.isdir(subdir_path):
                continue

            for file in os.listdir(subdir_path):
                if not file.lower().endswith(('.aif', '.aiff')):
                    continue

                filepath = os.path.join(subdir_path, file)
                category = get_op1_file_category(filepath, parent_folder)

                if category == "drum_sample":
                    counts["drum_samples"] += 1
                elif category == "synth_sample":
                    counts["synth_samples"] += 1
                elif category == "patch":
                    counts["patches"] += 1

    return counts


@sample_manager_bp.route("/read-op1-samples")
def read_op1():
    """Read all samples and patches from OP-1 directory structure."""
    OP1_MOUNT_PATH = get_config_setting("OP1_MOUNT_PATH")
    current_app.logger.info(f"Reading OP-1 samples from: {OP1_MOUNT_PATH}")

    # Validate the OP-1 folder structure
    is_valid, error_message = validate_device_folder_structure("op1", OP1_MOUNT_PATH)
    if not is_valid:
        current_app.logger.warning(f"OP-1 folder validation failed: {error_message}")
        return jsonify({
            "validation_error": error_message,
            "drum": {"subdirectories": {}},
            "synth": {"subdirectories": {}}
        })

    result = {
        "drum": {"subdirectories": {}},
        "synth": {"subdirectories": {}}
    }

    for parent_folder in ["drum", "synth"]:
        folder_path = os.path.join(OP1_MOUNT_PATH, parent_folder)
        if not os.path.exists(folder_path):
            continue

        for subdir in sorted(os.listdir(folder_path)):
            subdir_path = os.path.join(folder_path, subdir)
            if not os.path.isdir(subdir_path):
                continue

            files = []
            for file in sorted(os.listdir(subdir_path)):
                if not file.lower().endswith(('.aif', '.aiff')):
                    continue

                filepath = os.path.join(subdir_path, file)
                file_type = parse_op1_file_type(filepath)
                category = get_op1_file_category(filepath, parent_folder)

                try:
                    filesize = os.path.getsize(filepath)
                except OSError:
                    filesize = 0

                files.append({
                    "name": file,
                    "path": filepath,
                    "size": filesize,
                    "type": file_type,
                    "category": category
                })

            result[parent_folder]["subdirectories"][subdir] = files

    # Add counts and storage info
    result["counts"] = get_op1_counts(OP1_MOUNT_PATH)
    result["storage"] = get_device_storage_info("op1", OP1_MOUNT_PATH)

    return jsonify(result)


@sample_manager_bp.route("/upload-op1-folder", methods=["POST"])
def upload_op1_folder():
    """Upload multiple files as a new subdirectory."""
    parent_folder = request.form.get("parent")  # "drum" or "synth"
    folder_name = request.form.get("folder_name")
    files = request.files.getlist("files")

    if not parent_folder or not folder_name or not files:
        return {"error": "Missing parent, folder_name, or files"}, 400

    if parent_folder not in ["drum", "synth"]:
        return {"error": "Invalid parent folder"}, 400

    # Check for reserved folder name
    if folder_name == "user":
        return {"error": "Cannot use 'user' as folder name"}, 400

    OP1_MOUNT_PATH = get_config_setting("OP1_MOUNT_PATH")

    is_valid, error_message = validate_device_folder_structure("op1", OP1_MOUNT_PATH)
    if not is_valid:
        return {"error": error_message}, 400

    # Sanitize and validate path (prevents path traversal and dangerous characters)
    is_valid, safe_target_dir, error = sanitize_and_validate_path(OP1_MOUNT_PATH, parent_folder, folder_name)
    if not is_valid:
        return {"error": error}, 403

    # Check limits
    counts = get_op1_counts(OP1_MOUNT_PATH)
    num_files = len([f for f in files if f.filename])

    if parent_folder == "drum":
        if counts["drum_samples"] + num_files > OP1_DRUM_SAMPLE_LIMIT:
            return {"error": f"Would exceed drum sample limit ({OP1_DRUM_SAMPLE_LIMIT})"}, 400
    else:
        if counts["synth_samples"] + num_files > OP1_SYNTH_SAMPLE_LIMIT:
            return {"error": f"Would exceed synth sample limit ({OP1_SYNTH_SAMPLE_LIMIT})"}, 400

    os.makedirs(safe_target_dir, exist_ok=True)

    uploaded = []
    errors = []

    for file in files:
        if not file.filename:
            continue

        original_filename = werkzeug.utils.secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1].lower()
        needs_conversion = file_ext not in [".aif", ".aiff"]

        base_name = os.path.splitext(original_filename)[0]
        final_filename = base_name + ".aif"
        final_path = os.path.join(safe_target_dir, final_filename)

        # Avoid overwriting
        counter = 1
        while os.path.exists(final_path):
            final_filename = f"{base_name}_{counter}.aif"
            final_path = os.path.join(safe_target_dir, final_filename)
            counter += 1

        temp_path = None

        try:
            if needs_conversion:
                temp_path = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()) + "_" + original_filename)
                file.save(temp_path)
                sample_type = "drum" if parent_folder == "drum" else "synth"
                convert_audio_file(temp_path, final_path, sample_type)
            else:
                file.save(final_path)

            uploaded.append(final_filename)
        except Exception as e:
            current_app.logger.error(f"Error uploading {original_filename}: {e}")
            errors.append(original_filename)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    return {
        "status": "uploaded",
        "folder": folder_name,
        "uploaded": uploaded,
        "errors": errors
    }, 200


@sample_manager_bp.route("/create-op1-subdirectory", methods=["POST"])
def create_op1_subdirectory():
    """Create a new subdirectory in drum or synth folder."""
    data = request.get_json()
    parent = data.get("parent")  # "drum" or "synth"
    name = data.get("name")

    if not parent or not name:
        return {"error": "Missing parent or name"}, 400

    if parent not in ["drum", "synth"]:
        return {"error": "Invalid parent folder"}, 400

    # Check for reserved folder name
    if name == "user":
        return {"error": "Cannot use 'user' as folder name"}, 400

    OP1_MOUNT_PATH = get_config_setting("OP1_MOUNT_PATH")

    is_valid, error_message = validate_device_folder_structure("op1", OP1_MOUNT_PATH)
    if not is_valid:
        return {"error": error_message}, 400

    # Sanitize and validate path (prevents path traversal and dangerous characters)
    is_valid, safe_target_path, error = sanitize_and_validate_path(OP1_MOUNT_PATH, parent, name)
    if not is_valid:
        return {"error": error}, 403

    if os.path.exists(safe_target_path):
        return {"error": "Folder already exists"}, 400

    try:
        os.makedirs(safe_target_path)
        return {"status": "created", "path": safe_target_path}, 200
    except Exception as e:
        current_app.logger.error(f"Error creating OP-1 subdirectory: {e}")
        return {"error": "Failed to create folder"}, 500


@sample_manager_bp.route("/rename-op1-subdirectory", methods=["POST"])
def rename_op1_subdirectory():
    """Rename a subdirectory."""
    data = request.get_json()
    old_path = data.get("old_path")  # e.g., "drum/electronic"
    new_name = data.get("new_name")

    if not old_path or not new_name:
        return {"error": "Missing old_path or new_name"}, 400

    parts = old_path.split("/")
    if len(parts) != 2 or parts[0] not in ["drum", "synth"]:
        return {"error": "Invalid path format"}, 400

    parent, old_name = parts

    # Can't rename "user" directory
    if old_name == "user":
        return {"error": "Cannot rename 'user' directory"}, 403

    # Can't rename to "user"
    if new_name == "user":
        return {"error": "Cannot use 'user' as folder name"}, 400

    OP1_MOUNT_PATH = get_config_setting("OP1_MOUNT_PATH")

    # Sanitize and validate both paths (prevents path traversal and dangerous characters)
    is_valid, safe_old_path, error = sanitize_and_validate_path(OP1_MOUNT_PATH, parent, old_name)
    if not is_valid:
        return {"error": error}, 403

    is_valid, safe_new_path, error = sanitize_and_validate_path(OP1_MOUNT_PATH, parent, new_name)
    if not is_valid:
        return {"error": error}, 403

    if not os.path.exists(safe_old_path):
        return {"error": "Folder does not exist"}, 404

    if os.path.exists(safe_new_path):
        return {"error": "A folder with that name already exists"}, 400

    try:
        os.rename(safe_old_path, safe_new_path)
        return {"status": "renamed", "new_path": f"{parent}/{new_name}"}, 200
    except Exception as e:
        current_app.logger.error(f"Error renaming OP-1 subdirectory: {e}")
        return {"error": "Failed to rename folder"}, 500


@sample_manager_bp.route("/delete-op1-subdirectory", methods=["DELETE"])
def delete_op1_subdirectory():
    """Delete a subdirectory and all its contents."""
    data = request.get_json()
    path = data.get("path")  # e.g., "drum/electronic"

    if not path:
        return {"error": "Missing path"}, 400

    parts = path.split("/")
    if len(parts) != 2 or parts[0] not in ["drum", "synth"]:
        return {"error": "Invalid path format"}, 400

    parent, name = parts

    # Can't delete "user" directory
    if name == "user":
        return {"error": "Cannot delete 'user' directory"}, 403

    OP1_MOUNT_PATH = get_config_setting("OP1_MOUNT_PATH")

    # Sanitize and validate path (prevents path traversal and dangerous characters)
    is_valid, safe_path, error = sanitize_and_validate_path(OP1_MOUNT_PATH, parent, name)
    if not is_valid:
        return {"error": error}, 403

    if not os.path.exists(safe_path):
        return {"error": "Folder does not exist"}, 404

    try:
        import shutil
        shutil.rmtree(safe_path)
        return {"status": "deleted"}, 200
    except Exception as e:
        current_app.logger.error(f"Error deleting OP-1 subdirectory: {e}")
        return {"error": "Failed to delete folder"}, 500


