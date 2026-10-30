import {createRequire} from 'node:module';
import {retain} from './retain.mjs';
const require=createRequire('/app/package.json');
const {chromium}=require('playwright');
const connect=chromium.connect.bind(chromium);
chromium.connect=async(...args)=>{
 const browser=await connect(...args);const newContext=browser.newContext.bind(browser);
 browser.newContext=async(...args)=>{
  const context=await newContext(...args);const newPage=context.newPage.bind(context);
  context.newPage=async(...args)=>{
   const page=await newPage(...args);const goto=page.goto.bind(page);
   page.goto=async(...args)=>{const value=await goto(...args);await retain('scanner-browser');return value;};
   return page;
  };return context;
 };return browser;
};
