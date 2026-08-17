const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
const UI_VERSION = 2;
const $ = id => document.getElementById(id);

async function getState(defaults) { return await api.storage.local.get(defaults); }
async function setState(values) { await api.storage.local.set(values); }

async function ensureUiVersion() {
  const state = await getState({uiVersion: 0});
  if (state.uiVersion === UI_VERSION) return;
  await setState({
    uiVersion: UI_VERSION,
    clientToken: "",
    pairedAt: "",
    profileLabel: ""
  });
}

function browserLabel() {
  const ua = navigator.userAgent || "";
  if (navigator.brave) return "Brave";
  if (/Firefox/i.test(ua)) return "Firefox";
  if (/Edg\//i.test(ua)) return "Edge";
  if (/OPR\//i.test(ua)) return "Opera";
  if (/Chrome\//i.test(ua)) return "Chrome";
  return "Chromium";
}

function siteEnabled(site) {
  return Boolean(site) && site.enabled !== false;
}

function normalizeSiteUrl(raw) {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Bu sayfa desteklenmiyor.");
  url.hash = "";
  url.search = "";
  return url.toString();
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
  const parsed = new URL(normalizeSiteUrl(url));
  const host = parsed.hostname.replace(/[^A-Za-z0-9.-]/g, "-").slice(0, 64) || "site";
  return `site-${host}-${hash32(`${clientId}|${parsed.origin}`)}`.slice(0, 100);
}

async function activeSiteInfo() {
  const tabs = await api.tabs.query({active: true, currentWindow: true});
  const tab = tabs?.[0];
  const raw = tab?.url || "";
  if (!raw) return null;
  const url = normalizeSiteUrl(raw);
  return {url, title: cleanTitle(tab?.title, url)};
}

function formatTime(value) {
  if (!value) return "henüz eşitlenmedi";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function findSite(sites, url) {
  const wanted = siteOrigin(url);
  return sites.find(site => {
    try { return siteOrigin(site.url) === wanted; }
    catch { return false; }
  });
}

async function toggleSite(info) {
  const state = await getState({sites: [], clientId: "", profileLabel: "", pairedAt: ""});
  if (!state.pairedAt || !state.clientId) throw new Error("Önce broker bağlantısını kur.");

  const normalized = normalizeSiteUrl(info.url);
  const title = cleanTitle(info.title, normalized);
  let site = findSite(state.sites, normalized);

  if (siteEnabled(site)) {
    site.enabled = false;
    site.lastStatus = "DISABLED";
    site.lastError = "";
    site.title = title;
    site.url = normalized;
    await setState({sites: state.sites});
    return;
  }

  const granted = await api.permissions.request({origins: [permissionPattern(normalized)]});
  if (!granted) throw new Error("Site izni verilmedi.");

  if (!site) {
    site = {
      name: internalSessionName(normalized, state.clientId),
      title,
      url: normalized,
      storeId: "",
      keepaliveUrl: "",
      keepaliveMinutes: 0,
      enabled: true,
      browser: browserLabel(),
      profileLabel: state.profileLabel || browserLabel(),
      lastStatus: "PENDING"
    };
    state.sites.push(site);
  } else {
    site.title = title;
    site.url = normalized;
    site.enabled = true;
    site.browser = browserLabel();
    site.profileLabel = state.profileLabel || browserLabel();
    site.keepaliveUrl = "";
    site.keepaliveMinutes = 0;
    site.lastStatus = "PENDING";
    site.lastError = "";
  }

  await setState({sites: state.sites});
  await api.runtime.sendMessage({type: "SYNC_ONE", name: site.name});
}

function siteRow(info, site, isCurrent) {
  const row = document.createElement("div");
  row.className = "site";

  const head = document.createElement("div");
  head.className = "site-head";

  const content = document.createElement("div");
  content.className = "site-info";

  const shownUrl = normalizeSiteUrl(info?.url || site?.url || "");
  const shownTitle = cleanTitle(info?.title || site?.title, shownUrl);

  const title = document.createElement("strong");
  title.className = "site-name";
  title.textContent = shownTitle;
  title.title = shownTitle;

  const urlLine = document.createElement("div");
  urlLine.className = "site-url";
  urlLine.textContent = shownUrl;
  urlLine.title = shownUrl;

  const enabled = siteEnabled(site);
  const status = site ? (enabled ? (site.lastStatus || "PENDING") : "KAPALI") : "KAPALI";
  const browser = site?.browser || browserLabel();
  const cookies = site?.cookieCount ?? 0;
  const sync = site?.lastSync ? formatTime(site.lastSync) : "henüz eşitlenmedi";

  const meta = document.createElement("div");
  meta.className = "site-meta";
  meta.textContent = `${browser} • ${status} • ${cookies} cookie • ${sync}${isCurrent ? " • bu sekme" : ""}`;

  content.append(title, urlLine, meta);

  const toggle = document.createElement("button");
  toggle.className = enabled ? "toggle-on" : "toggle-off";
  toggle.textContent = enabled ? "Kapat" : "Aç";
  toggle.onclick = async () => {
    try {
      $("siteStatus").textContent = "";
      await toggleSite({url: shownUrl, title: shownTitle});
      await render();
    } catch (error) {
      $("siteStatus").textContent = `HATA: ${error.message || error}`;
    }
  };

  head.append(content, toggle);
  row.append(head);
  return row;
}

async function render() {
  await ensureUiVersion();
  const state = await getState({pairedAt: "", clientId: "", clientToken: "", profileLabel: "", sites: []});
  const browser = browserLabel();
  const paired = Boolean(state.pairedAt && state.clientId && state.clientToken);

  $("runtimeInfo").textContent = `${browser} • ${paired ? "broker bağlı" : "broker bağlı değil"}`;
  $("pairSection").hidden = paired;
  $("siteSection").hidden = !paired;

  if (!paired) return;

  const container = $("sites");
  container.textContent = "";

  let currentInfo = null;
  try { currentInfo = await activeSiteInfo(); }
  catch { currentInfo = null; }

  const renderedOrigins = new Set();

  if (currentInfo) {
    const currentSite = findSite(state.sites, currentInfo.url);
    if (currentSite) {
      currentSite.title = currentInfo.title;
      currentSite.url = currentInfo.url;
      await setState({sites: state.sites});
    }
    container.append(siteRow(currentInfo, currentSite, true));
    renderedOrigins.add(siteOrigin(currentInfo.url));
  }

  for (const site of state.sites) {
    let origin;
    try { origin = siteOrigin(site.url); }
    catch { continue; }
    if (renderedOrigins.has(origin)) continue;
    container.append(siteRow({url: site.url, title: site.title}, site, false));
    renderedOrigins.add(origin);
  }

  if (!container.children.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "HTTP/HTTPS bir sayfa açıp uzantıya tekrar tıkla.";
    container.append(empty);
  }
}

$("pairButton").onclick = async () => {
  try {
    const code = $("pairCode").value.trim();
    if (!/^\d{8}$/.test(code)) throw new Error("8 haneli pair code gerekli.");
    const label = browserLabel();
    const result = await api.runtime.sendMessage({
      type: "PAIR",
      payload: {brokerUrl: DEFAULT_BROKER, label, code}
    });
    $("pairStatus").textContent = `Bağlandı: ${result.paired_at}`;
    await render();
  } catch (error) {
    $("pairStatus").textContent = `HATA: ${error.message || error}`;
  }
};

render();
