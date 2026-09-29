/**
 * Guards against stored XSS in the document list.
 *
 * Filenames and tags come from LLM output (shaped by document text) and from
 * PUT /document/{id}, so they must never reach innerHTML unescaped, and must
 * never be spliced into inline event-handler JavaScript.
 *
 * Unlike tests/test_frontend.js this file fails hard (non-zero exit), and it
 * exercises the real functions from app.js rather than local copies.
 * Run with: node tests/test_frontend_escaping.js
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '../frontend/static/app.js'), 'utf8');

function extract(name) {
    const m = src.match(new RegExp(`\\nfunction ${name}\\([\\s\\S]*?\\n\\}`));
    assert.ok(m, `app.js should define ${name}()`);
    return m[0];
}

const fns = ['escapeHtml', 'displayName', 'createDocumentCard', 'createDocumentRow'];
const load = new Function(
    't', 'translateTag', 'translateCategory', 'selectedDocuments',
    fns.map(extract).join('\n') + `\nreturn { ${fns.join(', ')} };`
);
const identity = x => x;
const app = load(identity, identity, identity, new Set());

const PAYLOAD = `x"><img src=x onerror=alert(1)>'); alert(2);//`;
const evilDoc = {
    id: 7,
    auto_filename: PAYLOAD,
    original_filename: 'evil.pdf',
    category: '<b onmouseover=alert(3)>Tax</b>',
    tags: ['<img src=x onerror=alert(4)>', `tag"onmouseover="alert(5)`],
    thumbnail: null,
    upload_date: '2026-09-29T09:00:00',
};

function testEscapeHtml() {
    assert.strictEqual(app.escapeHtml('normal.pdf'), 'normal.pdf');
    assert.strictEqual(
        app.escapeHtml(`<a href="x">'&'</a>`),
        '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;'
    );
    assert.strictEqual(app.escapeHtml(null), '');
    assert.strictEqual(app.escapeHtml(undefined), '');
    assert.strictEqual(app.escapeHtml(42), '42');
}

function assertSafe(html, where) {
    assert.ok(!/<img src=x/.test(html), `${where}: injected <img> must be escaped`);
    assert.ok(!/<b onmouseover/.test(html), `${where}: injected category markup must be escaped`);
    // Escaped payload text may still read "onerror=" - only a real quote makes it an attribute.
    assert.ok(!/on(error|mouseover)="alert/i.test(html), `${where}: no injected event-handler attributes`);

    const handlers = [...html.matchAll(/\son\w+="([^"]*)"/g)].map(m => m[1]);
    assert.ok(handlers.length > 0, `${where}: expected inline handlers to inspect`);
    for (const h of handlers) {
        assert.ok(!h.includes('alert'), `${where}: payload leaked into handler: ${h}`);
    }
    assert.ok(html.includes('&lt;img src=x onerror=alert(4)&gt;'), `${where}: tag text should still be shown, escaped`);
}

function testCardEscapesDocumentFields() {
    const html = app.createDocumentCard(evilDoc);
    assertSafe(html, 'card');
    assert.ok(html.includes('x&quot;&gt;&lt;img src=x onerror=alert(1)&gt;'), 'card title should show the escaped name');
}

function testRowEscapesDocumentFields() {
    assertSafe(app.createDocumentRow(evilDoc), 'row');
}

function testHandlersPassOnlyTheDocumentId() {
    const html = app.createDocumentCard({ ...evilDoc, auto_filename: "o'brien.pdf" });
    for (const fn of ['previewDocument', 'editDocument', 'deleteDocument']) {
        assert.ok(html.includes(`${fn}(7)`), `${fn} should be called with the id only`);
    }
}

function testDisplayNameFallsBackToOriginal() {
    assert.strictEqual(app.displayName({ auto_filename: null, original_filename: 'a.pdf' }), 'a.pdf');
    assert.strictEqual(app.displayName({ auto_filename: 'b.pdf', original_filename: 'a.pdf' }), 'b.pdf');
}

function testOtherSinksEscape() {
    // Upload progress (local filename), tag suggestions and pills, sync folder paths.
    assert.ok(/upload-filename">\$\{escapeHtml\(file\.name\)\}/.test(src), 'upload progress should escape file.name');
    assert.ok(/data-tag="\$\{escapeHtml\(tag\)\}">\$\{escapeHtml\(tag\)\}/.test(src), 'tag suggestions should escape');
    assert.ok(/\$\{escapeHtml\(tag\)\}\s*<button type="button" class="tag-remove" data-tag="\$\{escapeHtml\(tag\)\}"/.test(src),
        'selected tag pills should escape');
    assert.ok(src.includes('<span>${escapeHtml(folder.source_path)}</span>'), 'sync folder path should escape');
}

const tests = [
    testEscapeHtml,
    testCardEscapesDocumentFields,
    testRowEscapesDocumentFields,
    testHandlersPassOnlyTheDocumentId,
    testDisplayNameFallsBackToOriginal,
    testOtherSinksEscape,
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
