// Drop zone elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const statusDiv = document.getElementById('status');
const documentsList = document.getElementById('documents-list');
const documentsTable = document.getElementById('documents-table');

// Search elements
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search');

// View toggle elements
const gridViewBtn = document.getElementById('grid-view-btn');
const tableViewBtn = document.getElementById('table-view-btn');

// Dark mode toggle
const darkModeToggle = document.getElementById('dark-mode-toggle');

// State
let currentView = 'grid'; // 'grid' or 'table'
let currentSort = { field: 'upload_date', direction: 'desc' };
let documentsData = [];
let allTags = [];
let selectedTags = [];
let currentPreviewDocId = null;
let selectedDocuments = new Set();

// Initialize dark mode from localStorage
const initDarkMode = () => {
    const darkMode = localStorage.getItem('darkMode') === 'true';
    if (darkMode) {
        document.body.classList.add('dark-mode');
    }
};

// Toggle dark mode
darkModeToggle.addEventListener('click', () => {
    document.body.classList.toggle('dark-mode');
    const isDarkMode = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDarkMode);
});

// Initialize
initDarkMode();
loadDocuments();
loadAllTags();

// Click to browse
dropZone.addEventListener('click', () => {
    fileInput.click();
});

// File input change
fileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
});

// Drag & drop handlers
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    handleFiles(e.dataTransfer.files);
});

// Handle file uploads
async function handleFiles(files) {
    const pdfFiles = Array.from(files).filter(file => file.name.endsWith('.pdf'));

    if (pdfFiles.length === 0) {
        showStatus('Please upload PDF files only', 'error');
        return;
    }

    for (const file of pdfFiles) {
        await uploadFile(file);
    }
}

// Upload single file
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    // Create progress bar
    const progressId = 'progress-' + Date.now();
    const progressHtml = `
        <div id="${progressId}" class="upload-progress">
            <div class="upload-progress-header">
                <span class="upload-filename">${file.name}</span>
                <span class="upload-status">Uploading...</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: 0%"></div>
            </div>
        </div>
    `;
    statusDiv.insertAdjacentHTML('beforeend', progressHtml);
    const progressElement = document.getElementById(progressId);
    const progressFill = progressElement.querySelector('.progress-fill');
    const statusText = progressElement.querySelector('.upload-status');

    try {
        // Use XMLHttpRequest for progress tracking
        const xhr = new XMLHttpRequest();

        const uploadPromise = new Promise((resolve, reject) => {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    // Upload progress: 0-90%
                    const percentComplete = (e.loaded / e.total) * 90;
                    progressFill.style.width = percentComplete + '%';
                    statusText.textContent = 'Uploading...';
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    // Parse error response to get detailed message
                    try {
                        const errorData = JSON.parse(xhr.responseText);
                        reject(new Error(errorData.detail || 'Upload failed'));
                    } catch {
                        reject(new Error('Upload failed'));
                    }
                }
            });

            xhr.addEventListener('error', () => reject(new Error('Network error')));
            xhr.addEventListener('abort', () => reject(new Error('Upload cancelled')));

            xhr.open('POST', '/upload');
            xhr.send(formData);
        });

        // Upload complete, now processing
        statusText.textContent = 'Processing (extracting text, running OCR if needed)...';
        progressFill.style.width = '95%';
        progressFill.classList.add('processing');

        const result = await uploadPromise;

        // Processing complete
        progressFill.classList.remove('processing');
        progressFill.style.width = '100%';

        statusText.textContent = 'Complete!';
        progressElement.classList.add('success');

        setTimeout(() => {
            progressElement.remove();
        }, 3000);

        loadDocuments();
    } catch (error) {
        // Check if it's a duplicate error (409 Conflict)
        if (error.message.includes('Duplicate file detected')) {
            statusText.textContent = 'Duplicate detected';
            const duplicateMsg = document.createElement('div');
            duplicateMsg.style.fontSize = '0.85rem';
            duplicateMsg.style.marginTop = '0.25rem';
            duplicateMsg.style.color = 'var(--text-secondary)';
            duplicateMsg.textContent = error.message.replace('Duplicate file detected. ', '');
            progressElement.querySelector('.upload-progress-header').appendChild(duplicateMsg);
        } else {
            statusText.textContent = 'Failed!';
        }

        progressElement.classList.add('error');

        setTimeout(() => {
            progressElement.remove();
        }, 5000);
    }
}

// Search on input (live search with debounce)
let searchTimeout;
searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        loadDocuments();
    }, 300);

    // Show/hide clear button
    clearSearchBtn.style.display = searchInput.value ? 'block' : 'none';
});

// Clear search
clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    clearSearchBtn.style.display = 'none';
    loadDocuments();
});

// View toggle handlers
gridViewBtn.addEventListener('click', () => {
    currentView = 'grid';
    gridViewBtn.classList.add('active');
    tableViewBtn.classList.remove('active');
    renderDocuments();
});

tableViewBtn.addEventListener('click', () => {
    currentView = 'table';
    tableViewBtn.classList.add('active');
    gridViewBtn.classList.remove('active');
    renderDocuments();
});

// Table sorting
documentsTable.addEventListener('click', (e) => {
    const th = e.target.closest('th.sortable');
    if (!th) return;

    const sortField = th.dataset.sort;

    // Toggle direction if clicking same field, otherwise default to ascending
    if (currentSort.field === sortField) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.field = sortField;
        currentSort.direction = 'asc';
    }

    sortDocuments();
    renderDocuments();
    updateSortIndicators();
});

function updateSortIndicators() {
    // Clear all indicators
    documentsTable.querySelectorAll('th').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        const indicator = th.querySelector('.sort-indicator');
        if (indicator) indicator.textContent = '';
    });

    // Set current sort indicator
    const currentTh = documentsTable.querySelector(`th[data-sort="${currentSort.field}"]`);
    if (currentTh) {
        currentTh.classList.add(currentSort.direction === 'asc' ? 'sorted-asc' : 'sorted-desc');
        const indicator = currentTh.querySelector('.sort-indicator');
        if (indicator) {
            indicator.textContent = currentSort.direction === 'asc' ? '▲' : '▼';
        }
    }
}

function sortDocuments() {
    documentsData.sort((a, b) => {
        let aVal = a[currentSort.field];
        let bVal = b[currentSort.field];

        // Handle special cases
        if (currentSort.field === 'tags') {
            aVal = a.tags.join(', ');
            bVal = b.tags.join(', ');
        } else if (currentSort.field === 'original_filename') {
            aVal = a.auto_filename || a.original_filename;
            bVal = b.auto_filename || b.original_filename;
        }

        // String comparison
        if (typeof aVal === 'string' && typeof bVal === 'string') {
            return currentSort.direction === 'asc'
                ? aVal.localeCompare(bVal)
                : bVal.localeCompare(aVal);
        }

        // Default comparison
        if (aVal < bVal) return currentSort.direction === 'asc' ? -1 : 1;
        if (aVal > bVal) return currentSort.direction === 'asc' ? 1 : -1;
        return 0;
    });
}

// Load all available tags
async function loadAllTags() {
    try {
        const response = await fetch('/filters');
        const data = await response.json();
        allTags = data.tags || [];
    } catch (error) {
        console.error('Error loading tags:', error);
    }
}

// Load and display documents
async function loadDocuments() {
    try {
        // Build query parameters
        const params = new URLSearchParams();

        if (searchInput.value) {
            params.append('search', searchInput.value);
        }

        const url = '/documents' + (params.toString() ? '?' + params.toString() : '');
        const response = await fetch(url);
        documentsData = await response.json();

        renderDocuments();
    } catch (error) {
        console.error('Error loading documents:', error);
    }
}

function renderDocuments() {
    const hasSearch = searchInput.value;
    const emptyMessage = hasSearch
        ? 'No documents match your search. Try different keywords.'
        : 'No documents yet. Upload some PDFs to get started!';

    if (currentView === 'grid') {
        documentsList.style.display = 'grid';
        documentsTable.style.display = 'none';

        if (documentsData.length === 0) {
            documentsList.innerHTML = `<p class="empty-state">${emptyMessage}</p>`;
        } else {
            documentsList.innerHTML = documentsData.map(doc => createDocumentCard(doc)).join('');
        }
    } else {
        documentsList.style.display = 'none';
        documentsTable.style.display = 'table';

        const tbody = documentsTable.querySelector('tbody');
        if (documentsData.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="4">
                        <p class="empty-state">${emptyMessage}</p>
                    </td>
                </tr>
            `;
        } else {
            tbody.innerHTML = documentsData.map(doc => createDocumentRow(doc)).join('');
        }
    }
}

// Create document card HTML
function createDocumentCard(doc) {
    const tags = doc.tags.map(tag => `<span class="tag">${tag}</span>`).join('');
    const thumbnailUrl = doc.thumbnail || '/static/placeholder.png';
    const isSelected = selectedDocuments.has(doc.id);

    return `
        <div class="document-card ${isSelected ? 'selected' : ''}" data-doc-id="${doc.id}">
            <div class="document-checkbox">
                <input type="checkbox" class="doc-checkbox" data-doc-id="${doc.id}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleDocumentSelection(${doc.id})">
            </div>
            <img src="${thumbnailUrl}" alt="${doc.auto_filename || doc.original_filename}" class="document-thumbnail" onclick="previewDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}')" style="cursor: pointer;" onerror="this.src='/static/placeholder.png'">
            <div class="document-content" onclick="previewDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <div class="document-header">
                    <div class="document-title">
                        <h3>${doc.auto_filename || doc.original_filename}</h3>
                    </div>
                    <span class="document-category">${doc.category}</span>
                </div>
                ${tags ? `<div class="document-tags">${tags}</div>` : ''}
            </div>
            <div class="document-actions">
                <button class="btn-icon" onclick="event.stopPropagation(); editDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}', '${doc.category}', ${JSON.stringify(doc.tags).replace(/"/g, '&quot;')})" title="Edit document">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button class="btn-icon btn-delete" onclick="event.stopPropagation(); deleteDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}')" title="Delete document">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

// Create document table row HTML
function createDocumentRow(doc) {
    const tags = doc.tags.map(tag => `<span class="tag">${tag}</span>`).join('');
    const displayFilename = doc.auto_filename || doc.original_filename;
    const uploadDate = new Date(doc.upload_date).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
    const isSelected = selectedDocuments.has(doc.id);

    return `
        <tr data-doc-id="${doc.id}">
            <td style="text-align: center;">
                <input type="checkbox" class="doc-checkbox" data-doc-id="${doc.id}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleDocumentSelection(${doc.id})">
            </td>
            <td class="filename-cell" onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <span class="filename-link">${displayFilename}</span>
            </td>
            <td onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <span class="document-category">${doc.category}</span>
            </td>
            <td class="tags-cell" onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">
                ${tags}
            </td>
            <td onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">${uploadDate}</td>
            <td class="actions-cell">
                <button class="btn-icon" onclick="editDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}', '${doc.category}', ${JSON.stringify(doc.tags).replace(/"/g, '&quot;')})" title="Edit document">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button class="btn-icon btn-delete" onclick="deleteDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" title="Delete document">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </td>
        </tr>
    `;
}

// Preview document in modal
function previewDocument(id, filename) {
    currentPreviewDocId = id;
    const modal = document.getElementById('preview-modal');
    const iframe = document.getElementById('pdf-viewer');
    const title = document.getElementById('preview-title');

    title.textContent = filename;
    iframe.src = `/document/${id}`;
    modal.style.display = 'flex';
}

// Close preview modal
function closePreviewModal() {
    const modal = document.getElementById('preview-modal');
    const iframe = document.getElementById('pdf-viewer');
    modal.style.display = 'none';
    iframe.src = '';
    currentPreviewDocId = null;
}

// Download document
function downloadDocument() {
    if (currentPreviewDocId) {
        window.location.href = `/document/${currentPreviewDocId}`;
    }
}

// Open in new tab
function openInNewTab() {
    if (currentPreviewDocId) {
        window.open(`/document/${currentPreviewDocId}`, '_blank');
    }
}

// View document (legacy - for direct access)
function viewDocument(id) {
    window.open(`/document/${id}`, '_blank');
}

// Edit document
function editDocument(id, filename, category, tags) {
    const modal = document.getElementById('edit-modal');
    const form = document.getElementById('edit-form');

    // Populate form
    document.getElementById('edit-doc-id').value = id;
    document.getElementById('edit-filename').value = filename;
    document.getElementById('edit-category').value = category;

    // Set up tags
    selectedTags = Array.isArray(tags) ? [...tags] : [];
    renderSelectedTags();
    setupTagInput();

    // Show modal
    modal.style.display = 'flex';

    // Remove existing listener and add new one
    form.onsubmit = async (e) => {
        e.preventDefault();
        await saveDocumentChanges();
    };
}

// Setup tag input with autocomplete
function setupTagInput() {
    const tagInput = document.getElementById('edit-tags');
    const suggestionsDiv = document.getElementById('tag-suggestions');

    // Remove old listeners
    const newTagInput = tagInput.cloneNode(true);
    tagInput.parentNode.replaceChild(newTagInput, tagInput);

    newTagInput.addEventListener('input', (e) => {
        const value = e.target.value.trim().toLowerCase();

        if (value.length === 0) {
            suggestionsDiv.style.display = 'none';
            return;
        }

        // Filter tags that match and aren't already selected
        const matches = allTags.filter(tag =>
            tag.toLowerCase().includes(value) &&
            !selectedTags.includes(tag)
        );

        if (matches.length > 0) {
            suggestionsDiv.innerHTML = matches.map(tag =>
                `<div class="tag-suggestion" data-tag="${tag}">${tag}</div>`
            ).join('');
            suggestionsDiv.style.display = 'block';

            // Add click handlers to suggestions
            suggestionsDiv.querySelectorAll('.tag-suggestion').forEach(el => {
                el.addEventListener('click', () => {
                    addTag(el.dataset.tag);
                    newTagInput.value = '';
                    suggestionsDiv.style.display = 'none';
                    newTagInput.focus();
                });
            });
        } else {
            suggestionsDiv.style.display = 'none';
        }
    });

    newTagInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            const value = newTagInput.value.trim();
            if (value) {
                addTag(value);
                newTagInput.value = '';
                suggestionsDiv.style.display = 'none';
            }
        } else if (e.key === 'Backspace' && newTagInput.value === '') {
            // Remove last tag on backspace
            if (selectedTags.length > 0) {
                removeTag(selectedTags[selectedTags.length - 1]);
            }
        }
    });

    newTagInput.addEventListener('blur', () => {
        // Delay to allow click on suggestion
        setTimeout(() => {
            suggestionsDiv.style.display = 'none';
        }, 200);
    });
}

// Add tag to selected tags
function addTag(tag) {
    tag = tag.toLowerCase().trim();
    if (tag && !selectedTags.includes(tag)) {
        selectedTags.push(tag);
        renderSelectedTags();
    }
}

// Remove tag from selected tags
function removeTag(tag) {
    selectedTags = selectedTags.filter(t => t !== tag);
    renderSelectedTags();
}

// Render selected tags as pills
function renderSelectedTags() {
    const container = document.getElementById('selected-tags');
    container.innerHTML = selectedTags.map(tag =>
        `<span class="tag-pill">
            ${tag}
            <button type="button" class="tag-remove" data-tag="${tag}">&times;</button>
        </span>`
    ).join('');

    // Add remove handlers
    container.querySelectorAll('.tag-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            removeTag(btn.dataset.tag);
        });
    });
}

// Close edit modal
function closeEditModal() {
    document.getElementById('edit-modal').style.display = 'none';
}

// Save document changes
async function saveDocumentChanges() {
    const docId = document.getElementById('edit-doc-id').value;
    const category = document.getElementById('edit-category').value;

    try {
        const response = await fetch(`/document/${docId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                category: category,
                tags: selectedTags
            })
        });

        if (!response.ok) {
            throw new Error('Failed to update document');
        }

        showStatus('Document updated successfully', 'success');
        closeEditModal();
        loadDocuments();
        loadAllTags(); // Refresh tags list
    } catch (error) {
        showStatus('Error updating document: ' + error.message, 'error');
    }
}

// Delete document
async function deleteDocument(id, filename) {
    if (!confirm(`Are you sure you want to delete "${filename}"? This action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/document/${id}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const errorMessage = errorData.detail || `Server returned ${response.status}`;
            throw new Error(errorMessage);
        }

        showStatus('Document deleted successfully', 'success');
        loadDocuments();
    } catch (error) {
        console.error('Delete error:', error);
        showStatus('Error deleting document: ' + error.message, 'error');
    }
}

// Close modal on outside click
window.onclick = function(event) {
    const editModal = document.getElementById('edit-modal');
    const previewModal = document.getElementById('preview-modal');

    if (event.target === editModal) {
        closeEditModal();
    } else if (event.target === previewModal) {
        closePreviewModal();
    }
}

// Keyboard shortcuts for preview modal
document.addEventListener('keydown', (e) => {
    const previewModal = document.getElementById('preview-modal');
    if (previewModal.style.display === 'flex') {
        if (e.key === 'Escape') {
            closePreviewModal();
        }
    }
});

// Show status message
function showStatus(message, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `status-message ${type}`;
    messageDiv.textContent = message;

    statusDiv.appendChild(messageDiv);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        messageDiv.remove();
    }, 5000);
}

// Toggle document selection
function toggleDocumentSelection(docId) {
    if (selectedDocuments.has(docId)) {
        selectedDocuments.delete(docId);
    } else {
        selectedDocuments.add(docId);
    }
    updateSelectionUI();
}

// Update selection UI (button visibility and checkbox states)
function updateSelectionUI() {
    const downloadBtn = document.getElementById('download-selected-btn');
    const downloadBtnText = document.getElementById('download-btn-text');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');

    // Show/hide download button
    if (selectedDocuments.size > 0) {
        downloadBtn.style.display = 'flex';
        downloadBtnText.textContent = `Download (${selectedDocuments.size})`;
    } else {
        downloadBtn.style.display = 'none';
    }

    // Update select all checkbox
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = documentsData.length > 0 && selectedDocuments.size === documentsData.length;
        selectAllCheckbox.indeterminate = selectedDocuments.size > 0 && selectedDocuments.size < documentsData.length;
    }

    // Update card/row styles
    document.querySelectorAll('.document-card').forEach(card => {
        const docId = parseInt(card.dataset.docId);
        if (selectedDocuments.has(docId)) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    });
}

// Select all documents
const selectAllCheckbox = document.getElementById('select-all-checkbox');
if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            documentsData.forEach(doc => selectedDocuments.add(doc.id));
        } else {
            selectedDocuments.clear();
        }
        renderDocuments();
        updateSelectionUI();
    });
}

// Download selected documents
const downloadSelectedBtn = document.getElementById('download-selected-btn');
if (downloadSelectedBtn) {
    downloadSelectedBtn.addEventListener('click', async () => {
        if (selectedDocuments.size === 0) return;

        const docIds = Array.from(selectedDocuments);

        try {
            if (docIds.length === 1) {
                // Single file - download as PDF directly
                const doc = documentsData.find(d => d.id === docIds[0]);
                const filename = doc.auto_filename || doc.original_filename;

                // Use file system access API
                if ('showSaveFilePicker' in window) {
                    const handle = await window.showSaveFilePicker({
                        suggestedName: filename,
                        types: [{
                            description: 'PDF Files',
                            accept: { 'application/pdf': ['.pdf'] }
                        }]
                    });

                    const response = await fetch(`/download/${docIds[0]}`);
                    const blob = await response.blob();
                    const writable = await handle.createWritable();
                    await writable.write(blob);
                    await writable.close();

                    showStatus('Document downloaded successfully', 'success');
                    selectedDocuments.clear();
                    renderDocuments();
                    updateSelectionUI();
                } else {
                    // Fallback for browsers without showSaveFilePicker
                    window.location.href = `/download/${docIds[0]}`;
                    selectedDocuments.clear();
                    renderDocuments();
                    updateSelectionUI();
                }
            } else {
                // Multiple files - download as ZIP
                if ('showSaveFilePicker' in window) {
                    const handle = await window.showSaveFilePicker({
                        suggestedName: `documents_${new Date().toISOString().split('T')[0]}.zip`,
                        types: [{
                            description: 'ZIP Archives',
                            accept: { 'application/zip': ['.zip'] }
                        }]
                    });

                    showStatus(`Preparing ${docIds.length} documents for download...`, 'info');

                    const response = await fetch('/download/multiple', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ document_ids: docIds })
                    });

                    if (!response.ok) throw new Error('Download failed');

                    const blob = await response.blob();
                    const writable = await handle.createWritable();
                    await writable.write(blob);
                    await writable.close();

                    showStatus('Documents downloaded successfully', 'success');
                    selectedDocuments.clear();
                    renderDocuments();
                    updateSelectionUI();
                } else {
                    // Fallback for browsers without showSaveFilePicker
                    showStatus(`Preparing ${docIds.length} documents for download...`, 'info');

                    const response = await fetch('/download/multiple', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ document_ids: docIds })
                    });

                    if (!response.ok) throw new Error('Download failed');

                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `documents_${new Date().toISOString().split('T')[0]}.zip`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    a.remove();

                    showStatus('Documents downloaded successfully', 'success');
                    selectedDocuments.clear();
                    renderDocuments();
                    updateSelectionUI();
                }
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                // User cancelled the file picker
                return;
            }
            console.error('Download error:', error);
            showStatus('Error downloading documents: ' + error.message, 'error');
        }
    });
}
