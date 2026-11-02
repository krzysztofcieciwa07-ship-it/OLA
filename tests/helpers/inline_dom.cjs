'use strict';
// Minimal DOM for isolated tests that execute the real inline page scripts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../../web/index.html'), 'utf8');
class Element {
  constructor(id = '') {
    Object.assign(this, {id, value: '', textContent: '', disabled: false, children: []});
    this.attributes = new Map();
    this.dataset = {};
    this.scrolls = [];
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
  dispatch(type, event = {}) {
    for (const callback of this.listeners.get(type) || []) callback({preventDefault() {}, ...event});
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  scrollIntoView(options) { this.scrolls.push(options); }
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
function createDom(source = html) {
  const elements = new Map();
  const nodes = [];
  for (const match of source.matchAll(/<([a-z][\w-]*)\b[^>]*>/gi)) {
    const tag = match[0];
    const id = tag.match(/\bid="([^"]+)"/)?.[1] || '';
    const element = new Element(id);
    for (const attribute of tag.matchAll(/([\w-]+)="([^"]*)"/g)) {
      element.setAttribute(attribute[1], attribute[2]);
      if (attribute[1] === 'data-view') element.dataset.view = attribute[2];
      if (attribute[1] === 'class') {
        for (const name of attribute[2].split(/\s+/)) element.classList.add(name);
      }
    }
    element.disabled = /\sdisabled(?:\s|>|=)/.test(match[0]);
    element.hidden = /\shidden(?:\s|>|=)/.test(match[0]);
    nodes.push(element);
    if (id) elements.set(id, element);
  }
  const el = id => {
    assert.ok(elements.has(id), `Unknown element ${id}`);
    return elements.get(id);
  };
  const documentEvents = new Element();
  const document = {
    getElementById: el,
    querySelectorAll(selector) {
      if (selector === '[data-view]') return nodes.filter(node => node.dataset.view);
      if (selector === '.nav-btn') return nodes.filter(node => node.classList.contains('nav-btn'));
      return [];
    },
    createElement: () => new Element(),
    addEventListener: (...args) => documentEvents.addEventListener(...args),
    dispatch: (...args) => documentEvents.dispatch(...args),
  };
  return {el, document};
}
function inlineScript(marker, source = html) {
  const script = [...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
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
