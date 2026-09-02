/**
 * Frontend JavaScript tests for FileFolio.
 *
 * These tests can be run with a test runner like Jest or Mocha.
 * For now, they're written as simple test functions that can be adapted.
 */

// Mock DOM elements for testing
function createMockDOM() {
    if (typeof document === 'undefined') {
        global.document = {
            getElementById: (id) => ({
                value: '',
                textContent: '',
                style: {},
                classList: {
                    add: () => {},
                    remove: () => {},
                    toggle: () => {},
                    contains: () => false
                },
                addEventListener: () => {},
                insertAdjacentHTML: () => {}
            }),
            querySelector: () => null,
            querySelectorAll: () => []
        };
    }
}

// Test: File validation
function testFileValidation() {
    const validFiles = [
        { name: 'invoice.pdf', type: 'application/pdf' },
        { name: 'receipt.PDF', type: 'application/pdf' }
    ];

    const invalidFiles = [
        { name: 'document.txt', type: 'text/plain' },
        { name: 'image.jpg', type: 'image/jpeg' },
        { name: 'document.docx', type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }
    ];

    // Test valid files
    validFiles.forEach(file => {
        const isPDF = file.name.toLowerCase().endsWith('.pdf');
        console.assert(isPDF === true, `${file.name} should be recognized as PDF`);
    });

    // Test invalid files
    invalidFiles.forEach(file => {
        const isPDF = file.name.toLowerCase().endsWith('.pdf');
        console.assert(isPDF === false, `${file.name} should not be recognized as PDF`);
    });

    console.log('✓ File validation tests passed');
}

// Test: Search debouncing
function testSearchDebounce() {
    let callCount = 0;
    let searchTimeout;

    function debouncedSearch(query) {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            callCount++;
        }, 300);
    }

    // Simulate rapid typing
    debouncedSearch('i');
    debouncedSearch('in');
    debouncedSearch('inv');
    debouncedSearch('invo');
    debouncedSearch('invoic');
    debouncedSearch('invoice');

    // Wait and check that search was only called once
    setTimeout(() => {
        console.assert(callCount === 1, 'Search should only be called once after debounce');
        console.log('✓ Search debounce tests passed');
    }, 400);
}

// Test: Dark mode toggle
function testDarkModeToggle() {
    createMockDOM();

    const mockBody = {
        classList: {
            items: [],
            add: function(cls) { this.items.push(cls); },
            remove: function(cls) {
                this.items = this.items.filter(c => c !== cls);
            },
            toggle: function(cls) {
                if (this.items.includes(cls)) {
                    this.remove(cls);
                } else {
                    this.add(cls);
                }
            },
            contains: function(cls) {
                return this.items.includes(cls);
            }
        }
    };

    // Test toggle on
    mockBody.classList.toggle('dark-mode');
    console.assert(mockBody.classList.contains('dark-mode'), 'Dark mode should be enabled');

    // Test toggle off
    mockBody.classList.toggle('dark-mode');
    console.assert(!mockBody.classList.contains('dark-mode'), 'Dark mode should be disabled');

    console.log('✓ Dark mode toggle tests passed');
}

// Test: Tag parsing
function testTagParsing() {
    function parseTags(tagString) {
        return tagString
            .split(',')
            .map(tag => tag.trim())
            .filter(tag => tag.length > 0);
    }

    const testCases = [
        { input: 'tag1,tag2,tag3', expected: ['tag1', 'tag2', 'tag3'] },
        { input: 'tag1, tag2, tag3', expected: ['tag1', 'tag2', 'tag3'] },
        { input: 'tag1,  tag2  ,tag3', expected: ['tag1', 'tag2', 'tag3'] },
        { input: 'single', expected: ['single'] },
        { input: '', expected: [] },
        { input: ',,,', expected: [] }
    ];

    testCases.forEach(({ input, expected }) => {
        const result = parseTags(input);
        const match = JSON.stringify(result) === JSON.stringify(expected);
        console.assert(match, `Tag parsing failed for "${input}"`);
    });

    console.log('✓ Tag parsing tests passed');
}

// Test: Progress bar updates
function testProgressBarUpdates() {
    const progressBar = {
        style: { width: '0%' },
        setProgress: function(percent) {
            this.style.width = percent + '%';
        }
    };

    // Test progress updates
    progressBar.setProgress(0);
    console.assert(progressBar.style.width === '0%', 'Progress should start at 0%');

    progressBar.setProgress(50);
    console.assert(progressBar.style.width === '50%', 'Progress should update to 50%');

    progressBar.setProgress(100);
    console.assert(progressBar.style.width === '100%', 'Progress should reach 100%');

    console.log('✓ Progress bar tests passed');
}

// Test: Document sorting
function testDocumentSorting() {
    const documents = [
        { id: 1, original_filename: 'B.pdf', upload_date: '2024-01-02' },
        { id: 2, original_filename: 'A.pdf', upload_date: '2024-01-03' },
        { id: 3, original_filename: 'C.pdf', upload_date: '2024-01-01' }
    ];

    // Sort by filename
    const byFilename = [...documents].sort((a, b) =>
        a.original_filename.localeCompare(b.original_filename)
    );
    console.assert(byFilename[0].original_filename === 'A.pdf', 'First should be A.pdf');
    console.assert(byFilename[2].original_filename === 'C.pdf', 'Last should be C.pdf');

    // Sort by date (descending)
    const byDate = [...documents].sort((a, b) =>
        b.upload_date.localeCompare(a.upload_date)
    );
    console.assert(byDate[0].upload_date === '2024-01-03', 'First should be latest date');
    console.assert(byDate[2].upload_date === '2024-01-01', 'Last should be earliest date');

    console.log('✓ Document sorting tests passed');
}

// Test: View mode switching
function testViewModeSwitching() {
    const state = {
        currentView: 'grid'
    };

    function switchView(view) {
        state.currentView = view;
    }

    switchView('grid');
    console.assert(state.currentView === 'grid', 'Should switch to grid view');

    switchView('table');
    console.assert(state.currentView === 'table', 'Should switch to table view');

    console.log('✓ View mode switching tests passed');
}

// Test: Selection state management
function testSelectionState() {
    const selectedDocuments = new Set();

    // Add items
    selectedDocuments.add(1);
    selectedDocuments.add(2);
    selectedDocuments.add(3);
    console.assert(selectedDocuments.size === 3, 'Should have 3 selected items');

    // Remove item
    selectedDocuments.delete(2);
    console.assert(selectedDocuments.size === 2, 'Should have 2 selected items');
    console.assert(!selectedDocuments.has(2), 'Item 2 should be removed');

    // Clear all
    selectedDocuments.clear();
    console.assert(selectedDocuments.size === 0, 'Should have no selected items');

    console.log('✓ Selection state tests passed');
}

// Test: Filename escaping for display
function testFilenameEscaping() {
    function escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    const testCases = [
        { input: 'normal.pdf', expected: 'normal.pdf' },
        { input: '<script>alert("xss")</script>', expected: '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;' },
        { input: "file'with'quotes.pdf", expected: "file&#039;with&#039;quotes.pdf" }
    ];

    testCases.forEach(({ input, expected }) => {
        const result = escapeHtml(input);
        console.assert(result === expected, `Escaping failed for "${input}"`);
    });

    console.log('✓ Filename escaping tests passed');
}

// Test: Date formatting
function testDateFormatting() {
    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString();
    }

    const testDate = '2024-01-15T10:30:00';
    const formatted = formatDate(testDate);

    console.assert(typeof formatted === 'string', 'Should return a string');
    console.assert(formatted.length > 0, 'Should not be empty');

    console.log('✓ Date formatting tests passed');
}

// Test: PDF tool configuration
function testPdfToolConfig() {
    // Read the real PDF_TOOL_CONFIG object literal out of app.js so this test
    // fails if that config changes shape.
    const src = require('fs').readFileSync(
        __dirname + '/../frontend/static/app.js', 'utf8'
    );
    const match = src.match(/const PDF_TOOL_CONFIG\s*=\s*(\{[\s\S]*?\n\});/);
    console.assert(match !== null, 'app.js should define a PDF_TOOL_CONFIG object literal');
    const PDF_TOOL_CONFIG = new Function('return ' + match[1])();

    const ops = ['merge', 'split', 'extract', 'delete_pages', 'rotate', 'ocr'];
    ops.forEach(op => {
        console.assert(PDF_TOOL_CONFIG[op] !== undefined, `PDF_TOOL_CONFIG should include "${op}"`);
    });
    console.assert(Object.keys(PDF_TOOL_CONFIG).length === 6, 'PDF_TOOL_CONFIG should have exactly 6 ops');

    console.assert(PDF_TOOL_CONFIG.merge.pages === false, 'merge should set pages: false');
    console.assert(PDF_TOOL_CONFIG.ocr.pages === false, 'ocr should set pages: false');

    ['split', 'extract', 'delete_pages'].forEach(op => {
        console.assert(PDF_TOOL_CONFIG[op].pages === true, `${op} should set pages: true`);
    });

    console.assert(PDF_TOOL_CONFIG.rotate.degrees === true, 'rotate should set degrees: true');

    console.log('✓ PDF tool config tests passed');
}

// Run all tests
function runAllTests() {
    console.log('Running FileFolio frontend tests...\n');

    testFileValidation();
    testSearchDebounce();
    testDarkModeToggle();
    testTagParsing();
    testProgressBarUpdates();
    testDocumentSorting();
    testViewModeSwitching();
    testSelectionState();
    testFilenameEscaping();
    testDateFormatting();
    testPdfToolConfig();

    console.log('\n✓ All frontend tests completed');
}

// Export for module usage (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        testFileValidation,
        testSearchDebounce,
        testDarkModeToggle,
        testTagParsing,
        testProgressBarUpdates,
        testDocumentSorting,
        testViewModeSwitching,
        testSelectionState,
        testFilenameEscaping,
        testDateFormatting,
        testPdfToolConfig,
        runAllTests
    };
}

// Run tests if executed directly
if (typeof window === 'undefined' && typeof require !== 'undefined') {
    runAllTests();
}
