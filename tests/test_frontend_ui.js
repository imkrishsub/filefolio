/**
 * Small web UI defects found in the 2026-09-29 walkthrough (T039).
 *
 * Fails hard (non-zero exit) and uses the real app.js, index.html and
 * i18n.json. Run with: node tests/test_frontend_ui.js
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', 'frontend');
const src = fs.readFileSync(path.join(root, 'static', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'templates', 'index.html'), 'utf8');
const i18n = JSON.parse(fs.readFileSync(path.join(root, 'static', 'i18n.json'), 'utf8'));

function extract(name) {
    const m = src.match(new RegExp(`\\n(?:async )?function ${name}\\([\\s\\S]*?\\n\\}`));
    assert.ok(m, `app.js should define ${name}()`);
    return m[0];
}

function extractConst(name) {
    // \r?: a Windows checkout has CRLF line endings.
    const m = src.match(new RegExp(`\\nconst ${name} = [\\s\\S]*?;\\r?\\n`));
    assert.ok(m, `app.js should define const ${name}`);
    return m[0];
}

const fns = ['escapeHtml', 'displayName', 'createDocumentCard', 'pdfToolDownloadName', 'formatErrorDetail'];
const app = new Function(
    't', 'translateTag', 'translateCategory', 'selectedDocuments',
    [extractConst('PLACEHOLDER_THUMBNAIL'), extractConst('PDF_TOOL_DOWNLOAD_SUFFIX'), ...fns.map(extract)].join('\n') +
        `\nreturn { PLACEHOLDER_THUMBNAIL, ${fns.join(', ')} };`
)(x => x, x => x, x => x, new Set());

const doc = {
    id: 3,
    auto_filename: 'stadtwerke-electricity-bill-september-2026.pdf',
    original_filename: 'scan_0012.pdf',
    category: 'Invoice',
    tags: [],
    thumbnail: null,
};

function testPlaceholderThumbnailExists() {
    const file = path.join(root, 'static', path.basename(app.PLACEHOLDER_THUMBNAIL));
    assert.ok(fs.existsSync(file), `${app.PLACEHOLDER_THUMBNAIL} must exist`);
    assert.ok(!src.includes('placeholder.png'), 'no references to the missing placeholder.png');
}

function testCardWithoutThumbnailUsesPlaceholderAndCannotLoop() {
    const card = app.createDocumentCard(doc);
    assert.ok(card.includes(`src="${app.PLACEHOLDER_THUMBNAIL}"`), 'card should show the placeholder');
    const onerror = card.match(/onerror="([^"]*)"/)[1];
    assert.ok(onerror.startsWith('this.onerror = null;'), 'onerror must disable itself before swapping src');
}

function testFaviconIsLinkedAndExists() {
    const m = html.match(/<link rel="icon"[^>]*href="\/static\/([^"]+)"/);
    assert.ok(m, 'index.html should link a favicon');
    assert.ok(fs.existsSync(path.join(root, 'static', m[1])), `${m[1]} must exist`);
}

function testKofiLinkIsTranslatedTextNotAnImage() {
    assert.ok(!html.includes('ko-fi.com/img/'), 'no third-party image: it cannot be translated');
    assert.ok(/class="kofi-link"[\s\S]*?data-i18n="header\.support"/.test(html), 'Ko-fi label should be translated');
}

function testNewStringsExistInEveryLanguage() {
    for (const [lang, table] of Object.entries(i18n)) {
        for (const key of ['header.support', 'upload.queued']) {
            assert.ok(table[key], `${lang} is missing ${key}`);
        }
    }
    assert.strictEqual(i18n.de['header.support'], 'Unterstützen Sie mich auf Ko-fi');
}

function testDownloadOnlyNamesFollowTheDocument() {
    assert.strictEqual(app.pdfToolDownloadName('extract', doc, false), 'stadtwerke-electricity-bill-september-2026-pages.pdf');
    assert.strictEqual(app.pdfToolDownloadName('delete_pages', doc, false), 'stadtwerke-electricity-bill-september-2026-edited.pdf');
    assert.strictEqual(app.pdfToolDownloadName('merge', doc, false), 'stadtwerke-electricity-bill-september-2026-merged.pdf');
    assert.strictEqual(app.pdfToolDownloadName('split', doc, true), 'stadtwerke-electricity-bill-september-2026-split.zip');
    assert.strictEqual(
        app.pdfToolDownloadName('extract', { auto_filename: null, original_filename: 'Scan.PDF' }, false),
        'Scan-pages.pdf'
    );
    assert.strictEqual(app.pdfToolDownloadName('extract', undefined, false), 'document-pages.pdf');
}

function testBatchUploadShowsEveryFile() {
    // Rows are created for all files before the first upload starts, and are
    // only removed once the whole batch has finished.
    const handleFiles = extract('handleFiles');
    assert.ok(/pdfFiles\.map\(file => createUploadRow\(file\)\)[\s\S]*await uploadFile\(/.test(handleFiles),
        'all rows should be created before uploading');
    assert.ok(!extract('uploadFile').includes('.remove()'), 'uploadFile must not remove its own row');
    assert.ok(!/Date\.now\(\)/.test(extract('createUploadRow')), 'row ids must not collide within a batch');
}

function testSettingsStatusReplacesEarlierMessages() {
    assert.ok(extract('showSettingsStatus').includes('settingsStatus.replaceChildren(messageDiv)'));
}

function testValidationErrorsReadCleanly() {
    // Server-side markup rejection (T038 follow-up) reaches the edit dialog.
    const detail = [{ msg: 'Value error, tags must not contain < or >' }];
    assert.strictEqual(app.formatErrorDetail(detail, 'fallback'), 'tags must not contain < or >');
    assert.strictEqual(app.formatErrorDetail('plain', 'fallback'), 'plain');
    assert.strictEqual(app.formatErrorDetail(undefined, 'fallback'), 'fallback');
    assert.ok(/formatErrorDetail\(detail\.detail, 'Failed to update document'\)/.test(extract('saveDocumentChanges')),
        'the edit dialog should show the server reason');
}

const tests = [
    testValidationErrorsReadCleanly,
    testPlaceholderThumbnailExists,
    testCardWithoutThumbnailUsesPlaceholderAndCannotLoop,
    testFaviconIsLinkedAndExists,
    testKofiLinkIsTranslatedTextNotAnImage,
    testNewStringsExistInEveryLanguage,
    testDownloadOnlyNamesFollowTheDocument,
    testBatchUploadShowsEveryFile,
    testSettingsStatusReplacesEarlierMessages,
];
let failed = 0;
for (const test of tests) {
    try {
        test();
        console.log(`ok   ${test.name}`);
    } catch (err) {
        failed++;
        console.error(`FAIL ${test.name}: ${err.message}`);
    }
}
process.exit(failed ? 1 : 0);
