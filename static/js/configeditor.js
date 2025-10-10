function createNumberInput(name, value, idx = null, subIdx = null) {
  const input = document.createElement('input');
  input.type = 'number';
  input.name = name;
  input.value = value;
  input.className = "config-number-input";
  if (idx !== null) input.dataset.index = idx;
  if (subIdx !== null) input.dataset.subindex = subIdx;
  return input;
}

function createCheckboxInput(name, checked, idx = null) {
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.name = name;
  input.checked = checked;
  input.className = "toggle-checkbox";
  if (idx !== null) input.dataset.index = idx;
  return input;
}

function buildConfigForm(config, formElement) {
  formElement.innerHTML = '';

  for (const [key, value] of Object.entries(config)) {
    const wrapper = document.createElement('div');
    wrapper.className = "config-item";

    const label = document.createElement('label');
    label.textContent = key;
    label.className = "config-label";

    wrapper.appendChild(label);

    if (typeof value === 'boolean') {
      wrapper.appendChild(createCheckboxInput(key, value));
    } else if (typeof value === 'number') {
      wrapper.appendChild(createNumberInput(key, value));
    } else if (Array.isArray(value)) {
      value.forEach((item, idx) => {
        const row = document.createElement('div');
        row.className = "config-array";

        if (Array.isArray(item)) {
          item.forEach((val, subIdx) => {
            row.appendChild(createNumberInput(key, val, idx, subIdx));
          });
        } else if (typeof item === 'boolean') {
          row.appendChild(createCheckboxInput(key, item, idx));
        } else {
          row.appendChild(createNumberInput(key, item, idx));
        }

        wrapper.appendChild(row);
      });
    }

    formElement.appendChild(wrapper);
  }
}

async function loadGeneralConfig() {
  const res = await fetch('/get-config/general');
  const config = await res.json();
  const form = document.getElementById('general-form');
  buildConfigForm(config, form);
}

async function loadMidiConfig() {
  const res = await fetch('/get-config/midi');
  const config = await res.json();
  const form = document.getElementById('midi-form');
  buildConfigForm(config, form);
}

async function loadDmxConfig() {
  try {
    const res = await fetch('/get-config/dmx');
    const data = await res.json();
    const textarea = document.getElementById('dmx-textarea');
    textarea.value = data.content || '';
  } catch (err) {
    console.error('Error loading DMX config:', err);
    const textarea = document.getElementById('dmx-textarea');
    textarea.value = '// Error loading DMX config';
  }
}

async function loadAllConfigs() {
  await Promise.all([
    loadGeneralConfig(),
    loadMidiConfig(),
    loadDmxConfig()
  ]);
}

function parseFormConfig(formElement) {
  const inputs = formElement.querySelectorAll('input');
  const config = {};

  inputs.forEach(input => {
    const key = input.name;
    const idx = input.dataset.index;
    const subIdx = input.dataset.subindex;

    if (input.type === 'checkbox') {
      if (idx !== undefined && idx !== null) {
        if (!Array.isArray(config[key])) config[key] = [];
        config[key][idx] = input.checked;
      } else {
        config[key] = input.checked;
      }
    } else if (input.type === 'number') {
      const num = parseInt(input.value);
      if (idx !== undefined && idx !== null) {
        if (!Array.isArray(config[key])) config[key] = [];
        if (subIdx !== undefined && subIdx !== null) {
          config[key][idx] = config[key][idx] ?? [];
          config[key][idx][subIdx] = num;
        } else {
          config[key][idx] = num;
        }
      } else {
        config[key] = num;
      }
    }
  });

  return config;
}

document.getElementById('save-button').addEventListener('click', async () => {
  try {
    // Parse and save general config
    const generalConfig = parseFormConfig(document.getElementById('general-form'));
    await fetch('/save-config/general', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(generalConfig)
    });

    // Parse and save midi config
    const midiConfig = parseFormConfig(document.getElementById('midi-form'));
    await fetch('/save-config/midi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(midiConfig)
    });

    // Save dmx config (raw text)
    const dmxContent = document.getElementById('dmx-textarea').value;
    await fetch('/save-config/dmx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: dmxContent })
    });

    alert('All configurations saved successfully!');
  } catch (err) {
    console.error('Error saving configs:', err);
    alert('Error saving configurations. Check console for details.');
  }
});

// Initial load
loadAllConfigs();

async function pollForMount(retries = 60, delay = 2000) {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`/get-config-setting?config_option=OPZ_MOUNT_PATH`);
      const data = await res.json();

      if (data["config_value"]) {
        await loadAllConfigs();
        return;
      }
    } catch (err) {
      console.error("Failed to check mount path:", err);
    }
    await new Promise(r => setTimeout(r, delay));
  }

  console.warn("Mount path not found after polling.");
}
pollForMount();
