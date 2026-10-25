// 本地浏览器测试：独立模拟验签与到期检查，不连接或修改真实 AWS。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const { chromium } = require('playwright');

const projectRoot = path.resolve(__dirname, '..');
const dist = path.join(projectRoot, 'dist');
const config = JSON.parse(fs.readFileSync(path.join(projectRoot, 'config/cloudfront-invitation.json'), 'utf8'));
const origin = 'https://' + config.distributionDomain;
const keyDirectory = path.join(projectRoot, '.local/cloudfront');
const publicKey = fs.readFileSync(path.join(keyDirectory, 'public-key.pem'));
const privateKey = fs.readFileSync(path.join(keyDirectory, 'private-key.pem'));
const fromCF = value => Buffer.from(value.replace(/-/g, '+').replace(/_/g, '=').replace(/~/g, '/'), 'base64');
const toCF = bytes => Buffer.from(bytes).toString('base64').replace(/\+/g, '-').replace(/=/g, '_').replace(/\//g, '~');
const texts = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(dist, 'invite/content.js'), 'utf8'), texts);
const translations = texts.window.INVITATION_TEXT;
assert.deepEqual(Object.keys(translations.ja).sort(), Object.keys(translations.zh).sort());
assert.deepEqual(Object.keys(translations.ja).sort(), Object.keys(translations.en).sort());

function mint({ expiry = Math.floor(Date.now() / 1000) + 600, resource = origin + '/*', keyId = config.publicKeyId } = {}) {
  const policy = Buffer.from(JSON.stringify({ Statement: [{ Resource: resource, Condition: { DateLessThan: { 'AWS:EpochTime': expiry } } }] }));
  const signature = crypto.sign('RSA-SHA256', policy, privateKey);
  return origin + config.entryPath + '#v=1&p=' + toCF(policy) + '&s=' + toCF(signature) + '&k=' + keyId;
}
function verifyCookieHeader(header) {
  try {
    const cookies = Object.fromEntries(header.split(';').map(item => {
      const at = item.indexOf('=');
      return [item.slice(0, at).trim(), item.slice(at + 1)];
    }));
    if (cookies['CloudFront-Key-Pair-Id'] !== config.publicKeyId || cookies['CloudFront-Hash-Algorithm'] !== 'SHA256') return false;
    const policy = fromCF(cookies['CloudFront-Policy']);
    if (!crypto.verify('RSA-SHA256', policy, publicKey, fromCF(cookies['CloudFront-Signature']))) return false;
    const parsed = JSON.parse(policy);
    const statement = parsed.Statement[0];
    return parsed.Statement.length === 1 && statement.Resource === origin + '/*' &&
      statement.Condition.DateLessThan['AWS:EpochTime'] > Date.now() / 1000;
  } catch { return false; }
}

const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.webp': 'image/webp', '.svg': 'image/svg+xml' };
async function addMock(context, { failProbe = false } = {}) {
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    assert.equal(url.origin, origin, '测试不应访问其他站点');
    const pathname = decodeURIComponent(url.pathname);
    if (failProbe && pathname === '/index.html' && request.method() === 'HEAD') return route.abort();
    const headers = await request.allHeaders();
    if (!pathname.startsWith('/invite/') && !verifyCookieHeader(headers.cookie || '')) {
      return route.fulfill({ status: 403, contentType: 'application/xml', body: '<Error><Code>AccessDenied</Code></Error>' });
    }
    const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
    const file = path.resolve(dist, relative);
    if (!file.startsWith(dist + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      return route.fulfill({ status: 404, body: 'Not found' });
    }
    await route.fulfill({ status: 200, contentType: types[path.extname(file)] || 'application/octet-stream',
      body: request.method() === 'HEAD' ? '' : fs.readFileSync(file) });
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.INVITATION_BROWSER_CHANNEL ? { channel: process.env.INVITATION_BROWSER_CHANNEL } : {}) });
  let count = 0;
  async function scenario(name, action, options = {}) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    try {
      await addMock(context, options);
      await action(context);
      console.log('PASS ' + name);
      count++;
    } finally { await context.close(); }
  }
  try {
    const invitationFiles = fs.readdirSync(keyDirectory).filter(file => /^invitation-.*\.txt$/.test(file)).sort();
    assert.ok(invitationFiles.length, '先运行 New-PortfolioInvitation.ps1');
    const generatedLink = fs.readFileSync(path.join(keyDirectory, invitationFiles.at(-1)), 'utf8').trim();
    const generatedParams = new URL(generatedLink).hash.slice(1);
    const params = new URLSearchParams(generatedParams);
    assert.equal(params.get('k'), config.publicKeyId);
    assert.ok(crypto.verify('RSA-SHA256', fromCF(params.get('p')), publicKey, fromCF(params.get('s'))));
    const deadline = JSON.parse(fromCF(params.get('p'))).Statement[0].Condition.DateLessThan['AWS:EpochTime'];
    assert.ok(deadline - Date.now() / 1000 > 29 * 86400 && deadline - Date.now() / 1000 <= 30 * 86400);

    await scenario('没有凭证时首页、个人文案和照片都被拒绝', async context => {
      const page = await context.newPage();
      for (const resource of ['/', '/index.html', '/content.js', '/assets/photos/IMG_8655.webp']) {
        const response = await page.goto(origin + resource);
        assert.equal(response.status(), 403);
      }
    });
    await scenario('入口缺少凭证的三语提示及移动排版', async context => {
      const page = await context.newPage();
      await page.goto(origin + config.entryPath);
      await page.waitForFunction(() => document.querySelector('#message').textContent.length > 0);
      for (const language of ['ja', 'zh', 'en']) {
        await page.locator(`[data-lang="${language}"]`).click();
        assert.equal(await page.locator('#message').textContent(), translations[language].missing);
      }
      await page.locator('[data-lang="zh"]').click();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(keyDirectory, 'invitation-entry-preview.png'), fullPage: true });
    });
    await scenario('PowerShell 生成的链接通过独立验签并加载原站及五张照片', async context => {
      const page = await context.newPage();
      const pageErrors = [];
      page.on('pageerror', error => pageErrors.push(error.message));
      await page.goto(generatedLink);
      await page.waitForURL(origin + '/');
      assert.equal((await context.cookies()).filter(cookie => cookie.name.startsWith('CloudFront-')).length, 4);
      const cookies = await context.cookies();
      for (const cookie of cookies.filter(cookie => cookie.name.startsWith('CloudFront-'))) {
        assert.ok(cookie.secure);
        assert.equal(cookie.sameSite, 'Lax');
        assert.ok(Math.abs(cookie.expires - deadline) <= 2);
      }
      for (const language of ['zh', 'en', 'ja']) {
        await page.locator(`[data-lang="${language}"]`).click();
        assert.equal(await page.locator('html').getAttribute('lang'), language);
      }
      for (const image of await page.locator('#photo-gallery img').all()) {
        await image.scrollIntoViewIfNeeded();
        await image.evaluate(element => element.decode());
      }
      await page.waitForFunction(() => [...document.querySelectorAll('#photo-gallery img')].length === 5 &&
        [...document.querySelectorAll('#photo-gallery img')].every(image => image.complete && image.naturalWidth > 0));
      assert.deepEqual(pageErrors, []);
    });
    await scenario('同一原始链接可在另一新浏览器使用', async context => {
      const page = await context.newPage();
      await page.goto(generatedLink);
      await page.waitForURL(origin + '/');
    });
    await scenario('过期凭证显示到期提示且不设置 Cookie', async context => {
      const page = await context.newPage();
      await page.goto(mint({ expiry: Math.floor(Date.now() / 1000) - 60 }));
      await page.waitForFunction(() => document.querySelector('#message').textContent.includes('有効期限'));
      assert.equal(new URL(page.url()).hash, '');
      assert.equal((await context.cookies()).length, 0);
    });
    await scenario('篡改有效期但保留旧签名，被独立验签端拒绝并清除凭证', async context => {
      const link = new URL(mint());
      const p = new URLSearchParams(link.hash.slice(1));
      const altered = JSON.parse(fromCF(p.get('p')));
      altered.Statement[0].Condition.DateLessThan['AWS:EpochTime'] += 86400;
      p.set('p', toCF(Buffer.from(JSON.stringify(altered))));
      link.hash = p.toString();
      const page = await context.newPage();
      await page.goto(link.href);
      await page.waitForFunction(() => document.querySelector('#message').textContent.includes('アクセスを確認'));
      assert.equal((await context.cookies()).length, 0);
      assert.equal(new URL(page.url()).hash, '');
    });
    for (const [name, url] of [
      ['错误公钥 ID', mint({ keyId: 'WRONGKEY' })],
      ['授权到另一个域名', mint({ resource: 'https://other.example/*' })],
      ['畸形凭证', origin + config.entryPath + '#v=1&p=%3Cscript%3E&s=x&k=x']
    ]) {
      await scenario(name + '不触发放行', async context => {
        const page = await context.newPage();
        await page.goto(url);
        await page.waitForFunction(() => document.querySelector('#message').textContent.includes('招待リンクを確認できません'));
        assert.equal((await context.cookies()).length, 0);
      });
    }
    await scenario('浏览器拒绝 Cookie 时给出提示', async context => {
      await context.addInitScript(() => Object.defineProperty(Document.prototype, 'cookie', { get: () => '', set: () => {} }));
      const page = await context.newPage();
      await page.goto(mint());
      await page.waitForFunction(() => document.querySelector('#message').textContent.includes('Cookie'));
    });
    await scenario('网络失败不放行且清除凭证', async context => {
      const page = await context.newPage();
      await page.goto(mint());
      await page.waitForFunction(() => document.querySelector('#message').textContent.includes('接続を確認できません'));
      assert.equal((await context.cookies()).length, 0);
    }, { failProbe: true });
    console.log(`Completed ${count} local scenarios; real AWS integration remains to be verified.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message.replace(/#[^\s"']+/g, '#<redacted>')); process.exitCode = 1; });
