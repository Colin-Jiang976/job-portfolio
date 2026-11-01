// 仅在.local中创建隔离材料配置；不修改dist或调用AWS。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const cp = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const directory = fs.mkdtempSync(path.join(root, '.local', 'document-config-check-'));
const checker = path.join(__dirname, 'check_site_content.cjs');
const records = [];
function check(name, config, expected, files = {}) {
  const dir = path.join(directory, name); fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, 'documents.js'), 'window.PORTFOLIO_DOCUMENTS = ' + JSON.stringify(config) + ';');
  for (const [file, bytes] of Object.entries(files)) {
    const target = path.join(dir, file); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, bytes);
  }
  const run = cp.spawnSync(process.execPath, [checker, dir], { encoding: 'utf8' });
  const result = JSON.parse(run.stdout); assert.equal(result.ok, expected, name);
  records.push({ name, passed: true, expectedAccepted: expected, errors: result.errors });
}
check('not-provided', {resume:null,career:null}, true);
check('provided-file', {resume:'documents/example.pdf',career:null}, true, {'documents/example.pdf':'%PDF-1.4\n%%EOF\n'});
check('missing-file', {resume:'documents/missing.pdf',career:null}, false);
check('external-url', {resume:'https://example.invalid/resume.pdf',career:null}, false);
check('path-traversal', {resume:'documents/../example.pdf',career:null}, false);
check('wrong-file-header', {resume:'documents/example.pdf',career:null}, false, {'documents/example.pdf':'Not a PDF'});
check('unknown-slot', {resume:null,career:null,other:null}, false);
const context = {window:{}};
new vm.Script(fs.readFileSync(path.join(root,'dist/content.js'),'utf8')).runInNewContext(context);
const expectedRole = {ja:'クラウド・インフラ設計・構築',zh:'云与基础设施相关岗位',en:'Cloud & infrastructure roles'};
for (const lang of ['ja','zh','en']) assert.equal(context.window.PORTFOLIO_TEXT[lang].roleValue,expectedRole[lang]);
records.push({name:'existing-role-values-preserved',passed:true});
fs.writeFileSync(path.join(directory,'results.json'),JSON.stringify({scope:'local document configuration and existing role text only',records},null,2));
console.log(JSON.stringify({ok:true,checks:records.length,directory},null,2));
