// Trusted checker adapter. The document never receives Node, filesystem or CDP access.
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL, fileURLToPath} from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
const policy = JSON.parse(await readFile(path.join(directory, 'policy.json'), 'utf8'));
const require = createRequire(path.join(process.env.REMEDY_HTML_TOOLS_ROOT || directory, 'package.json'));
const pa11yRequire = createRequire(require.resolve('pa11y/package.json'));
const puppeteer = (await import(pathToFileURL(pa11yRequire.resolve('puppeteer')).href)).default;
const manifest = JSON.parse(await readFile(path.join(directory, 'assets.json'), 'utf8'));
for (const [asset, expected] of Object.entries(manifest)) {
  const bytes = await readFile(require.resolve(asset));
  if (createHash('sha256').update(bytes).digest('hex') !== expected) throw new Error('Local checker asset integrity failure');
}

let source = '';
process.stdin.setEncoding('utf8'); // preserve multibyte characters across pipe chunks
for await (const chunk of process.stdin) {
  source += chunk;
  if (Buffer.byteLength(source) > policy.max_document_bytes * 6 + 4096) throw new Error('Input limit exceeded');
}
const {html, tool, executablePath} = JSON.parse(source);
if (Buffer.byteLength(html) > policy.max_document_bytes) throw new Error('HTML byte limit exceeded');
if (!['axe', 'pa11y', 'lighthouse'].includes(tool)) throw new Error('Unsupported checker');
if (process.getuid?.() === 0) throw new Error('Non-root Chromium sandbox required');

let browser;
let timer;
try {
  const work = async () => {
    browser = await puppeteer.launch({executablePath, headless: true, timeout: 30000,
      args: ['--host-resolver-rules=MAP * ~NOTFOUND', '--dns-prefetch-disable', '--disable-background-networking'],
      env: {PATH: process.env.PATH, HOME: process.env.HOME, LANG: 'C.UTF-8'}});
    const page = await browser.newPage();
    let blocked = false;
    let navigations = 0;
    await page.setRequestInterception(true);
    page.on('request', request => {
      if (navigations === 0 && request.url() === policy.document_url && request.isNavigationRequest() && request.frame() === page.mainFrame()) {
        navigations++;
        void request.respond({status: 200, body: html, headers: {'content-type': 'text/html; charset=utf-8',
          'content-security-policy': policy.csp, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff'}});
      } else if (request.url().startsWith('data:')) {
        void request.continue(); // embedded bytes only; CSP restricts their resource type
      } else {
        blocked = true;
        void request.abort('blockedbyclient');
      }
    });
    await page.evaluateOnNewDocument(() => {
      window.__remedyPolicyBlocked = false;
      document.addEventListener('securitypolicyviolation', () => { window.__remedyPolicyBlocked = true; });
    });
    const complete = async () => {
      if (blocked || page.url() !== policy.document_url || await page.evaluate(selector => window.__remedyPolicyBlocked === true || !!document.querySelector(selector), policy.incomplete_selector)) {
        throw new Error('Offline HTML resource policy blocked content; evaluation incomplete');
      }
    };
    await page.goto(policy.document_url, {waitUntil: 'networkidle0', timeout: 30000});
    await complete();
    let result;
    if (tool === 'axe') {
      await page.evaluate(await readFile(require.resolve('axe-core/axe.min.js'), 'utf8'));
      result = await page.evaluate(() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']}}));
    } else if (tool === 'pa11y') {
      const pa11y = (await import(pathToFileURL(require.resolve('pa11y')).href)).default;
      result = (await pa11y(policy.document_url, {browser, page, ignoreUrl: true, standard: 'WCAG2AA', timeout: 30000})).issues;
    } else {
      const {snapshot} = await import(pathToFileURL(require.resolve('lighthouse')).href);
      const observation = await snapshot(page, {flags: {onlyCategories: ['accessibility'], logLevel: 'error', disableFullPageScreenshot: true}});
      result = observation?.lhr;
      if (!result || result.runtimeError) throw new Error('Lighthouse did not complete');
    }
    await complete();
    return result;
  };
  const result = await Promise.race([work(), new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('HTML checker deadline exceeded')), policy.timeout_seconds * 1000);
  })]);
  const output = JSON.stringify(result);
  if (Buffer.byteLength(output) > 8 * 1024 * 1024) throw new Error('Checker output limit exceeded');
  process.stdout.write(output);
} catch {
  // Do not echo document text, raw tool errors, paths or credentials.
  process.stderr.write('HTML checker unavailable or incomplete under offline resource policy\n');
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  if (browser) await browser.close();
}
