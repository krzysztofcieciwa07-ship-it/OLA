'use strict';
// Minimal DOM for isolated tests that execute the real inline page scripts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../../web/index.html'), 'utf8');
class Element {
  constructor(id = '') {
    Object.assign(this, {id, value: '', textContent: '', disabled: false, children: []});
    this.listeners = new Map();
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value), remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle(value, enabled) {
        const active = enabled ?? !classes.has(value);
        if (active) classes.add(value); else classes.delete(value);
        return active;
      },
    };
  }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  dispatch(type) {
    for (const callback of this.listeners.get(type) || []) callback({preventDefault() {}});
  }
  replaceChildren(...children) {
    this.children = children; this.textContent = '';
    if (children[0]?.value !== undefined) this.value = children[0].value;
  }
  appendChild(child) { child.parent = this; this.children.push(child); }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  get firstElementChild() { return this.children[0]; }
  get lastElementChild() { return this.children.at(-1); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
}
function createDom() {
  const elements = new Map();
  for (const match of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    element.disabled = /\sdisabled(?:\s|>|=)/.test(match[0]);
    elements.set(element.id, element);
  }
  const el = id => {
    assert.ok(elements.has(id), `Unknown element ${id}`);
    return elements.get(id);
  };
  return {el, document: {getElementById: el, querySelectorAll: () => [], createElement: () => new Element()}};
}
function inlineScript(marker) {
  const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
    .map(match => match[1]).find(text => text.includes(marker));
  assert.ok(script, `Missing inline script: ${marker}`);
  return script;
}
const response = (body, status = 200) => ({ok: status >= 200 && status < 300, status, async json() { return body; }});
const drain = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
module.exports = {createDom, inlineScript, response, drain, deferred};
