'use strict';
const report = JSON.parse(document.getElementById('report').textContent);
const cases = report.cases;
const get = id => document.getElementById(id);
const time = new Intl.DateTimeFormat('en-GB', {
  timeZone: report.timezone, day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'
});
const stories = {
  P118: ['The courier missed the pickup.', 'The return is still with the shopper. Follow the carrier alert through to a new pickup time.'],
  P102: ['Is the courier still coming?', 'The pickup window has ended. The shopper writes first, and the carrier has yet to confirm what happened.']
};
const actors = {
  carrier: ['truck','Carrier','Pickup agent'],
  shopper: ['user','Shopper','Pickup agent'],
  checks: ['agent','Pickup agent','Internal checks'],
  agent: ['mail','Pickup agent','Shopper'],
  timer: ['clock','Scheduled check','Pickup agent'],
  support: ['headset','Pickup agent','Support'],
  record: ['file','Pickup agent','Case record']
};
let current = cases.find(item => item.id === 'P118');
let index = 0;
let playing = false;
let timer = null;

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS(svg.namespaceURI,'use');
  svg.setAttribute('class','icon');
  svg.setAttribute('aria-hidden','true');
  use.setAttribute('href','#i-' + name);
  svg.append(use);
  return svg;
}
function buttonContent(target, text, glyph, before = false) {
  const label = document.createTextNode(text);
  target.replaceChildren(...(before ? [icon(glyph),label] : [label,icon(glyph)]));
}
function displayTime(value) {
  return time.format(new Date(value));
}
function displayFacts(facts) {
  const list = element('dl','facts');
  for (const fact of facts) {
    const row = element('div');
    row.append(element('dt',null,fact.label),element('dd',null,fact.value));
    list.append(row);
  }
  return list;
}
function messageBody(step, turn) {
  const body = element('div','event-content');
  const slots = turn.tool_calls.find(call => call.tool === 'carrier.available_slots');
  const options = step.kind === 'agent' && slots ? Object.entries(slots.result) : [];
  const slotText = options.map(([code, slot]) => code + ': ' + slot).join(' or ');
  const suffix = slotText + '.';
  if (!options.length || !step.text.endsWith(suffix)) {
    body.append(element('p',null,step.text));
    return body;
  }
  body.append(element('p',null,step.text.slice(0,-suffix.length).trimEnd()));
  const grid = element('div','slots');
  for (const [code, label] of options) {
    const card = element('div','slot');
    const cut = label.indexOf(', ');
    const day = cut < 0 ? label : label.slice(0,cut);
    card.append(element('span','slot-code',code),element('strong',null,day));
    if (cut >= 0) card.append(element('span','slot-time',label.slice(cut+2)));
    grid.append(card);
  }
  body.append(grid);
  return body;
}
function renderScene(step, turn) {
  const scene = get('scene');
  scene.dataset.kind = step.kind;
  const [glyph, sender, target] = actors[step.kind];
  const row = element('div','actor-row');
  const avatar = element('span','actor-icon');
  avatar.append(icon(glyph));
  const destination = element('span','destination');
  destination.append(icon('arrow'),step.destination || (step.kind === 'support' ? turn.owner : target));
  row.append(avatar,element('span','actor-title',sender),destination);
  const card = element('div','event-card');
  card.append(row);
  if (step.text) card.append(messageBody(step,turn));
  if (step.facts.length) card.append(displayFacts(step.facts));
  if (step.receipt) {
    const receipt = element('div','receipt');
    receipt.append(icon('check'),'Delivery receipt ' + step.receipt);
    card.append(receipt);
  }
  scene.replaceChildren(card);
  if (index === current.steps.length-1) {
    const outcome = element('p','outcome');
    const note = turn.state === 'RESOLVED' && !turn.collection_scan_observed_at
      ? 'Scheduling is resolved. Physical collection still needs a carrier scan.'
      : turn.next_step;
    outcome.append(icon('file'), note);
    scene.append(outcome);
  }
}
function renderThread() {
  const steps = current.steps.slice(0,index+1).filter(step => step.kind === 'agent' || step.kind === 'shopper');
  const thread = get('thread');
  get('thread-count').textContent = steps.length;
  thread.replaceChildren();
  if (!steps.length) thread.append(element('p',null,'There are no shopper messages at this point.'));
  for (const step of steps) {
    const selection = step.kind === 'shopper' && current.turns[step.turn].event_source === 'shopper_selection';
    const who = selection ? 'Shopper · Rebooking link' : step.kind === 'shopper' ? 'Shopper' : 'Pickup agent';
    const item = element('div','thread-message');
    item.append(element('strong',null,who + ' · '+displayTime(step.at)),element('p',null,step.text));
    thread.append(item);
  }
}
function renderRecords(step, turn) {
  const panel = get('records');
  panel.replaceChildren();
  const lastForTurn = current.steps[index+1]?.turn !== step.turn;
  if (!lastForTurn) {
    panel.append(element('p',null,'The complete record appears at the end of this exchange.'));
    return;
  }
  panel.append(element('h3',null,'Case history'));
  const list = element('ul');
  for (const entry of turn.evidence) list.append(element('li',null,entry));
  panel.append(list,element('h3',null,'Tool calls'));
  if (!turn.tool_calls.length) panel.append(element('p',null,'No tools were called during this exchange.'));
  for (const call of turn.tool_calls) {
    const detail = element('details');
    detail.append(element('summary',null,call.tool),element('pre',null,JSON.stringify(call,null,2)));
    panel.append(detail);
  }
}
function makeTimeline() {
  const timeline = get('timeline');
  const jump = get('jump');
  timeline.replaceChildren();
  jump.replaceChildren();
  current.steps.forEach((step,i) => {
    const button = element('button','timeline-step');
    button.type = 'button';
    button.append(element('span','pin'), element('span',null,step.title));
    button.addEventListener('click',() => moveTo(i));
    timeline.append(button);
    const option = element('option',null,(i+1) + ' · ' + step.title);
    option.value = i;
    jump.append(option);
  });
}
function render() {
  const step = current.steps[index];
  const turn = current.turns[step.turn];
  get('step-counter').textContent = 'Step ' + (index+1) + ' of ' + current.steps.length;
  get('step-heading').textContent = step.title;
  get('stage-time').replaceChildren(icon('clock'),displayTime(step.at));
  get('stage-time').title = 'Local time · '+report.timezone;
  get('jump').value = String(index);
  Array.from(get('timeline').children).forEach((button,i) => {
    if (i === index) button.setAttribute('aria-current','step');
    else button.removeAttribute('aria-current');
    button.classList.toggle('done',i<index);
    button.firstChild.replaceChildren(i<index ? icon('check') : String(i+1));
  });
  get('back').disabled = index === 0;
  const end = index === current.steps.length-1;
  buttonContent(get('next'),end ? 'Restart' : 'Next step',end ? 'return' : 'arrow');
  renderScene(step,turn);
  renderThread();
  renderRecords(step,turn);
}
function setPlaying(on) {
  clearTimeout(timer);
  playing = on;
  buttonContent(get('play'),on ? 'Pause' : 'Play',on ? 'pause' : 'play',true);
  get('play').setAttribute('aria-pressed',String(on));
  if (on) schedule();
}
function schedule() {
  const words = current.steps[index].text.split(/\s+/).length;
  timer = setTimeout(() => {
    index++;
    render();
    if (index === current.steps.length-1) setPlaying(false);
    else schedule();
  },Math.min(12500,Math.max(4500,2200+words*225)));
}
function moveTo(position) {
  if (position < 0 || position >= current.steps.length) return;
  setPlaying(false);
  index = position;
  render();
  const stage = document.querySelector('.stage');
  if (stage.getBoundingClientRect().top < -55) stage.scrollIntoView({block:'start'});
}
function selectCase(item) {
  setPlaying(false);
  current = item;
  index = 0;
  const story = stories[item.id];
  get('case-title').textContent = story ? story[0] : item.label;
  get('intro').textContent = story ? story[1] : '';
  get('intro').hidden = !story;
  get('timeline-count').textContent = item.steps.length + ' steps';
  document.querySelectorAll('[data-route]').forEach(btn => {
    btn.setAttribute('aria-pressed',String(btn.dataset.route === item.id));
  });
  get('details').open = false;
  get('thread-panel').open = false;
  makeTimeline();
  render();
}
function renderLibrary() {
  const query = get('search').value.trim().toLowerCase();
  const hits = cases.filter(item => [item.id,item.label,item.group].join(' ').toLowerCase().includes(query));
  get('library-count').textContent = hits.length + (hits.length === 1 ? ' scenario' : ' scenarios');
  const list = get('library-list');
  list.replaceChildren();
  for (const group of new Set(hits.map(item => item.group))) {
    list.append(element('h3',null,group));
    for (const item of hits.filter(example => example.group === group)) {
      const button = element('button','case-option');
      button.type = 'button';
      button.setAttribute('aria-current',String(item.id === current.id));
      button.dataset.caseId = item.id;
      button.append(element('span',null,item.label),element('span',null,item.id));
      button.addEventListener('click',() => {
        get('library').close();
        selectCase(item);
      });
      list.append(button);
    }
  }
  if (!hits.length) list.append(element('p',null,'No matching scenarios. Try a different word or case ID.'));
}
get('next').addEventListener('click',() => moveTo((index+1)%current.steps.length));
get('back').addEventListener('click',() => moveTo(index-1));
get('jump').addEventListener('change',event => moveTo(Number(event.target.value)));
get('play').addEventListener('click',() => {
  if (!playing && index === current.steps.length-1) moveTo(0);
  setPlaying(!playing);
});
document.querySelectorAll('[data-route]').forEach(button => {
  button.addEventListener('click',() => selectCase(cases.find(item => item.id === button.dataset.route)));
});
get('browse').addEventListener('click',() => {
  setPlaying(false);
  get('search').value = '';
  renderLibrary();
  get('library').showModal();
  get('search').focus();
});
get('close-library').addEventListener('click',() => get('library').close());
get('library').addEventListener('keydown',event => {
  if (event.key === 'Escape') {
    event.preventDefault();
    get('library').close();
  }
},true);
get('search').addEventListener('input',renderLibrary);
document.addEventListener('visibilitychange',() => {if (document.hidden) setPlaying(false);});
selectCase(current);
