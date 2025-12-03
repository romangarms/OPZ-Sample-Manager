import sys
import webbrowser
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from config import load_config, run_all_config_tasks, get_config_setting, set_config_setting, config_bp
from sample_converter import sample_converter_bp
from sample_manager import sample_manager_bp
from dialogs import dialog_bp

# setup
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Register blueprints
app.register_blueprint(sample_converter_bp)
app.register_blueprint(sample_manager_bp)
app.register_blueprint(config_bp)
app.register_blueprint(dialog_bp)

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

@app.route("/tapeexport")
def tapeexport():
    return render_template("tapeexport.html")

@app.route("/configeditor")
def configeditor():
    return render_template("configeditor.html")

@app.route("/utilitysettings")
def utilitysettings():
    return render_template("utilitysettings.html")

@app.route("/backup")
def backup():
    return render_template("backup.html")

@app.route("/open-external-link")
def open_external_link():
    url = request.args.get("url")

    # Validate URL
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL"}), 400

    try:
        webbrowser.open(url)
        return jsonify({"status": "opened"}), 200
    except Exception as e:
        app.logger.error(f"Error opening external link: {e}")
        return jsonify({"error": "Failed to open link"}), 500

if __name__ == "__main__":
    app_startup_tasks()
    app.run(debug=False)
