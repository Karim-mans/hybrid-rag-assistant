import {drawLandscape} from "./landscape.js";

const $ = id => document.getElementById(id);
const icons = {
  chat: '<path d="M4 5h16v11H9l-5 4V5Z"/><path d="M8 9h8m-8 3h5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  book: '<path d="M3 5c4-1 6-.5 9 1.5C15 4.5 17 4 21 5v14c-4-1-6-.5-9 1.5C9 18.5 7 18 3 19Z"/><path d="M12 7v13"/>',
  desktop: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  compose: '<path d="M11 5H5v14h14v-6m-9 1 1-4 7-7 3 3-7 7-4 1Z"/>',
  stack: '<path d="m3 8 9-4 9 4-9 4-9-4Zm0 4 9 4 9-4m-18 4 9 4 9-4"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  send: '<path d="m3 10 17-7-5 18-4-7-8-4Zm8 4 9-11"/>',
  file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
  leaf: '<path d="M4 19C4 9 9 4 21 4c0 10-4 16-13 15m-5 2L15 9"/>',
  waves: '<path d="M2 7c4-4 6 4 10 0s6 4 10 0M2 12c4-4 6 4 10 0s6 4 10 0M2 17c4-4 6 4 10 0s6 4 10 0"/>',
  chart: '<path d="M4 4v16h16M8 15v-4m5 4V7m5 8v-5"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12m-16-12h.1m-.1 6h.1m-.1 6h.1"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
};

function icon(name) {
  const i = document.createElement("i");
  i.dataset.icon = name;
  decorate(i);
  return i;
}
function decorate(i) {
  i.setAttribute("aria-hidden", "true");
  i.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + icons[i.dataset.icon] + '</svg>';
}
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function btn(label, cls, action) {
  const node = el("button", cls, label);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
document.querySelectorAll("i[data-icon]").forEach(decorate);
drawLandscape($("landscape"));

const storageKey = "folio.workspace.v1";
let sources = [];
let turns = [];
let busy = false;
let ready = false;
let agentAvailable = false;
let toastTimer;
const narrow = matchMedia("(max-width:760px)");

function notify(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5000);
}
function persist() {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({sources, turns, mode:$("mode").value}));
  } catch {
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage is optional. */ }
    notify("Browser storage is full or disabled. This workspace lasts until you refresh.");
  }
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The workspace request failed.");
  return data;
}
function typeName(name) {
  return ({md:"Markdown",txt:"Text",pdf:"PDF"})[name.split(".").pop().toLowerCase()] || "Text";
}
function updateControls() {
  $("send").disabled = !ready || busy || !sources.length || !$("question").value.trim();
  $("add-source").disabled = busy || !ready;
  $("new-chat").disabled = busy || !ready;
  $("mode").disabled = busy || !ready;
  $("mode-hint").textContent = $("mode").value === "search" ? "Local keyword search · No model calls" : "Agent chat · Powered by your OpenAI key";
}
function sourceItem(s) {
  const item = btn("", "source-item", () => showSource(s.id));
  item.title = s.name;
  const mark = el("span","file-symbol");
  mark.append(icon("file"));
  const info = el("span");
  info.append(el("span","source-title",s.name.replace(/\.[^.]+$/, "")),
    el("small","source-meta",typeName(s.name) + (s.id === "sample" ? " · Sample" : s.name.toLowerCase().endsWith(".pdf") ? " · " + s.pages.length + (s.pages.length === 1 ? " page" : " pages") : "")));
  item.append(mark,info);
  return item;
}
function renderSources() {
  $("sources").replaceChildren(...sources.map(sourceItem));
  $("lib-count").textContent = sources.length;
  $("source-count").querySelector("span").textContent = sources.length + (sources.length === 1 ? " source" : " sources");
  renderStarters();
  updateControls();
}
function renderStarters() {
  let choices = [];
  const onlySample = sources.length === 1 && sources[0].id === "sample";
  if (onlySample) {
    choices = [["leaf","What is passive rewilding?"],["waves","How do beavers change rivers?"],["chart","How is recovery measured?"]];
  } else if (sources.length && $("mode").value === "agent") {
    choices = [["list","What are the main ideas?"],["search","What evidence supports the conclusions?"],["book","Which terms should I know?"]];
  } else if (sources.length) {
    const text = sources.map(s => s.pages.join(" ")).join(" ").slice(0,100000);
    const common = new Set("about after again because before being could every first found might other should these their there those under where which while would".split(" "));
    const words = new Map();
    for (const [word] of text.toLowerCase().matchAll(/[\p{L}]{5,}/gu)) {
      if (!common.has(word)) words.set(word, (words.get(word) || 0) + 1);
    }
    const topics = [...words].sort((a,b) => b[1]-a[1]).slice(0,3);
    choices = topics.map(([word], i) => [["search","book","list"][i], "Find passages about " + word]);
  }
  const cards = choices.map(([symbol, label]) => {
    const card = btn("", "starter", () => {
      $("question").value = label;
      updateControls();
      $("question").focus();
    });
    const mark = el("span", "starter-icon");
    mark.append(icon(symbol));
    card.append(mark, el("span","",label));
    return card;
  });
  if (!cards.length) {
    const empty = el("p","empty-text", sources.length ? "Enter a word from your source to find matching passages." : "Add your first source to start a conversation.");
    cards.push(empty);
  }
  $("starters").replaceChildren(...cards);
}

function openDialog(title, ...nodes) {
  const h = el("h2","",title);
  h.id = "dialog-title";
  $("dialog").setAttribute("aria-labelledby", h.id);
  $("dialog-body").replaceChildren(h,...nodes);
  if (!$("dialog").open) $("dialog").showModal();
}
function closeDialog() { $("dialog").close(); }
$("dialog-close").addEventListener("click", closeDialog);
$("dialog").addEventListener("click", e => {
  if (e.target !== $("dialog")) return;
  const r = $("dialog").getBoundingClientRect();
  if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeDialog();
});

// Format common Markdown structures using text nodes for all document/model content.
function inline(node, text) {
  for (const part of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
    if (part.startsWith("**") && part.endsWith("**")) node.append(el("strong","",part.slice(2,-2)));
    else if (part.startsWith("`") && part.endsWith("`")) node.append(el("code","",part.slice(1,-1)));
    else node.append(document.createTextNode(part));
  }
}
function formatText(text, cls) {
  const box = el("div",cls);
  let paragraph = [], list = null, code = null;
  function flush() {
    if (paragraph.length) {
      const p = el("p");
      inline(p,paragraph.join(" "));
      box.append(p);
      paragraph = [];
    }
  }
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("```")) {
      flush(); list = null;
      if (code) code = null;
      else { code = el("pre"); box.append(code); }
    } else if (code) code.append(document.createTextNode(line+"\n"));
    else if (!line.trim()) { flush(); list = null; }
    else if (/^#{1,6}\s/.test(line)) {
      flush(); list = null;
      const h = el("h3"); inline(h,line.replace(/^#+\s+/,"")); box.append(h);
    } else if (/^\s*(?:[-*]|\d+[.)])\s/.test(line)) {
      flush();
      const tag = /^\s*\d/.test(line) ? "ol" : "ul";
      if (!list || list.localName !== tag) { list = el(tag); box.append(list); }
      const li = el("li"); inline(li,line.replace(/^\s*(?:[-*]|\d+[.)])\s+/,"")); list.append(li);
    } else { list = null; paragraph.push(line); }
  }
  flush();
  return box;
}
function showSource(id, page = 1) {
  const s = sources.find(item => item.id === id);
  if (!s) return;
  const text = formatText(s.pages[page-1] || "This page contains no readable text.", "reader-text");
  text.tabIndex = 0;
  const actions = el("div","dialog-actions");
  const remove = btn("Remove source","secondary danger",() => {
    sources = sources.filter(item => item.id !== id);
    persist(); renderSources(); closeDialog(); notify("Source removed from this workspace.");
  });
  remove.disabled = busy;
  actions.append(remove);
  if (s.pages.length > 1) {
    const back = btn("Previous","secondary",() => showSource(id,page-1));
    const next = btn("Next","secondary",() => showSource(id,page+1));
    back.disabled = page <= 1;
    next.disabled = page >= s.pages.length;
    actions.append(back,next);
  }
  const meta = typeName(s.name) + (typeName(s.name) === "PDF" ? " · Page "+page+" of "+s.pages.length : "");
  openDialog(s.name,el("p","empty-text",meta),text,actions);
}
function showPassage(p) {
  const parts = [el("p","empty-text",p.page ? "Retrieved passage · Page "+p.page : "Retrieved passage"),formatText(p.text,"reader-text")];
  if (sources.some(s => s.id === p.id)) {
    const actions = el("div","dialog-actions");
    actions.append(btn("Read full source","secondary",() => showSource(p.id,p.page || 1)));
    parts.push(actions);
  }
  openDialog(p.name,...parts);
}
function showGuide() {
  openDialog("Workspace guide",
    el("h3","","1. Gather your sources"),el("p","","Use Add sources or drop PDF, TXT, or Markdown files onto the workspace. Select a filename to read or remove it."),
    el("h3","","2. Choose an answer mode"),el("p","","Passage search finds matching words locally. Agent chat combines keyword matches with OpenAI embeddings. Set OPENAI_API_KEY in .env to enable it. Adding COHERE_API_KEY sends the query and candidate passages to Cohere for reranking. Restart the server after changing keys."),
    el("h3","","3. Check the evidence"),el("p","","Open a retrieved passage below a response to see its source and PDF page. New chat clears the conversation and keeps the library."),
    el("p","empty-text","This tab remembers your source list and chat. Agent chat caches passages and embeddings in a local Chroma database. Removing a source excludes it from searches and keeps its cached passages on disk."));
}
$("guide-open").addEventListener("click", showGuide);
function setSidebar(open) {
  if (narrow.matches) {
    document.body.classList.toggle("mobile-library", open);
    $("scrim").hidden = !open;
  } else {
    document.body.classList.toggle("is-collapsed", !open);
  }
  $("menu").setAttribute("aria-expanded", String(open));
}
$("menu").addEventListener("click", () => setSidebar($("menu").getAttribute("aria-expanded") !== "true"));
$("scrim").addEventListener("click", () => setSidebar(false));
$("mobile-close").addEventListener("click", () => { setSidebar(false); $("menu").focus(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("dialog").open && narrow.matches) setSidebar(false);
});
function resetSidebar() {
  document.body.classList.remove("mobile-library","is-collapsed");
  $("scrim").hidden = true;
  setSidebar(!narrow.matches);
}
narrow.addEventListener("change", resetSidebar);
resetSidebar();
$("chat-nav").addEventListener("click", () => { if (narrow.matches) setSidebar(false); $("question").focus(); });
$("source-count").addEventListener("click", () => {
  setSidebar(true);
  ($("sources").querySelector("button") || $("add-source")).focus();
});
$("new-chat").addEventListener("click", () => {
  function clear() {
    turns = []; $("question").value = ""; persist(); renderThread(); updateControls();
    closeDialog(); $("question").focus();
  }
  if (!turns.length) { $("question").value = ""; $("question").focus(); updateControls(); return; }
  const actions = el("div","dialog-actions");
  actions.append(btn("Cancel","secondary",closeDialog),btn("Start new chat","secondary",clear));
  openDialog("Start a new chat?",el("p","","This clears the current conversation. Your sources stay in the library."),actions);
});

function renderThread() {
  $("welcome").hidden = !!turns.length;
  $("thread").hidden = !turns.length;
  const nodes = [el("h1","thread-title","Document chat")];
  turns.forEach((turn,index) => {
    nodes.push(el("div","message user",turn.q));
    const answer = el("article","message");
    const head = el("div","answer-head");
    const brand = el("img"); brand.src = "/favicon.svg"; brand.alt = "";
    head.append(brand,el("span","","Hybrid RAG Assistant"),el("small","",turn.mode === "search" ? "Passage search" : "Agent chat"));
    answer.append(head);
    if (turn.pending) {
      const status = el("p","pending",turn.mode === "search" ? "Finding passages" : "Reading your sources");
      status.setAttribute("role","status"); answer.append(status);
    } else if (turn.error) {
      const error = el("div","error-box",turn.error);
      if (index === turns.length-1) error.append(btn("Retry","",() => submit(turn.q,true)));
      error.setAttribute("role","alert"); answer.append(error);
    } else {
      answer.append(formatText(turn.text,"answer-body"));
      if (turn.passages?.length) {
        const snippets = el("div","passages");
        for (const p of turn.passages) {
          const card = btn("","passage",() => showPassage(p));
          const title = el("strong"); title.append(icon("file"),document.createTextNode(p.name+(p.page ? " · p. "+p.page : "")));
          card.append(title,el("span","",p.text)); snippets.append(card);
        }
        answer.append(snippets);
      }
    }
    nodes.push(answer);
  });
  $("thread").replaceChildren(...nodes);
}
async function submit(question, retry = false) {
  question = question.trim();
  if (busy || !ready || !sources.length || !question) return;
  busy = true;
  if (retry) turns.pop();
  const mode = $("mode").value;
  const history = turns.filter(t => !t.error && !t.pending && t.mode === "agent").slice(-8).flatMap(t =>
    [{role:"user",text:t.q},{role:"assistant",text:t.text}]);
  const turn = {q:question,mode,pending:true};
  turns.push(turn);
  $("question").value = ""; renderThread(); updateControls();
  const scroll = $("scroll-area");
  scroll.scrollTop = scroll.scrollHeight;
  try {
    Object.assign(turn, await api("/api/ask",{
      method:"POST",headers:{"Content-Type":"application/json","X-Folio":"workspace"},
      body:JSON.stringify({question,mode,history,sources}),
    }));
  } catch (e) { turn.error = e.message; }
  finally {
    turn.pending = false; busy = false; persist(); renderThread(); updateControls();
    const lastAnswer = $("thread").lastElementChild;
    if (lastAnswer) lastAnswer.scrollIntoView({block:"nearest"});
    $("question").focus({preventScroll:true});
  }
}
$("composer").addEventListener("submit", e => { e.preventDefault(); submit($("question").value); });
$("question").addEventListener("input", updateControls);
$("question").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault(); $("composer").requestSubmit();
  }
});
$("mode").addEventListener("change", () => { renderStarters(); updateControls(); persist(); });

async function addFiles(files) {
  if (busy || !ready || !files.length) return;
  busy = true; updateControls();
  const failures = [];
  let added = 0;
  for (const file of files) {
    try {
      if (sources.length >= 12) throw new Error("The library holds up to 12 sources.");
      if (file.size > 10*1024*1024) throw new Error("Choose a file under 10 MB.");
      if (sources.some(s => s.name === file.name)) throw new Error("A source with that name is already open.");
      const data = await api("/api/read?name="+encodeURIComponent(file.name),{
        method:"POST",headers:{"Content-Type":"application/octet-stream","X-Folio":"workspace"},body:file,
      });
      const used = sources.reduce((a,s) => a+s.pages.reduce((n,p) => n+p.length,0),0);
      if (used+data.pages.reduce((a,p) => a+p.length,0)>2000000) throw new Error("Remove a source to make room for this file.");
      sources.push({id:crypto.randomUUID(),name:file.name,pages:data.pages}); added++;
    } catch(e) { failures.push(file.name+" — "+e.message); }
  }
  busy = false; $("files").value = ""; persist(); renderSources();
  if (failures.length) openDialog("Upload details",...failures.map(m => el("p","",m)));
  else notify(added === 1 ? "Source added to your library." : added+" sources added to your library.");
}
$("add-source").addEventListener("click", () => $("files").click());
$("files").addEventListener("change", () => addFiles(Array.from($("files").files)));
let dragDepth = 0;
window.addEventListener("dragenter", e => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); } });
window.addEventListener("dragover", e => { if (e.dataTransfer?.types.includes("Files")) e.preventDefault(); });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth=0; document.body.classList.remove("dragging"); } });
window.addEventListener("drop", e => { e.preventDefault(); dragDepth=0; document.body.classList.remove("dragging"); addFiles(Array.from(e.dataTransfer?.files || [])); });

async function init() {
  updateControls();
  try {
    const config = await api("/api/config");
    agentAvailable = config.agentAvailable;
    const agentOption = $("mode").querySelector('[value="agent"]');
    agentOption.disabled = !agentAvailable;
    if (!agentAvailable) agentOption.textContent = "Agent chat (key needed)";
    let saved;
    try { saved = JSON.parse(sessionStorage.getItem(storageKey)); } catch { /* New or unavailable storage. */ }
    if (saved && Array.isArray(saved.sources) && Array.isArray(saved.turns)) {
      sources = saved.sources; turns = saved.turns;
    } else {
      const response = await fetch("/sample.md");
      if (!response.ok) throw new Error("Could not load the sample source.");
      sources = [{id:"sample",name:"Rewilding field notes.md",pages:[await response.text()]}];
    }
    $("mode").value = agentAvailable && saved?.mode !== "search" ? "agent" : "search";
    ready = true; renderSources(); renderThread();
  } catch (e) { notify("Could not open the workspace. "+e.message); }
}
init();
