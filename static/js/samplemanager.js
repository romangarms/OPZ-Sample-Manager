let storageUsed = 0;
let TOTAL_STORAGE = 32000; // 32 MB total storage
let numSamples = 0;
let MAX_SAMPLES = 40; // maximum number of samples allowed

function updateStorageDisplay() {
    // Update the storage info display
    const storagePercentElem = document.getElementById("storage-percent");
    const percent = ((storageUsed / TOTAL_STORAGE) * 100).toFixed(1);
    storagePercentElem.textContent = `${percent}%`;

    const storageUsedElem = document.getElementById("storage-used");
    storageUsedElem.textContent = `${(storageUsed / 1024).toFixed(1)} KB`;

    const storageFreeElem = document.getElementById("storage-free");
    const freeSpace = TOTAL_STORAGE - storageUsed;
    storageFreeElem.textContent = `${(freeSpace / 1024).toFixed(1)} KB`;

    //samples
    const samplesPercentElem = document.getElementById("samples-percent");
    const samplesPercent = ((numSamples / MAX_SAMPLES) * 100).toFixed(1);
    samplesPercentElem.textContent = `${samplesPercent}%`;

    const samplesUsedElem = document.getElementById("samples-used");
    samplesUsedElem.textContent = `${numSamples}`;

    const samplesFreeElem = document.getElementById("samples-free");
    const freeSamples = MAX_SAMPLES - numSamples;
    samplesFreeElem.textContent = `${freeSamples}`;
}


async function fetchOpzSamples() {
    try {
        const response = await fetch("http://localhost:5000/read-samples");
        if (!response.ok) {
            throw new Error("Network response was not ok: " + response.statusText);
        }
        const data = await response.json();

        storageUsed = 0;
        numSamples = 0;

        // Clear existing slots
        data.categories.forEach((category, catIndex) => {
            const container = document.getElementById(category);

            // Preserve the heading if it exists
            const heading = container.querySelector("h3");
            container.innerHTML = ""; // clear previous content
            if (heading) {
                container.appendChild(heading);
            }

            data.sampleData[catIndex].forEach((slot, slotIndex) => {
                const slotDiv = document.createElement("div");
                slotDiv.classList.add("sampleslot");
                slotDiv.setAttribute("draggable", "true");
                slotDiv.dataset.category = category;
                slotDiv.dataset.slot = slotIndex;

                // Enable dragging from this slot
                slotDiv.addEventListener("dragstart", (e) => {
                    e.dataTransfer.setData("text/plain", JSON.stringify({
                        category,
                        slot: slotIndex,
                        path: slot.path
                    }));
                });

                // Allow dropping into another slot
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

                    // If files are being dropped, let the box handler deal with it
                    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                        return;
                    }

                    const textData = e.dataTransfer.getData("text/plain");
                    if (!textData) return; // No data to process

                    const droppedData = JSON.parse(textData);
                    const fromPath = droppedData.path;

                    if (!fromPath || (droppedData.category === category && droppedData.slot == slotIndex)) return;

                    const formData = new FormData();
                    formData.append("source_path", fromPath);
                    formData.append("target_category", category);
                    formData.append("target_slot", slotIndex);

                    try {
                        const response = await fetch("http://localhost:5000/move-sample", {
                            method: "POST",
                            body: formData
                        });

                        if (!response.ok) throw new Error("Move failed");

                        // Refresh the entire UI to reflect all changes
                        await fetchOpzSamples();
                    } catch (err) {
                        console.error("Failed to move sample:", err);
                        alert("Could not move sample.");
                    }
                });

                // Display sample info
                const filename = slot.filename || "(empty)";
                const filesize = slot.filesize ? ` (${(slot.filesize / 1024).toFixed(1)} KB)` : "";
                if (typeof slot.filename === "string" && slot.filename !== "(empty)" && !slot.filename.startsWith("~")) {
                    numSamples++;
                }
                if (slot.filesize) {
                    storageUsed += slot.filesize / 1024; // accumulate storage used in KB
                }
                const text = document.createElement("span");
                text.textContent = `Slot ${slotIndex + 1}: ${filename}${filesize}`;
                updateStorageDisplay()

                // Delete button
                const deleteBtn = document.createElement("button");
                deleteBtn.textContent = "✕";
                deleteBtn.classList.add("delete-btn");
                deleteBtn.onclick = async () => {
                    const samplePath = slot.path;
                    if (!samplePath) return;

                    const confirmed = confirm(`Delete sample?\n${samplePath}`);
                    if (!confirmed) return;

                    try {
                        const res = await fetch("http://localhost:5000/delete-sample", {
                            method: "DELETE",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify({ path: samplePath })
                        });

                        if (!res.ok) throw new Error("Delete failed");

                        slot.path = null;
                        text.textContent = `Slot ${slotIndex + 1}: (empty)`;
                    } catch (err) {
                        console.error("Failed to delete sample:", err);
                        alert("Could not delete sample.");
                    }
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


document.querySelectorAll(".samplepackbox").forEach(box => {
    box.addEventListener("dragover", (e) => {
        e.preventDefault(); // allow drop
    });

    box.addEventListener("drop", async (e) => {
        e.preventDefault();

        const files = e.dataTransfer.files;
        if (files.length === 0) return;

        const file = files[0]; // assume only one file for now
        const category = box.id;

        // Find the nearest .sampleslot under the cursor
        const slotElement = document.elementFromPoint(e.clientX, e.clientY)?.closest(".sampleslot");
        if (!slotElement) return;

        const slot = slotElement.dataset.slot;

        // Upload the file to the backend
        const formData = new FormData();
        formData.append("file", file);
        formData.append("category", category);
        formData.append("slot", slot);

        try {
            const response = await fetch("http://localhost:5000/upload-sample", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                throw new Error("Upload failed");
            }

            await response.json();
            // Refresh the entire UI to reflect the new sample
            await fetchOpzSamples();
        } catch (err) {
            console.error("Failed to upload file:", err);
            alert("Upload failed.");
        }
    });
});

async function pollForMount(retries = 60, delay = 2000) {
    for (let i = 0; i < retries; i++) {
        try {
            const res = await fetch(`/get-config-setting?config_option=OPZ_MOUNT_PATH`);
            const data = await res.json();

            if (data["config_value"]) {
                await fetchOpzSamples();
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

// Prevent default drag-and-drop behavior on the whole page
window.addEventListener("dragover", (e) => {
    e.preventDefault();
});

window.addEventListener("drop", (e) => {
    e.preventDefault();
});

async function openOpzDirectory() {
    try {
        const response = await fetch("http://localhost:5000/open-opz-directory");
        if (!response.ok) {
            throw new Error("Failed to open directory");
        }
    } catch (error) {
        console.error("Failed to open OP-Z directory:", error);
        alert("Could not open OP-Z directory.");
    }
}