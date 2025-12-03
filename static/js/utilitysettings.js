function resetConfig() {
  fetch('/reset-config', {
    method: 'POST'
  })
    .then(response => response.json())
    .then(data => {
      alert('Config reset! Please restart the app.');
      window.location.reload();
    })
    .catch(error => {
      alert('Error resetting config.');
      console.error(error);
    });
}

function openPathPicker(endpoint, inputId, infoId, configOption, autoSet = false) {
  // autoSet determines if this will automatically send the path it gets off to the flask server to set & save the config option - defaults to false
  fetch(endpoint)
    .then(res => res.json())
    .then(data => {
      const input = document.getElementById(inputId);
      if (data.path) {
        input.value = data.path;
        updateInputWidth(input);
        if (autoSet && configOption) {
          setConfigPath(configOption, inputId, infoId);
        }
      } else {
        document.getElementById(infoId).textContent = "Failed to get path.";
      }
    })
    .catch(err => {
      console.error("Error getting path:", err);
      document.getElementById(infoId).textContent = "Error communicating with server.";
    });
}


function setConfigPath(configOption, inputId, infoId = null) {
  //does this based on the value of the inputId thing, might be worth changing that
  const path = document.getElementById(inputId).value;
  console.log(`Setting config "${configOption}" to path:`, path);

  fetch("/set-config-setting", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      config_option: configOption,
      config_value: path
    })
  })
    .then(res => {
      if (infoId) {
        document.getElementById(infoId).textContent =
          res.ok ? "Setting saved successfully!" : "Failed to set path.";
      }
      console.log(res.ok ? `Successfully set "${configOption}"` : `Failed to set "${configOption}". HTTP status: ${res.status}`);
    })
    .catch(err => {
      console.error(`Error while setting "${configOption}":`, err);
      if (infoId) {
        document.getElementById(infoId).textContent = "Error communicating with server.";
      }
    });
}


function removeConfigPath(configOption, inputId, infoId = null) {
  // tells flask to delete this config option
  fetch("/remove-config-setting", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ config_option: configOption })
  })
    .then(res => res.json())
    .then(data => {
      const input = document.getElementById(inputId);
      if (data.success) {
        input.value = "";
        updateInputWidth(input);
        if (infoId) {
          document.getElementById(infoId).textContent = "Path removed.";
        }
        console.log(`Successfully removed "${configOption}"`);
      } else {
        if (infoId) {
          document.getElementById(infoId).textContent = "Failed to remove path.";
        }
        console.warn(`Failed to remove "${configOption}":`, data);
      }
    })
    .catch(err => {
      console.error(`Error while removing "${configOption}":`, err);
      if (infoId) {
        document.getElementById(infoId).textContent = "Error communicating with server.";
      }
    });
}

async function loadConfig(configOption) {
  const res = await fetch(`/get-config-setting?config_option=${configOption}`);
  const data = await res.json();
  return data.config_value || "";
}

async function loadConfigPath(configOption, inputId) {
  const res = await fetch(`/get-config-setting?config_option=${configOption}`);
  const data = await res.json();
  const input = document.getElementById(inputId);
  input.value = data.config_value || "";
  updateInputWidth(input);
}

function enableAutoResizeInput(inputElement, minWidth = 200, padding = 20) {
  const measurer = document.createElement("span");
  measurer.style.position = "absolute";
  measurer.style.visibility = "hidden";
  measurer.style.whiteSpace = "pre";
  measurer.style.font = getComputedStyle(inputElement).font;
  document.body.appendChild(measurer);

  function update() {
    measurer.textContent = inputElement.value || inputElement.placeholder;
    inputElement.style.width = Math.max(measurer.offsetWidth + padding, minWidth) + "px";
  }

  inputElement.addEventListener("input", update);
  update(); // initial run

  inputElement._resizeHandler = update;
}

function updateInputWidth(inputElement) {
  if (inputElement && inputElement._resizeHandler) {
    inputElement._resizeHandler();
  }
}

function setLoggerLevelFromDropdown() {
  const level = document.getElementById("logger-level-select").value;
  console.log(`Setting LOGGER_LEVEL to: ${level}`);
  setConfigPath("LOGGER_LEVEL", "logger-level-select", "logger-info");
}

async function loadLoggerLevel() {
  const res = await fetch("/get-config-setting?config_option=LOGGER_LEVEL");
  const data = await res.json();

  const select = document.getElementById("logger-level-select");
  const level = data.config_value || "INFO"; // Default to INFO
  select.value = level;
  updateInputWidth(select);
}


window.onload = function () {
  loadConfigPath("FFMPEG_PATH", "ffmpeg-path-holder");
  loadConfigPath("OPZ_MOUNT_PATH", "opz-path-holder");
  loadConfigPath("OP1_MOUNT_PATH", "op1-path-holder");
  loadConfigPath("WORKING_DIRECTORY", "working-dir-holder");
  loadLoggerLevel();

  // only show ffmpeg settings if the OS is Windows
  (async function () {
    const OS = await loadConfig("OS");
    if (OS !== "windows") {
      console.log("Hiding ffmpeg settings because OS is not Windows.");
      document.getElementById("ffmpeg-settings").style.display = 'none';
    }
  })();

  enableAutoResizeInput(document.getElementById("ffmpeg-path-holder"));
  enableAutoResizeInput(document.getElementById("opz-path-holder"));
  enableAutoResizeInput(document.getElementById("op1-path-holder"));
  enableAutoResizeInput(document.getElementById("working-dir-holder"));
};
