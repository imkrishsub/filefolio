// Drop zone elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const statusDiv = document.getElementById('status');
const documentsList = document.getElementById('documents-list');
const documentsTable = document.getElementById('documents-table');

// Search elements
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search');
const searchLoadingIndicator = document.getElementById('search-loading');

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

// i18n state
let currentLanguage = 'en';
let translations = {};

// i18n functions
async function loadTranslations() {
    try {
        const response = await fetch('/static/i18n.json');
        translations = await response.json();
    } catch (error) {
        console.error('Error loading translations:', error);
    }
}

function detectBrowserLanguage() {
    const browserLang = navigator.language || navigator.userLanguage;
    const langCode = browserLang.split('-')[0];
    return ['en', 'es', 'fr', 'de', 'zh'].includes(langCode) ? langCode : 'en';
}

function initLanguage() {
    const savedLang = localStorage.getItem('language');
    currentLanguage = savedLang || detectBrowserLanguage();

    // Set the language selector value
    const languageSelect = document.getElementById('language-select');
    if (languageSelect) {
        languageSelect.value = currentLanguage;
    }

    updatePageLanguage();
}

function setLanguage(lang) {
    console.log('Switching language to:', lang);
    currentLanguage = lang;
    localStorage.setItem('language', lang);
    console.log('Translations available:', Object.keys(translations));
    console.log('Sample translation (category.invoice):', t('category.invoice'));
    updatePageLanguage();
}

function t(key, params = {}) {
    if (!translations[currentLanguage]) {
        console.warn('No translations loaded for language:', currentLanguage);
        return key;
    }
    let text = translations[currentLanguage]?.[key] || translations['en']?.[key] || key;
    Object.keys(params).forEach(param => {
        text = text.replace(`{${param}}`, params[param]);
    });
    return text;
}

function translateCategory(category) {
    if (!category) return '';
    const categoryKey = `category.${category.toLowerCase()}`;
    const translated = t(categoryKey);
    // If translation returns the key itself (meaning no translation found), return original category
    return translated !== categoryKey ? translated : category;
}

function translateTag(tag) {
    // Try to translate tag as a category first
    const categoryKey = `category.${tag.toLowerCase()}`;
    const translated = t(categoryKey);
    // If translation returns the key itself, the tag isn't a category, return original
    return translated !== categoryKey ? translated : tag;
}

// Last /ollama-status payload, kept so the banner can be re-rendered on a
// language switch without re-hitting the endpoint.
let ollamaStatus = null;

function renderOllamaBanner() {
    const banner = document.getElementById('ollama-banner');
    if (!banner) return;

    // No status yet, or everything is working — say nothing.
    if (!ollamaStatus || ollamaStatus.ok) {
        banner.hidden = true;
        banner.textContent = '';
        return;
    }

    const model = ollamaStatus.model || '';
    const isMissingModel = ollamaStatus.reason === 'model_missing';

    const message = document.createElement('div');
    message.textContent = isMissingModel
        ? t('ollama.model_missing', { model })
        : t('ollama.unreachable');

    const hint = document.createElement('code');
    hint.textContent = isMissingModel
        ? `ollama pull ${model}`
        : 'ollama serve';

    banner.textContent = '';
    banner.append(message, hint);
    banner.hidden = false;
}

async function checkOllamaStatus() {
    try {
        const response = await fetch('/ollama-status');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        ollamaStatus = await response.json();
    } catch (error) {
        // The banner exists to explain degraded AI tagging. If the check itself
        // fails we have nothing trustworthy to report, so stay quiet.
        console.warn('Could not check Ollama status:', error);
        ollamaStatus = null;
    }
    renderOllamaBanner();
}

function updatePageLanguage() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        if (element.tagName === 'INPUT' && element.type !== 'checkbox') {
            element.placeholder = t(key);
        } else {
            element.textContent = t(key);
        }
    });

    document.querySelectorAll('[data-i18n-title]').forEach(element => {
        const key = element.getAttribute('data-i18n-title');
        element.title = t(key);
    });

    renderDocuments();
    renderOllamaBanner();
}

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
async function init() {
    // Add page loading class
    document.body.classList.add('page-loading');

    await loadTranslations();
    initLanguage();
    initDarkMode();

    // Setup language selector event listener after translations are loaded
    const languageSelect = document.getElementById('language-select');
    if (languageSelect) {
        languageSelect.addEventListener('change', (e) => {
            setLanguage(e.target.value);
        });
    }

    await loadDocuments(true);
    loadAllTags();
    checkOllamaStatus();

    // Page loaded - trigger fade in animation
    document.body.classList.remove('page-loading');
    document.body.classList.add('page-loaded');
}

init();

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
        showStatus(t('upload.pdf_only'), 'error');
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
                <span class="upload-status">${t('upload.uploading')}</span>
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
                    statusText.textContent = t('upload.uploading');
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
        statusText.textContent = t('upload.processing');
        progressFill.style.width = '95%';
        progressFill.classList.add('processing');

        const result = await uploadPromise;

        // Processing complete
        progressFill.classList.remove('processing');
        progressFill.style.width = '100%';

        statusText.textContent = t('upload.complete');
        progressElement.classList.add('success');

        setTimeout(() => {
            progressElement.remove();
        }, 3000);

        loadDocuments();
    } catch (error) {
        // Check if it's a duplicate error (409 Conflict)
        if (error.message.includes('Duplicate file detected')) {
            statusText.textContent = t('upload.duplicate');
            const duplicateMsg = document.createElement('div');
            duplicateMsg.style.fontSize = '0.85rem';
            duplicateMsg.style.marginTop = '0.25rem';
            duplicateMsg.style.color = 'var(--text-secondary)';
            duplicateMsg.textContent = error.message.replace('Duplicate file detected. ', '');
            progressElement.querySelector('.upload-progress-header').appendChild(duplicateMsg);
        } else {
            statusText.textContent = t('upload.failed');
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
async function loadDocuments(showSkeletons = false) {
    try {
        // Show skeleton loaders if this is initial load
        if (showSkeletons) {
            renderSkeletonLoaders();
        }

        // Show search loading indicator if searching
        const isSearching = searchInput && searchInput.value;
        if (isSearching && searchLoadingIndicator) {
            searchLoadingIndicator.classList.add('active');
        }

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
    } finally {
        // Hide search loading indicator
        if (searchLoadingIndicator) {
            searchLoadingIndicator.classList.remove('active');
        }
    }
}

function renderSkeletonLoaders() {
    const skeletonCount = 6;

    if (currentView === 'grid') {
        documentsList.style.display = 'grid';
        documentsTable.style.display = 'none';

        const skeletons = Array(skeletonCount).fill(0).map(() => `
            <div class="skeleton-card">
                <div class="skeleton skeleton-thumbnail"></div>
                <div class="skeleton skeleton-text"></div>
                <div class="skeleton skeleton-text short"></div>
            </div>
        `).join('');

        documentsList.innerHTML = skeletons;
    } else {
        documentsList.style.display = 'none';
        documentsTable.style.display = 'table';

        const tbody = documentsTable.querySelector('tbody');
        const skeletons = Array(skeletonCount).fill(0).map(() => `
            <tr>
                <td colspan="6">
                    <div class="skeleton skeleton-row"></div>
                </td>
            </tr>
        `).join('');

        tbody.innerHTML = skeletons;
    }
}

function renderDocuments() {
    const hasSearch = searchInput.value;
    const emptyMessage = hasSearch
        ? t('documents.no_results')
        : t('documents.empty');

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
                    <td colspan="6">
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
    const tags = doc.tags.map(tag => `<span class="tag">${translateTag(tag)}</span>`).join('');
    const thumbnailUrl = doc.thumbnail || '/static/placeholder.png';
    const isSelected = selectedDocuments.has(doc.id);
    const translatedCategory = translateCategory(doc.category);

    return `
        <div class="document-card ${isSelected ? 'selected' : ''}" data-doc-id="${doc.id}">
            <div class="document-checkbox">
                <input type="checkbox" class="doc-checkbox" data-doc-id="${doc.id}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleDocumentSelection(${doc.id})">
            </div>
            <img src="${thumbnailUrl}" alt="${doc.auto_filename || doc.original_filename}" class="document-thumbnail loading" onclick="previewDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}')" style="cursor: pointer;" onerror="this.src='/static/placeholder.png'; this.classList.remove('loading'); this.classList.add('loaded');" onload="this.classList.remove('loading'); this.classList.add('loaded');">
            <div class="document-content" onclick="previewDocument(${doc.id}, '${(doc.auto_filename || doc.original_filename).replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <div class="document-header">
                    <div class="document-title">
                        <h3>${doc.auto_filename || doc.original_filename}</h3>
                    </div>
                    <span class="document-category">${translatedCategory}</span>
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
                <div class="tools-menu">
                    <button class="btn-icon" onclick="event.stopPropagation(); toggleToolsMenu(${doc.id})" title="${t('pdf.tools')}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
                    </button>
                    <div class="tools-dropdown" id="tools-dropdown-${doc.id}" hidden>
                        <button onclick="event.stopPropagation(); openPdfTool('rotate', ${doc.id})">${t('pdf.rotate')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('split', ${doc.id})">${t('pdf.split')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('extract', ${doc.id})">${t('pdf.extract')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('delete_pages', ${doc.id})">${t('pdf.delete_pages')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('ocr', ${doc.id})">${t('pdf.ocr')}</button>
                    </div>
                </div>
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
    const tags = doc.tags.map(tag => `<span class="tag">${translateTag(tag)}</span>`).join('');
    const displayFilename = doc.auto_filename || doc.original_filename;
    const uploadDate = new Date(doc.upload_date).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
    const isSelected = selectedDocuments.has(doc.id);
    const translatedCategory = translateCategory(doc.category);

    return `
        <tr data-doc-id="${doc.id}">
            <td style="text-align: center;">
                <input type="checkbox" class="doc-checkbox" data-doc-id="${doc.id}" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleDocumentSelection(${doc.id})">
            </td>
            <td class="filename-cell" onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <span class="filename-link">${displayFilename}</span>
            </td>
            <td onclick="previewDocument(${doc.id}, '${displayFilename.replace(/'/g, "\\'")}')" style="cursor: pointer;">
                <span class="document-category">${translatedCategory}</span>
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
                <div class="tools-menu">
                    <button class="btn-icon" onclick="event.stopPropagation(); toggleToolsMenu(${doc.id})" title="${t('pdf.tools')}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
                    </button>
                    <div class="tools-dropdown" id="tools-dropdown-${doc.id}" hidden>
                        <button onclick="event.stopPropagation(); openPdfTool('rotate', ${doc.id})">${t('pdf.rotate')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('split', ${doc.id})">${t('pdf.split')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('extract', ${doc.id})">${t('pdf.extract')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('delete_pages', ${doc.id})">${t('pdf.delete_pages')}</button>
                        <button onclick="event.stopPropagation(); openPdfTool('ocr', ${doc.id})">${t('pdf.ocr')}</button>
                    </div>
                </div>
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
    const form = document.getElementById('edit-form');
    const submitBtn = form.querySelector('button[type="submit"]');

    // Add loading state to submit button
    if (submitBtn) {
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;
    }

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

        showStatus(t('status.updated'), 'success');
        closeEditModal();
        loadDocuments();
        loadAllTags(); // Refresh tags list
    } catch (error) {
        showStatus(t('error.update_failed') + ': ' + error.message, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
        }
    }
}

// Delete document
async function deleteDocument(id, filename) {
    if (!confirm(t('confirm.delete', { filename }))) {
        return;
    }

    // Find the delete button and add loading state
    const deleteBtn = event?.target?.closest('.btn-delete');
    if (deleteBtn) {
        deleteBtn.classList.add('loading');
        deleteBtn.disabled = true;
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

        showStatus(t('status.deleted'), 'success');
        loadDocuments();
    } catch (error) {
        console.error('Delete error:', error);
        showStatus(t('error.delete_failed') + ': ' + error.message, 'error');
    } finally {
        if (deleteBtn) {
            deleteBtn.classList.remove('loading');
            deleteBtn.disabled = false;
        }
    }
}

// Close modal on outside click
window.onclick = function(event) {
    const editModal = document.getElementById('edit-modal');
    const previewModal = document.getElementById('preview-modal');
    const pdfToolModal = document.getElementById('pdf-tool-modal');

    if (event.target === editModal) {
        closeEditModal();
    } else if (event.target === previewModal) {
        closePreviewModal();
    } else if (event.target === pdfToolModal) {
        closePdfToolModal();
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

// Show status message in settings modal
function showSettingsStatus(message, type) {
    const settingsStatus = document.getElementById('settings-status');
    if (!settingsStatus) return;

    const messageDiv = document.createElement('div');
    messageDiv.className = `status-message ${type}`;
    messageDiv.textContent = message;

    settingsStatus.appendChild(messageDiv);

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
    const mergeBtn = document.getElementById('merge-selected-btn');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');

    // Show/hide download button
    if (selectedDocuments.size > 0) {
        downloadBtn.style.display = 'flex';
        downloadBtnText.textContent = t('button.download_count', { count: selectedDocuments.size });
    } else {
        downloadBtn.style.display = 'none';
    }

    // Show/hide merge button (needs at least two selected documents)
    if (mergeBtn) {
        mergeBtn.style.display = selectedDocuments.size >= 2 ? 'flex' : 'none';
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

        // Add loading state
        downloadSelectedBtn.classList.add('loading');
        downloadSelectedBtn.disabled = true;

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

                    showStatus(t('status.downloaded'), 'success');
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

                    showStatus(t('status.preparing_download', { count: docIds.length }), 'info');

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

                    showStatus(t('status.documents_downloaded'), 'success');
                    selectedDocuments.clear();
                    renderDocuments();
                    updateSelectionUI();
                } else {
                    // Fallback for browsers without showSaveFilePicker
                    showStatus(t('status.preparing_download', { count: docIds.length }), 'info');

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

                    showStatus(t('status.documents_downloaded'), 'success');
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
            showStatus(t('error.download_failed') + ': ' + error.message, 'error');
        } finally {
            // Remove loading state
            downloadSelectedBtn.classList.remove('loading');
            downloadSelectedBtn.disabled = false;
        }
    });
}

// =====================
// Sync Folders Feature
// =====================

// Settings modal functions
function openSettingsModal() {
    const modal = document.getElementById('settings-modal');
    modal.style.display = 'flex';
    loadSyncFolders();
}

function closeSettingsModal() {
    const modal = document.getElementById('settings-modal');
    modal.style.display = 'none';
}

async function loadSyncFolders() {
    try {
        const response = await fetch('/sync-folders');
        const folders = await response.json();

        const listContainer = document.getElementById('sync-folders-list');

        if (folders.length === 0) {
            listContainer.innerHTML = `<p class="empty-state">${t('settings.no_folders')}</p>`;
            return;
        }

        listContainer.innerHTML = folders.map(folder => `
            <div class="sync-folder-item ${folder.enabled ? 'enabled' : 'disabled'}" data-folder-id="${folder.id}">
                <div class="folder-info">
                    <div class="folder-path">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                        <span>${folder.source_path}</span>
                    </div>
                    <div class="folder-status">
                        <span class="status-badge ${folder.is_watching ? 'watching' : 'paused'}">
                            ${folder.is_watching ? t('settings.watching') : t('settings.paused')}
                        </span>
                        ${folder.move_after_processing ? '<span class="move-badge" title="' + t('settings.move_after_processing') + '">📦</span>' : ''}
                        ${folder.last_scan ? '<span class="last-scan">Last scan: ' + new Date(folder.last_scan).toLocaleString() + '</span>' : ''}
                    </div>
                </div>
                <div class="folder-actions">
                    <label class="toggle-switch">
                        <input type="checkbox" ${folder.enabled ? 'checked' : ''} onchange="toggleSyncFolder(${folder.id}, this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                    <button class="btn-icon" onclick="scanSyncFolder(${folder.id})" title="${t('settings.scan_now')}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="23 4 23 10 17 10"></polyline>
                            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                        </svg>
                    </button>
                    <button class="btn-icon btn-danger" onclick="removeSyncFolder(${folder.id})" title="${t('settings.remove_folder')}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading sync folders:', error);
        showSettingsStatus(t('error.loading_failed'), 'error');
    }
}

async function addSyncFolder() {
    const pathInput = document.getElementById('new-folder-path');
    const moveCheckbox = document.getElementById('move-after-processing');
    const addBtn = document.getElementById('add-folder-btn');

    const folderPath = pathInput.value.trim();

    if (!folderPath) {
        showSettingsStatus(t('error.folder_path_required'), 'error');
        return;
    }

    addBtn.disabled = true;
    addBtn.classList.add('loading');

    try {
        const response = await fetch('/sync-folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_path: folderPath,
                enabled: true,
                move_after_processing: moveCheckbox.checked
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || t('error.add_folder_failed'));
        }

        pathInput.value = '';
        moveCheckbox.checked = false;
        loadSyncFolders();
        showSettingsStatus(t('success.folder_added'), 'success');
    } catch (error) {
        console.error('Error adding sync folder:', error);
        showSettingsStatus(error.message, 'error');
    } finally {
        addBtn.disabled = false;
        addBtn.classList.remove('loading');
    }
}

async function toggleSyncFolder(folderId, enabled) {
    try {
        const response = await fetch(`/sync-folders/${folderId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });

        if (!response.ok) {
            throw new Error(t('error.update_failed'));
        }

        loadSyncFolders();
        showSettingsStatus(enabled ? t('success.folder_enabled') : t('success.folder_disabled'), 'success');
    } catch (error) {
        console.error('Error toggling sync folder:', error);
        showSettingsStatus(error.message, 'error');
        loadSyncFolders(); // Reload to reset checkbox
    }
}

async function scanSyncFolder(folderId) {
    try {
        const response = await fetch(`/sync-folders/${folderId}/scan`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(t('error.scan_failed'));
        }

        showSettingsStatus(t('success.scan_started'), 'success');

        // Refresh folder list after a delay to show updated last_scan
        setTimeout(() => loadSyncFolders(), 2000);
    } catch (error) {
        console.error('Error scanning folder:', error);
        showSettingsStatus(error.message, 'error');
    }
}

async function removeSyncFolder(folderId) {
    if (!confirm(t('confirm.remove_folder'))) {
        return;
    }

    try {
        const response = await fetch(`/sync-folders/${folderId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(t('error.remove_failed'));
        }

        loadSyncFolders();
        showSettingsStatus(t('success.folder_removed'), 'success');
    } catch (error) {
        console.error('Error removing sync folder:', error);
        showSettingsStatus(error.message, 'error');
    }
}

// Setup settings button
const settingsBtn = document.getElementById('settings-btn');
if (settingsBtn) {
    settingsBtn.addEventListener('click', openSettingsModal);
}

// Setup add folder button
const addFolderBtn = document.getElementById('add-folder-btn');
if (addFolderBtn) {
    addFolderBtn.addEventListener('click', addSyncFolder);
}

// Close modal on background click
const settingsModal = document.getElementById('settings-modal');
if (settingsModal) {
    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) {
            closeSettingsModal();
        }
    });
}

// Backup and Restore Functions
async function createBackup() {
    const btn = document.getElementById('create-backup-btn');
    if (!btn) return;

    try {
        btn.disabled = true;
        btn.classList.add('loading');
        btn.textContent = t('settings.creating_backup') || 'Creating backup...';

        const response = await fetch('/backup');

        if (!response.ok) {
            throw new Error(t('error.backup_failed'));
        }

        // Download the backup file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;

        // Extract filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        const filename = contentDisposition
            ? contentDisposition.split('filename=')[1].replace(/"/g, '')
            : `filefolio_backup_${new Date().toISOString().slice(0, 10)}.zip`;

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showSettingsStatus(t('success.backup_created'), 'success');
    } catch (error) {
        console.error('Backup error:', error);
        showSettingsStatus(error.message, 'error');
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.textContent = t('settings.create_backup');
    }
}

async function restoreBackup(file) {
    if (!confirm(t('confirm.restore_backup') || 'This will replace all current data! Are you sure?')) {
        return;
    }

    try {
        const formData = new FormData();
        formData.append('file', file);

        showSettingsStatus(t('settings.restoring') || 'Restoring backup...', 'info');

        const response = await fetch('/restore', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || t('error.restore_failed'));
        }

        showSettingsStatus(
            t('success.backup_restored') ||
            `Backup restored! ${data.stats.pdfs_restored} PDFs and ${data.stats.thumbnails_restored} thumbnails restored.`,
            'success'
        );

        // Reload documents after a short delay
        setTimeout(() => {
            loadDocuments();
        }, 1500);

    } catch (error) {
        console.error('Restore error:', error);
        showSettingsStatus(error.message, 'error');
    }
}

// Setup backup/restore buttons
const createBackupBtn = document.getElementById('create-backup-btn');
if (createBackupBtn) {
    createBackupBtn.addEventListener('click', createBackup);
}

const restoreFileInput = document.getElementById('restore-file-input');
if (restoreFileInput) {
    restoreFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            restoreBackup(e.target.files[0]);
            // Reset input so same file can be selected again
            e.target.value = '';
        }
    });
}

// ---------------------------------------------------------------------------
// PDF workbench: per-document Tools menu, merge action, and operation modal
// ---------------------------------------------------------------------------

let pdfToolState = { op: null, docId: null };

function closeAllToolsMenus() {
    document.querySelectorAll('.tools-dropdown').forEach(d => { d.hidden = true; });
}

function toggleToolsMenu(docId) {
    const el = document.getElementById(`tools-dropdown-${docId}`);
    if (!el) return;
    const reopen = el.hidden;
    closeAllToolsMenus();
    if (!reopen) return;

    el.hidden = false;
    // The menu is position:fixed so it escapes the card's overflow:hidden
    // (grid view) and the table cell (list view). Place it from the toggle
    // button's viewport rect, flipping upward when there is little room below.
    const btn = el.previousElementSibling;
    const r = btn.getBoundingClientRect();
    const mh = el.offsetHeight;
    const mw = el.offsetWidth;
    const openUp = (window.innerHeight - r.bottom) < mh + 8 && r.top > mh + 8;
    el.style.top = `${Math.max(4, openUp ? r.top - mh - 4 : r.bottom + 4)}px`;
    el.style.left = `${Math.max(4, Math.min(r.right - mw, window.innerWidth - mw - 4))}px`;
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.tools-menu')) closeAllToolsMenus();
});
// A fixed-positioned menu would drift from its button on scroll/resize.
window.addEventListener('scroll', closeAllToolsMenus, true);
window.addEventListener('resize', closeAllToolsMenus);

const PDF_TOOL_CONFIG = {
    merge:        { pages: false, degrees: false, download: true,  explainer: 'pdf.merge_explainer' },
    split:        { pages: true,  degrees: false, download: true,  explainer: null },
    extract:      { pages: true,  degrees: false, download: true,  explainer: null },
    delete_pages: { pages: true,  degrees: false, download: true,  explainer: null },
    rotate:       { pages: true,  degrees: true,  download: false, explainer: null },
    ocr:          { pages: false, degrees: false, download: false, explainer: 'pdf.ocr_explainer' },
};

function openPdfTool(op, docId = null) {
    if (op === 'merge' && selectedDocuments.size < 2) {
        showStatus(t('pdf.failed'), 'error');
        return;
    }
    pdfToolState = { op, docId };
    const cfg = PDF_TOOL_CONFIG[op];
    document.getElementById('pdf-tool-title').textContent = t(`pdf.modal_title_${op}`);
    const explainer = document.getElementById('pdf-tool-explainer');
    explainer.hidden = !cfg.explainer;
    if (cfg.explainer) explainer.textContent = t(cfg.explainer);
    document.getElementById('pdf-tool-pages-group').hidden = !cfg.pages;
    document.getElementById('pdf-tool-degrees-group').hidden = !cfg.degrees;
    document.getElementById('pdf-tool-download-group').hidden = !cfg.download;
    document.getElementById('pdf-tool-pages').value = op === 'rotate' ? 'all' : '';
    document.getElementById('pdf-tool-download').checked = false;
    const status = document.getElementById('pdf-tool-status');
    status.hidden = true;
    status.textContent = '';
    status.classList.remove('form-status--error');
    document.querySelectorAll('.tools-dropdown').forEach(d => d.hidden = true);
    document.getElementById('pdf-tool-modal').style.display = 'flex';
}

function closePdfToolModal() {
    document.getElementById('pdf-tool-modal').style.display = 'none';
}

const pdfToolForm = document.getElementById('pdf-tool-form');
if (pdfToolForm) {
    pdfToolForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const { op, docId } = pdfToolState;
        const cfg = PDF_TOOL_CONFIG[op];
        const status = document.getElementById('pdf-tool-status');
        const pages = document.getElementById('pdf-tool-pages').value.trim();
        const downloadOnly = cfg.download && document.getElementById('pdf-tool-download').checked;

        let url, body;
        if (op === 'merge') {
            url = '/pdf/merge';
            body = { document_ids: Array.from(selectedDocuments), file: !downloadOnly };
        } else if (op === 'rotate') {
            url = '/pdf/rotate';
            body = {
                document_id: docId,
                degrees: parseInt(document.getElementById('pdf-tool-degrees').value, 10),
                pages: pages || 'all',
            };
        } else if (op === 'ocr') {
            url = '/pdf/ocr';
            body = { document_id: docId };
        } else {
            url = op === 'split' ? '/pdf/split' : (op === 'extract' ? '/pdf/extract' : '/pdf/delete-pages');
            body = op === 'split'
                ? { document_id: docId, ranges: pages, file: !downloadOnly }
                : { document_id: docId, pages, file: !downloadOnly };
        }

        status.hidden = false;
        status.classList.remove('form-status--error');
        status.textContent = t('pdf.working');
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || t('pdf.failed'));
            }
            const ct = resp.headers.get('content-type') || '';
            if (ct.includes('application/pdf') || ct.includes('application/zip')) {
                const blob = await resp.blob();
                const objectUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = objectUrl;
                a.download = ct.includes('zip') ? 'split.zip' : `${op}.pdf`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(objectUrl);
                a.remove();
            }
            status.textContent = t('pdf.done');
            selectedDocuments.clear();
            updateSelectionUI();
            await loadDocuments();
            setTimeout(closePdfToolModal, 600);
        } catch (err) {
            status.classList.add('form-status--error');
            status.textContent = err.message;
        }
    });
}
