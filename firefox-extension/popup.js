const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
const UI_VERSION = 3;
const $ = id => document.getElementById(id);

async function getState(defaults) { return await api.storage.local.get(defaults); }
async function setState(values) { await api.storage.local.set(values); }

function browserLabel() {
  const ua = navigator.userAgent || "";
  if (navigator.brave) return "Brave";
  if (/Firefox/i.test(ua)) return "Firefox";
  if (/Edg\//i.test(ua)) return "Edge";
  if (/OPR\//i.test(ua)) return "Opera";
  if (/Chrome\//i.test(ua)) return "Chrome";
  return "Chromium";
}

function normalizeSiteUrl(raw) {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Bu sayfa desteklenmiyor.");
  url.hash = "";
  url.search = "";
  return url.toString();
}

function siteKey(raw) {
  return normalizeSiteUrl(raw);
}

function siteOrigin(raw) {
  return new URL(normalizeSiteUrl(raw)).origin;
}

function permissionPattern(raw) {
  return `${siteOrigin(raw)}/*`;
}

function cleanTitle(raw, url) {
  const title = String(raw || "").trim().replace(/\s+/g, " ");
  if (title) return title.slice(0, 300);
  try { return new URL(url).hostname; }
  catch { return "Site"; }
}

function hash32(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function internalSessionName(url, clientId) {
  const normalized = normalizeSiteUrl(url);
  const parsed = new URL(normalized);
  const host = parsed.hostname.replace(/[^A-Za-z0-9.-]/g, "-").slice(0, 56) || "site";
  const digest = hash32(`${clientId}|${normalized}`) + hash32(`${normalized}|${clientId}`);
  return `site-${host}-${digest}`.slice(0, 100);
}

function siteEnabled(site) {
  return Boolean(site) && site.enabled !== false;
}

function findSite(sites, url) {
  const wanted = siteKey(url);
  return sites.find(site => {
    try { return siteKey(site.url) === wanted; }
    catch { return false; }
  });
}

async function ensureUiVersion() {
  const state = await getState({uiVersion: 0, sites: [], clientId: ""});
  if (state.uiVersion === UI_VERSION) return;

  const clientId = state.clientId || crypto.randomUUID();
  const migrated = [];
  const seen = new Set();

  for (const oldSite of Array.isArray(state.sites) ? state.sites : []) {
    try {
      const url = normalizeSiteUrl(oldSite.url);
      const key = siteKey(url);
      if (seen.has(key)) continue;
      seen.add(key);
      migrated.push({
        ...oldSite,
        name: internalSessionName(url, clientId),
        title: cleanTitle(oldSite.title, url),
        url,
        enabled: oldSite.enabled !== false,
        browser: oldSite.browser || browserLabel(),
        keepaliveUrl: "",
        keepaliveMinutes: 0
      });
    } catch {}
  }

  await setState({uiVersion: UI_VERSION, clientId, sites: migrated});
}

async function activeSiteInfo() {
  const tabs = await api.tabs.query({active: true, currentWindow: true});
  const tab = tabs?.[0];
  if (!tab?.url) return null;
  const url = normalizeSiteUrl(tab.url);
  return {url, title: cleanTitle(tab.title, url)};
}

function formatTime(value) {
  if (!value) return "henüz eşitlenmedi";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

async function addSite(info) {
  const state = await getState({sites: [], clientId: "", pairedAt: "", clientToken: ""});
  if (!state.pairedAt || !state.clientId || !state.clientToken) throw new Error("Önce broker bağlantısını kur.");

  const url = normalizeSiteUrl(info.url);
  if (findSite(state.sites, url)) throw new Error("Bu URL zaten bu tarayıcıda kayıtlı.");

  const granted = await api.permissions.request({origins: [permissionPattern(url)]});
  if (!granted) throw new Error("Site izni verilmedi.");

  const site = {
    name: internalSessionName(url, state.clientId),
    title: cleanTitle(info.title, url),
    url,
    enabled: true,
    browser: browserLabel(),
    storeId: "",
    keepaliveUrl: "",
    keepaliveMinutes: 0,
    lastStatus: "PENDING",
    lastError: ""
  };

  state.sites.push(site);
  await setState({sites: state.sites});
  await api.runtime.sendMessage({type: "SYNC_ONE", name: site.name});
}

async function toggleSite(name) {
  const state = await getState({sites: []});
  const site = state.sites.find(item => item.name === name);
  if (!site) throw new Error("Kayıt bulunamadı.");

  if (siteEnabled(site)) {
    site.enabled = false;
    site.lastStatus = "DISABLED";
    site.lastError = "";
    await setState({sites: state.sites});
    return;
  }

  const granted = await api.permissions.request({origins: [permissionPattern(site.url)]});
  if (!granted) throw new Error("Site izni verilmedi.");

  site.enabled = true;
  site.lastStatus = "PENDING";
  site.lastError = "";
  await setState({sites: state.sites});
  await api.runtime.sendMessage({type: "SYNC_ONE", name: site.name});
}

function buildInfo(site, isCurrent) {
  const info = document.createElement("div");
  info.className = "site-info";

  const title = document.createElement("strong");
  title.className = "site-name";
  title.textContent = cleanTitle(site.title, site.url);
  title.title = title.textContent;

  const urlLine = document.createElement("div");
  urlLine.className = "site-url";
  urlLine.textContent = normalizeSiteUrl(site.url);
  urlLine.title = urlLine.textContent;

  const status = siteEnabled(site) ? (site.lastStatus || "PENDING") : "KAPALI";
  const meta = document.createElement("div");
  meta.className = "site-meta";
  meta.textContent = `${site.browser || browserLabel()} • ${status} • ${site.cookieCount ?? 0} cookie • ${formatTime(site.lastSync)}${isCurrent ? " • bu sekme" : ""}`;

  info.append(title, urlLine, meta);
  return info;
}

function savedSiteRow(site, isCurrent = false) {
  const row = document.createElement("div");
  row.className = isCurrent ? "current-site" : "site";

  const head = document.createElement("div");
  head.className = "site-head";
  head.append(buildInfo(site, isCurrent));

  const toggle = document.createElement("button");
  toggle.className = siteEnabled(site) ? "toggle-on" : "toggle-off";
  toggle.textContent = siteEnabled(site) ? "Kapat" : "Aç";
  toggle.onclick = async () => {
    try {
      $("siteStatus").textContent = "";
      await toggleSite(site.name);
      await render();
    } catch (error) {
      $("siteStatus").textContent = `HATA: ${error.message || error}`;
    }
  };

  head.append(toggle);
  row.append(head);
  return row;
}

function unsavedCurrentRow(info) {
  const row = document.createElement("div");
  row.className = "current-site";

  const head = document.createElement("div");
  head.className = "site-head";

  const pseudoSite = {
    title: info.title,
    url: info.url,
    browser: browserLabel(),
    enabled: false,
    lastStatus: "EKLENMEMİŞ",
    cookieCount: 0,
    lastSync: ""
  };
  head.append(buildInfo(pseudoSite, true));

  const add = document.createElement("button");
  add.className = "add";
  add.textContent = "Ekle";
  add.onclick = async () => {
    try {
      $("siteStatus").textContent = "";
      await addSite(info);
      await render();
    } catch (error) {
      $("siteStatus").textContent = `HATA: ${error.message || error}`;
    }
  };

  head.append(add);
  row.append(head);
  return row;
}

async function render() {
  await ensureUiVersion();
  const state = await getState({pairedAt: "", clientId: "", clientToken: "", sites: []});
  const paired = Boolean(state.pairedAt && state.clientId && state.clientToken);

  $("runtimeInfo").textContent = `${browserLabel()} • ${paired ? "broker bağlı" : "broker bağlı değil"} • tarayıcıya özel liste`;
  $("pairSection").hidden = paired;
  $("siteSection").hidden = !paired;
  if (!paired) return;

  const currentContainer = $("currentSite");
  const savedContainer = $("sites");
  currentContainer.textContent = "";
  savedContainer.textContent = "";
  $("siteCount").textContent = `${state.sites.length} kayıt`;

  let currentInfo = null;
  try { currentInfo = await activeSiteInfo(); }
  catch { currentInfo = null; }

  let currentSite = null;
  if (currentInfo) {
    currentSite = findSite(state.sites, currentInfo.url);
    if (currentSite) {
      const newTitle = cleanTitle(currentInfo.title, currentInfo.url);
      const newUrl = normalizeSiteUrl(currentInfo.url);
      if (currentSite.title !== newTitle || currentSite.url !== newUrl) {
        currentSite.title = newTitle;
        currentSite.url = newUrl;
        await setState({sites: state.sites});
      }
      currentContainer.append(savedSiteRow(currentSite, true));
    } else {
      currentContainer.append(unsavedCurrentRow(currentInfo));
    }
  } else {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "HTTP/HTTPS bir sekme aç. Sonra buradan Ekle.";
    currentContainer.append(empty);
  }

  const currentKey = currentInfo ? siteKey(currentInfo.url) : "";
  let rendered = 0;
  for (const site of state.sites) {
    let key;
    try { key = siteKey(site.url); }
    catch { continue; }
    if (currentKey && key === currentKey) continue;
    savedContainer.append(savedSiteRow(site, false));
    rendered += 1;
  }

  if (!rendered) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = state.sites.length ? "Diğer kayıt yok." : "Henüz site eklenmedi.";
    savedContainer.append(empty);
  }
}

$("pairButton").onclick = async () => {
  try {
    const code = $("pairCode").value.trim();
    if (!/^\d{8}$/.test(code)) throw new Error("8 haneli pair code gerekli.");
    const result = await api.runtime.sendMessage({
      type: "PAIR",
      payload: {brokerUrl: DEFAULT_BROKER, label: browserLabel(), code}
    });
    $("pairStatus").textContent = `Bağlandı: ${result.paired_at}`;
    await render();
  } catch (error) {
    $("pairStatus").textContent = `HATA: ${error.message || error}`;
  }
};

render();
