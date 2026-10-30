import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {retain} from './retain.mjs';
const require=createRequire(path.join(process.env.REMEDY_HTML_TOOLS_ROOT,'package.json'));
const pa11yRequire=createRequire(require.resolve('pa11y/package.json'));
const puppeteer=(await import(pathToFileURL(pa11yRequire.resolve('puppeteer')).href)).default;
const launch=puppeteer.launch.bind(puppeteer);
puppeteer.launch=async(...args)=>{
 const browser=await launch(...args);const newPage=browser.newPage.bind(browser);
 browser.newPage=async(...args)=>{
  const page=await newPage(...args);const goto=page.goto.bind(page);
  page.goto=async(...args)=>{const value=await goto(...args);await retain(process.env.PROOF_TOOL);return value;};
  return page;
 };
 return browser;
};
