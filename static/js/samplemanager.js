// Current device selection
let currentDevice = 'opz';

// OP-Z specific variables
let opzStorageUsed = 0;
let OPZ_TOTAL_STORAGE = 24000; // 24 MB total storage in KB
let opzNumSamples = 0;

// OP-1 specific variables
let op1Data = null;
const OP1_TOTAL_STORAGE = 512000; // 512 MB in KB
const OP1_DRUM_LIMIT = 42;
const OP1_SYNTH_LIMIT = 42;
const OP1_PATCH_LIMIT = 100;

// ============================================
// Device Tab Management
// ============================================

async function initDeviceTabs() {
    // Load saved device from config
    try {
        const res = await fetch('/get-config-setting?config_option=SELECTED_DEVICE');
        const data = await res.json();
        if (data.config_value && (data.config_value === 'opz' || data.config_value === 'op1')) {
            currentDevice = data.config_value;
        }
    } catch (err) {
        console.error('Failed to load device setting:', err);
    }

    // Set up tab click handlers
    document.querySelectorAll('.device-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const device = tab.dataset.device;
            switchDevice(device);
        });
    });

    // Initialize the correct device view
    switchDevice(currentDevice);
}

async function switchDevice(device) {
    currentDevice = device;

    // Update tab active states
    document.querySelectorAll('.device-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.device === device);
    });

    // Toggle container visibility
    const opzContainer = document.getElementById('opz-container');
    const op1Container = document.getElementById('op1-container');

    if (device === 'opz') {
        opzContainer.hidden = false;
        op1Container.hidden = true;
        await fetchOpzSamples();
    } else {
        opzContainer.hidden = true;
        op1Container.hidden = false;
        await fetchOp1Samples();
    }

    // Save device selection to config
    try {
        await fetch('/set-config-setting', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_option: 'SELECTED_DEVICE', config_value: device })
        });
    } catch (err) {
        console.error('Failed to save device setting:', err);
    }
}

async function openDirectory() {
    try {
        const response = await fetch(`/open-device-directory?device=${currentDevice}`);
        if (!response.ok) {
            throw new Error("Failed to open directory");
        }
    } catch (error) {
        console.error(`Failed to open ${currentDevice.toUpperCase()} directory:`, error);
        alert(`Could not open ${currentDevice === 'opz' ? 'OP-Z' : 'OP-1'} directory.`);
    }
}

// ============================================
// Shared Functions
// ============================================

/**
 * Update storage display for a device
 * @param {string} device - "opz" or "op1"
 * @param {object} storage - Storage object with 'used' and 'total' in KB
 * @param {object} extraData - Optional extra data (counts for OP-1, numSamples for OP-Z)
 */
function updateStorageDisplay(device, storage, extraData = {}) {
    const prefix = device === 'op1' ? 'op1' : 'opz';
    const used = storage.used;
    const total = storage.total;

    const percent = ((used / total) * 100).toFixed(1);
    const percentNum = parseFloat(percent);

    const storageUsedElem = document.getElementById(`${prefix}-storage-used`);
    if (storageUsedElem) {
        storageUsedElem.textContent = `${(used / 1024).toFixed(1)} MB`;  // KB to MB
    }

    const storageFreeElem = document.getElementById(`${prefix}-storage-free`);
    const freeSpace = total - used;
    if (storageFreeElem) {
        storageFreeElem.textContent = `${(freeSpace / 1024).toFixed(1)} MB`;  // KB to MB
    }

    // Device-specific count displays
    if (device === 'op1' && extraData.counts) {
        const counts = extraData.counts;
        const drumSamplesElem = document.getElementById("op1-drum-samples");
        if (drumSamplesElem) {
            drumSamplesElem.textContent = `${counts.drum_samples} / ${OP1_DRUM_LIMIT}`;
        }

        const synthSamplesElem = document.getElementById("op1-synth-samples");
        if (synthSamplesElem) {
            synthSamplesElem.textContent = `${counts.synth_samples} / ${OP1_SYNTH_LIMIT}`;
        }

        const patchesElem = document.getElementById("op1-patches");
        if (patchesElem) {
            patchesElem.textContent = `${counts.patches} / ${OP1_PATCH_LIMIT}`;
        }
    } else if (device === 'opz' && extraData.numSamples !== undefined) {
        const samplesUsedElem = document.getElementById("opz-samples-used");
        if (samplesUsedElem) {
            samplesUsedElem.textContent = `${extraData.numSamples}`;
        }
    }

    let colorClass = 'storage-low';
    if (percentNum >= 85) {
        colorClass = 'storage-high';
    } else if (percentNum >= 60) {
        colorClass = 'storage-medium';
    }

    const storageBarFill = document.getElementById(`${prefix}-storage-bar-fill`);
    const storageBarLabel = document.getElementById(`${prefix}-storage-bar-label`);
    if (storageBarFill) {
        storageBarFill.style.width = `${percent}%`;
        storageBarFill.classList.remove('storage-low', 'storage-medium', 'storage-high');
        storageBarFill.classList.add(colorClass);
    }
    if (storageBarLabel) {
        storageBarLabel.textContent = `Storage: ${percent}%`;
    }

    if (storageFreeElem) {
        storageFreeElem.classList.remove('storage-low', 'storage-medium', 'storage-high');
        storageFreeElem.classList.add(colorClass);
    }
}

/**
 * Delete a sample from any device
 * @param {string} device - "opz" or "op1"
 * @param {string} path - Full path to the sample
 * @param {function} refreshCallback - Function to call after successful deletion
 */
async function deleteSample(device, path, refreshCallback) {
    const filename = path.split('/').pop();
    const confirmed = confirm(`Delete "${filename}"?`);
    if (!confirmed) return;

    try {
        const response = await fetch('/delete-sample', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path, device: device })
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to delete file');
        }

        if (refreshCallback) {
            await refreshCallback();
        }
    } catch (err) {
        console.error('Failed to delete sample:', err);
        alert(`Failed to delete file: ${err.message}`);
    }
}

// ============================================
// OP-Z Functions
// ============================================

async function fetchOpzSamples() {
    try {
        const response = await fetch("/read-samples");
        if (!response.ok) {
            throw new Error("Network response was not ok: " + response.statusText);
        }
        const data = await response.json();

        const errorContainer = document.getElementById("validation-error-container");
        const errorMessage = document.getElementById("validation-error-message");
        const storageInfo = document.getElementById("opz-storage-info");
        const fileList = document.getElementById("opz-file-list");

        if (data.validation_error) {
            errorMessage.innerHTML = data.validation_error + ' <a href="/utilitysettings" class="btn btn-danger">Go to Utility Settings</a>';
            errorContainer.hidden = false;
            if (storageInfo) storageInfo.hidden = true;
            if (fileList) fileList.hidden = true;
            return;
        }

        errorContainer.hidden = true;
        if (storageInfo) storageInfo.hidden = false;
        if (fileList) fileList.hidden = false;

        // Use storage from backend (includes all files under device dir)
        if (data.storage) {
            opzStorageUsed = data.storage.used;
            OPZ_TOTAL_STORAGE = data.storage.total;
        } else {
            opzStorageUsed = 0;
        }
        opzNumSamples = 0;

        data.categories.forEach((category, catIndex) => {
            const container = document.getElementById(category);
            if (!container) return;

            const heading = container.querySelector("h3");
            container.innerHTML = "";
            if (heading) {
                container.appendChild(heading);
            }

            data.sampleData[catIndex].forEach((slot, slotIndex) => {
                const slotDiv = document.createElement("div");
                slotDiv.classList.add("sampleslot");
                slotDiv.setAttribute("draggable", "true");
                slotDiv.dataset.category = category;
                slotDiv.dataset.slot = slotIndex;

                slotDiv.addEventListener("dragstart", (e) => {
                    e.dataTransfer.setData("text/plain", JSON.stringify({
                        category,
                        slot: slotIndex,
                        path: slot.path
                    }));
                });

                slotDiv.addEventListener("dragover", (e) => {
                    e.preventDefault();
                    slotDiv.classList.add("drag-hover");
                });

                slotDiv.addEventListener("dragleave", () => {
                    slotDiv.classList.remove("drag-hover");
                });

                slotDiv.addEventListener("drop", async (e) => {
                    e.preventDefault();
                    slotDiv.classList.remove("drag-hover");

                    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                        return;
                    }

                    const textData = e.dataTransfer.getData("text/plain");
                    if (!textData) return;

                    const droppedData = JSON.parse(textData);
                    const fromPath = droppedData.path;

                    if (!fromPath || (droppedData.category === category && droppedData.slot == slotIndex)) return;

                    const formData = new FormData();
                    formData.append("source_path", fromPath);
                    formData.append("target_category", category);
                    formData.append("target_slot", slotIndex);

                    try {
                        const response = await fetch("/move-sample", {
                            method: "POST",
                            body: formData
                        });

                        if (!response.ok) throw new Error("Move failed");
                        await fetchOpzSamples();
                    } catch (err) {
                        console.error("Failed to move sample:", err);
                        alert("Could not move sample.");
                    }
                });

                const filename = slot.filename || "(empty)";
                const filesize = slot.filesize ? ` (${(slot.filesize / 1024).toFixed(1)} KB)` : "";
                if (typeof slot.filename === "string" && slot.filename !== "(empty)" && !slot.filename.startsWith("~")) {
                    opzNumSamples++;
                }
                const text = document.createElement("span");
                text.textContent = `Slot ${slotIndex + 1}: ${filename}${filesize}`;
                updateStorageDisplay('opz', data.storage, { numSamples: opzNumSamples });

                const deleteBtn = document.createElement("button");
                deleteBtn.textContent = "✕";
                deleteBtn.classList.add("delete-btn");
                deleteBtn.onclick = async () => {
                    const samplePath = slot.path;
                    if (!samplePath) return;
                    await deleteSample('opz', samplePath, fetchOpzSamples);
                };

                slotDiv.appendChild(text);
                slotDiv.appendChild(deleteBtn);
                container.appendChild(slotDiv);
            });
        });

    } catch (error) {
        console.error("Failed to fetch OP-Z samples:", error);
    }
}


// ============================================
// OP-1 Functions
// ============================================

async function fetchOp1Samples() {
    try {
        const response = await fetch("/read-op1-samples");
        if (!response.ok) {
            throw new Error("Network response was not ok: " + response.statusText);
        }
        op1Data = await response.json();

        const errorContainer = document.getElementById("validation-error-container");
        const errorMessage = document.getElementById("validation-error-message");
        const storageInfo = document.getElementById("op1-storage-info");
        const fileList = document.getElementById("op1-file-list");

        if (op1Data.validation_error) {
            errorMessage.innerHTML = op1Data.validation_error + ' <a href="/utilitysettings" class="btn btn-danger">Go to Utility Settings</a>';
            errorContainer.hidden = false;
            if (storageInfo) storageInfo.hidden = true;
            if (fileList) fileList.hidden = true;
            return;
        }

        errorContainer.hidden = true;
        if (storageInfo) storageInfo.hidden = false;
        if (fileList) fileList.hidden = false;

        // Render drum subdirectories
        renderOp1Section('drum', op1Data.drum.subdirectories);

        // Render synth subdirectories
        renderOp1Section('synth', op1Data.synth.subdirectories);

        // Update storage display
        updateStorageDisplay('op1', op1Data.storage, { counts: op1Data.counts });

    } catch (error) {
        console.error("Failed to fetch OP-1 samples:", error);
    }
}

function renderOp1Section(parentFolder, subdirectories) {
    const container = document.getElementById(`op1-${parentFolder}-subdirectories`);
    if (!container) return;

    container.innerHTML = '';

    const sortedSubdirs = Object.keys(subdirectories).sort((a, b) => {
        // Put "user" at the end
        if (a === 'user') return 1;
        if (b === 'user') return -1;
        return a.localeCompare(b);
    });

    if (sortedSubdirs.length === 0) {
        container.innerHTML = '<p class="empty-subdirectory">No folders yet. Click "+ Add Folder" to create one.</p>';
        return;
    }

    sortedSubdirs.forEach(subdirName => {
        const files = subdirectories[subdirName];
        const isReadOnly = subdirName === 'user';

        const subdirDiv = document.createElement('div');
        subdirDiv.classList.add('op1-subdirectory');
        if (isReadOnly) {
            subdirDiv.classList.add('read-only');
        }
        subdirDiv.dataset.path = `${parentFolder}/${subdirName}`;

        // Count samples and patches
        const sampleCount = files.filter(f => f.category !== 'patch').length;
        const patchCount = files.filter(f => f.category === 'patch').length;

        let countText = '';
        if (parentFolder === 'drum') {
            countText = `(${files.length} files)`;
        } else {
            const parts = [];
            if (sampleCount > 0) parts.push(`${sampleCount} sample${sampleCount !== 1 ? 's' : ''}`);
            if (patchCount > 0) parts.push(`${patchCount} patch${patchCount !== 1 ? 'es' : ''}`);
            countText = parts.length > 0 ? `(${parts.join(', ')})` : '(empty)';
        }

        // Header
        const header = document.createElement('div');
        header.classList.add('subdirectory-header');
        header.innerHTML = `
            <span class="expand-icon">▶</span>
            <span class="subdirectory-name">${escapeHtml(subdirName)}</span>
            <span class="sample-count">${countText}</span>
            ${isReadOnly ? '<span class="read-only-badge">Read-only</span>' : `
                <div class="subdirectory-actions">
                    <button class="btn btn-small btn-secondary" onclick="event.stopPropagation(); renameOp1Subdirectory('${parentFolder}/${subdirName}')">Rename</button>
                    <button class="btn btn-small btn-danger" onclick="event.stopPropagation(); deleteOp1Subdirectory('${parentFolder}/${subdirName}')">Delete</button>
                </div>
            `}
        `;

        // Toggle expand/collapse on header click
        header.addEventListener('click', () => {
            const content = subdirDiv.querySelector('.subdirectory-content');
            const icon = header.querySelector('.expand-icon');
            content.classList.toggle('collapsed');
            icon.classList.toggle('expanded');
        });

        // Content (file list)
        const content = document.createElement('div');
        content.classList.add('subdirectory-content', 'collapsed');

        if (files.length === 0) {
            content.innerHTML = '<p class="empty-subdirectory">No files in this folder</p>';
        } else {
            files.forEach(file => {
                const fileDiv = document.createElement('div');
                fileDiv.classList.add('op1-sample');

                const sizeKB = (file.size / 1024).toFixed(1);
                const isPatch = file.category === 'patch';
                const badgeClass = isPatch ? 'patch' : 'sample';
                const badgeText = isPatch ? 'patch' : 'sample';

                fileDiv.innerHTML = `
                    <span class="sample-name">${escapeHtml(file.name)}</span>
                    <span class="sample-size">${sizeKB} KB</span>
                    <span class="sample-type-badge ${badgeClass}">${badgeText}</span>
                    ${!isReadOnly ? `<button class="delete-btn" onclick="deleteSample('op1', '${escapeHtml(file.path)}', fetchOp1Samples)">✕</button>` : ''}
                `;

                content.appendChild(fileDiv);
            });
        }

        subdirDiv.appendChild(header);
        subdirDiv.appendChild(content);
        container.appendChild(subdirDiv);

        // Add drag-and-drop support for files (not for read-only directories)
        if (!isReadOnly) {
            setupOp1SubdirectoryDropZone(subdirDiv, parentFolder, subdirName);
        }
    });

    // Set up drop zone for the whole section (for folder uploads)
    setupOp1SectionDropZone(parentFolder);
}

function setupOp1SubdirectoryDropZone(subdirDiv, parentFolder, subdirName) {
    subdirDiv.addEventListener('dragover', (e) => {
        e.preventDefault();
        subdirDiv.classList.add('drag-hover');
    });

    subdirDiv.addEventListener('dragleave', (e) => {
        if (!subdirDiv.contains(e.relatedTarget)) {
            subdirDiv.classList.remove('drag-hover');
        }
    });

    subdirDiv.addEventListener('drop', async (e) => {
        e.preventDefault();
        subdirDiv.classList.remove('drag-hover');

        const files = e.dataTransfer.files;
        if (files.length === 0) return;

        // Upload files to this subdirectory
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('device', 'op1');
            formData.append('target_path', `${parentFolder}/${subdirName}`);

            try {
                const response = await fetch('/upload-sample', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || 'Upload failed');
                }
            } catch (err) {
                console.error('Failed to upload file:', err);
                alert(`Failed to upload ${file.name}: ${err.message}`);
            }
        }

        // Refresh the view
        await fetchOp1Samples();
    });
}

function setupOp1SectionDropZone(parentFolder) {
    const section = document.getElementById(`op1-${parentFolder}-section`);
    if (!section) return;

    section.addEventListener('dragover', (e) => {
        // Only show drop zone if dragging a folder (has items)
        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
            e.preventDefault();
            section.classList.add('drag-hover');
        }
    });

    section.addEventListener('dragleave', (e) => {
        if (!section.contains(e.relatedTarget)) {
            section.classList.remove('drag-hover');
        }
    });

    section.addEventListener('drop', async (e) => {
        e.preventDefault();
        section.classList.remove('drag-hover');

        const items = e.dataTransfer.items;
        if (!items || items.length === 0) return;

        // Check if this is a folder drop
        const entry = items[0].webkitGetAsEntry ? items[0].webkitGetAsEntry() : null;

        if (entry && entry.isDirectory) {
            // Handle folder drop
            const folderName = entry.name;
            const files = await getFilesFromDirectory(entry);

            if (files.length === 0) {
                alert('The folder is empty.');
                return;
            }

            const formData = new FormData();
            formData.append('parent', parentFolder);
            formData.append('folder_name', folderName);
            files.forEach(file => {
                formData.append('files', file);
            });

            try {
                const response = await fetch('/upload-op1-folder', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || 'Upload failed');
                }

                const result = await response.json();
                if (result.errors && result.errors.length > 0) {
                    alert(`Some files failed to upload: ${result.errors.join(', ')}`);
                }
            } catch (err) {
                console.error('Failed to upload folder:', err);
                alert(`Failed to upload folder: ${err.message}`);
            }

            await fetchOp1Samples();
        }
    });
}

async function getFilesFromDirectory(directoryEntry) {
    const files = [];
    const reader = directoryEntry.createReader();

    return new Promise((resolve) => {
        reader.readEntries(async (entries) => {
            for (const entry of entries) {
                if (entry.isFile) {
                    const file = await new Promise((res) => entry.file(res));
                    files.push(file);
                }
            }
            resolve(files);
        });
    });
}

async function createOp1Subdirectory(parentFolder) {
    const name = prompt(`Enter name for new ${parentFolder} folder:`);
    if (!name) return;

    try {
        const response = await fetch('/create-op1-subdirectory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent: parentFolder, name: name })
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to create folder');
        }

        await fetchOp1Samples();
    } catch (err) {
        console.error('Failed to create subdirectory:', err);
        alert(`Failed to create folder: ${err.message}`);
    }
}

async function renameOp1Subdirectory(path) {
    const parts = path.split('/');
    const currentName = parts[1];
    const newName = prompt(`Enter new name for "${currentName}":`, currentName);
    if (!newName || newName === currentName) return;

    try {
        const response = await fetch('/rename-op1-subdirectory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_path: path, new_name: newName })
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to rename folder');
        }

        await fetchOp1Samples();
    } catch (err) {
        console.error('Failed to rename subdirectory:', err);
        alert(`Failed to rename folder: ${err.message}`);
    }
}

async function deleteOp1Subdirectory(path) {
    const parts = path.split('/');
    const name = parts[1];

    const confirmed = confirm(`Delete folder "${name}" and all its contents?`);
    if (!confirmed) return;

    try {
        const response = await fetch('/delete-op1-subdirectory', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to delete folder');
        }

        await fetchOp1Samples();
    } catch (err) {
        console.error('Failed to delete subdirectory:', err);
        alert(`Failed to delete folder: ${err.message}`);
    }
}

// ============================================
// Utility Functions
// ============================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// OP-Z Drag and Drop Setup
// ============================================

// Set up OP-Z sample box drag-and-drop after DOM loads
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll(".samplepackbox").forEach(box => {
        box.addEventListener("dragover", (e) => {
            e.preventDefault();
        });

        box.addEventListener("drop", async (e) => {
            e.preventDefault();

            const files = e.dataTransfer.files;
            if (files.length === 0) return;

            const file = files[0];
            const category = box.id;

            const slotElement = document.elementFromPoint(e.clientX, e.clientY)?.closest(".sampleslot");
            if (!slotElement) return;

            const slot = slotElement.dataset.slot;

            const formData = new FormData();
            formData.append("file", file);
            formData.append("category", category);
            formData.append("slot", slot);

            try {
                const response = await fetch("/upload-sample", {
                    method: "POST",
                    body: formData
                });

                if (!response.ok) {
                    throw new Error("Upload failed");
                }

                await response.json();
                await fetchOpzSamples();
            } catch (err) {
                console.error("Failed to upload file:", err);
                alert("Upload failed.");
            }
        });
    });
});

// Prevent default drag-and-drop behavior on the whole page
window.addEventListener("dragover", (e) => {
    e.preventDefault();
});

window.addEventListener("drop", (e) => {
    e.preventDefault();
});
