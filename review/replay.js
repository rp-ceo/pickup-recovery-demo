'use strict';
const report = JSON.parse(document.getElementById('report').textContent);
const cases = report.cases;
const get = id => document.getElementById(id);
const clock = new Intl.DateTimeFormat('en-GB',{timeZone:report.timezone,hour:'2-digit',minute:'2-digit'});
const date = new Intl.DateTimeFormat('en-GB',{timeZone:report.timezone,weekday:'short',day:'numeric',month:'short'});
const actors = {
  shopper:['user','Shopper'], agent:['mail','Pickup agent'], checks:['agent','Pickup agent'],
  carrier:['truck','Carrier'], timer:['clock','Scheduled check'], support:['headset','Pickup agent'], record:['file','Case record']
};
const stateLabels = {
  OFFERED:'Options offered', RESOLVED:'Pickup confirmed', HUMAN_REVIEW:'With the team', WINDOW_OPEN:'Window open',
  WAITING_CARRIER:'Awaiting carrier', NEED_ADDRESS:'Checking address', BOOKING_UNCERTAIN:'Booking unconfirmed',
  CONFIRMED_AWAITING_NOTICE:'Notice pending', NEEDS_SLOT_CHOICE:'Awaiting choice', NEEDS_CLARIFICATION:'Clarifying',
  SLOT_CHANGED:'Times changed', AWAITING_REPLY:'Awaiting reply'
};
let current = cases.find(item => item.id === 'P101');
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
function stamp(at) {
  const label = element('time',null,clock.format(new Date(at)));
  label.dateTime = at;
  label.title = date.format(new Date(at))+' · '+report.timezone;
  return label;
}
function inConversation(step) {
  return step.kind === 'shopper' || step.kind === 'agent';
}
function chatEntry(step,turn) {
  const outgoing = step.kind === 'agent';
  const chat = element('div','chat '+(outgoing ? 'out' : 'in'));
  const [glyph,role] = actors[step.kind];
  const anna = current.id === 'P101' && step.kind === 'shopper';
  const who = anna ? 'Anna' : role;
  const avatar = element('span','avatar');
  avatar.append(icon(glyph));
  const content = element('div','chat-content');
  const byline = element('div','byline');
  byline.append(element('strong',null,who),step.channel === 'link' ? 'Rebooking link' : anna ? 'Shopper email' : 'Email', stamp(step.at));
  const bubble = messageBody(step,turn);
  bubble.className = 'bubble';
  content.append(byline,bubble);
  if (step.receipt) {
    const receipt = element('span','receipt');
    receipt.append(icon('check'),'Delivered');
    receipt.title = step.receipt;
    content.append(receipt);
  }
  chat.append(avatar,content);
  return chat;
}
function actionEntry(step) {
  const block = element('div','action');
  block.dataset.kind = step.kind;
  block.dataset.channel = step.channel;
  const [glyph,actor] = actors[step.kind];
  const row = element('div','action-header');
  const avatar = element('span','action-icon');
  avatar.append(icon(glyph));
  const author = element('span','action-author',actor);
  if (step.destination && step.destination !== actor) author.append(icon('arrow'),step.destination);
  if (step.channel === 'carrier_record' && !step.destination) author.textContent = 'Carrier record';
  row.append(avatar,author,stamp(step.at));
  block.append(row,element('h3',null,step.title));
  if (step.text) block.append(element('p',null,step.text));
  if (step.facts.length) block.append(displayFacts(step.facts));
  return block;
}
function appendEntry(position,animate) {
  const step = current.steps[position];
  const turn = current.turns[step.turn];
  const entry = element('li',animate ? 'entry is-new' : 'entry');
  entry.dataset.stepIndex = position;
  entry.dataset.kind = step.kind;
  entry.dataset.channel = step.channel;
  const day = date.format(new Date(step.at));
  if (position === 0 || date.format(new Date(current.steps[position-1].at)) !== day) {
    entry.append(element('div','date-marker',day));
  }
  entry.append(inConversation(step) ? chatEntry(step,turn) : actionEntry(step));
  if (position === current.steps.length-1 && turn.state === 'RESOLVED' && !turn.collection_scan_observed_at) {
    const outcome = element('p','outcome');
    outcome.append(icon('box'),'The visit is booked. Collection is still awaiting a carrier scan.');
    entry.append(outcome);
  }
  get('feed').append(entry);
}
function renderRecords() {
  const panel = get('records');
  panel.replaceChildren();
  const step = current.steps[index];
  const complete = current.steps[index+1]?.turn !== step.turn;
  const lastTurn = complete ? step.turn : step.turn-1;
  if (lastTurn < 0) {
    panel.append(element('p',null,'The tool record will appear when this exchange is complete.'));
    return;
  }
  const turn = current.turns[lastTurn];
  panel.append(element('h3',null,'Latest completed exchange · '+clock.format(new Date(turn.at))));
  const list = element('ul');
  for (const fact of turn.evidence) list.append(element('li',null,fact));
  panel.append(list,element('h3',null,'Tool calls'));
  for (const call of turn.tool_calls) {
    const detail = element('details');
    detail.append(element('summary',null,call.tool),element('pre',null,JSON.stringify(call,null,2)));
    panel.append(detail);
  }
  if (!turn.tool_calls.length) panel.append(element('p',null,'No tools were called in this exchange.'));
}
function caseStatus() {
  const step = current.steps[index];
  if (step.channel === 'carrier_response') return 'Carrier confirmed';
  if (step.title === 'Booking still unconfirmed') return 'Booking unconfirmed';
  const complete = current.steps[index+1]?.turn !== step.turn;
  const turn = current.turns[complete ? step.turn : step.turn-1];
  if (!turn) return 'Open';
  if (turn.collection_scan_observed_at && turn.state === 'RESOLVED') return 'Parcel collected';
  return stateLabels[turn.state] || 'In progress';
}
function render(scroll=true,animate=true) {
  const feed = get('feed');
  while (feed.children.length > index+1) feed.lastElementChild.remove();
  while (feed.children.length < index+1) appendEntry(feed.children.length,animate);
  if (scroll) {
    const viewport = get('transcript');
    const last = feed.lastElementChild;
    const offset = last.getBoundingClientRect().top-viewport.getBoundingClientRect().top+viewport.scrollTop;
    viewport.scrollTop = last.offsetHeight > viewport.clientHeight-20 ? offset-10 : viewport.scrollHeight;
  }
  get('progress-label').textContent = (index+1)+' of '+current.steps.length+' events';
  get('progress').max = current.steps.length;
  get('progress').value = index+1;
  get('back').disabled = index === 0;
  const end = index === current.steps.length-1;
  buttonContent(get('next'),end ? 'Replay' : 'Next event',end ? 'return' : 'arrow');
  const status = caseStatus();
  const badge = get('case-status');
  badge.textContent = status;
  badge.dataset.state = ['Pickup confirmed','Parcel collected','Carrier confirmed'].includes(status) ? 'done' :
    ['Booking unconfirmed','Awaiting carrier','With the team','Notice pending'].includes(status) ? 'waiting' : 'open';
  const step = current.steps[index];
  get('announce').textContent = get('progress-label').textContent+'. '+actors[step.kind][1]+'. '+step.title+'. '+step.text;
  if (get('details').open) renderRecords();
}
function setPlaying(on) {
  clearTimeout(timer);
  playing = on;
  buttonContent(get('play'),on ? 'Pause' : 'Play story',on ? 'pause' : 'play',true);
  get('play').setAttribute('aria-pressed',String(on));
  if (on) schedule();
}
function schedule() {
  const step = current.steps[index];
  const words = step.text.split(/\s+/).length + step.facts.length*3;
  timer = setTimeout(() => {
    index++;
    render();
    if (index === current.steps.length-1) setPlaying(false);
    else schedule();
  },Math.min(12500,Math.max(3200,1400+words*205)));
}
function moveTo(position) {
  if (position < 0 || position >= current.steps.length) return;
  setPlaying(false);
  index = position;
  render();
}
function selectCase(item,opening=false) {
  setPlaying(false);
  current = item;
  index = opening ? Math.min(2,item.steps.length-1) : 0;
  get('feed').replaceChildren();
  get('case-title').textContent = item.id === 'P101' ? 'Anna’s return pickup' : item.label;
  get('intro-copy').textContent = item.id === 'P101'
    ? 'A missed return pickup, from the shopper’s first email to the carrier’s booking confirmation.'
    : 'Follow the shopper’s messages, agent actions and carrier records in the order they happen.';
  get('details').open = false;
  get('records').replaceChildren();
  render(false,false);
  get('transcript').scrollTop = 0;
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
get('details').addEventListener('toggle',() => {
  if (get('details').open) {setPlaying(false); renderRecords();}
});
get('transcript').addEventListener('wheel',() => {if (playing) setPlaying(false);},{passive:true});
get('transcript').addEventListener('touchstart',() => {if (playing) setPlaying(false);},{passive:true});
get('transcript').addEventListener('keydown',event => {
  if (['PageUp','PageDown','ArrowUp','ArrowDown','Home','End'].includes(event.key) && playing) setPlaying(false);
});
get('play').addEventListener('click',() => {
  if (!playing && index === current.steps.length-1) moveTo(0);
  setPlaying(!playing);
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
selectCase(current,true);
