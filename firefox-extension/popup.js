const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
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

function siteEnabled(site) {
  return Boolean(site) && site.enabled !== false;
}

function canonicalSiteUrl(raw) {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Bu sayfa desteklenmiyor.");
  return `${url.origin}/`;
}

function permissionPattern(raw) {
  const url = new URL(canonicalSiteUrl(raw));
  return `${url.origin}/*`;
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
  const parsed = new URL(canonicalSiteUrl(url));
  const host = parsed.hostname.replace(/[^A-Za-z0-9.-]/g, "-").slice(0, 64) || "site";
  return `site-${host}-${hash32(`${clientId}|${parsed.origin}`)}`.slice(0, 100);
}

async function activeSiteUrl() {
  const tabs = await api.tabs.query({active: true, currentWindow: true});
  const raw = tabs?.[0]?.url || "";
  return raw ? canonicalSiteUrl(raw) : "";
}

function formatTime(value) {
  if (!value) return "henüz eşitlenmedi";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function findSite(sites, url) {
  const wanted = canonicalSiteUrl(url);
  return sites.find(site => {
    try { return canonicalSiteUrl(site.url) === wanted; }
    catch { return false; }
  });
}

async function toggleSite(url) {
  const state = await getState({sites: [], clientId: "", profileLabel: "", pairedAt: ""});
  if (!state.pairedAt || !state.clientId) throw new Error("Önce broker bağlantısını kur.");

  const normalized = canonicalSiteUrl(url);
  let site = findSite(state.sites, normalized);

  if (siteEnabled(site)) {
    site.enabled = false;
    site.lastStatus = "DISABLED";
    site.lastError = "";
    await setState({sites: state.sites});
    return;
  }

  const granted = await api.permissions.request({origins: [permissionPattern(normalized)]});
  if (!granted) throw new Error("Site izni verilmedi.");

  if (!site) {
    site = {
      name: internalSessionName(normalized, state.clientId),
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
    site.url = normalized;
    site.enabled = true;
    site.browser = browserLabel();
    site.profileLabel = state.profileLabel || browserLabel();
    site.lastStatus = "PENDING";
    site.lastError = "";
  }

  await setState({sites: state.sites});
  await api.runtime.sendMessage({type: "SYNC_ONE", name: site.name});
}

function siteRow(url, site, isCurrent) {
  const row = document.createElement("div");
  row.className = "site";

  const head = document.createElement("div");
  head.className = "site-head";

  const info = document.createElement("div");
  info.className = "site-info";

  const title = document.createElement("strong");
  title.className = "site-url";
  title.textContent = canonicalSiteUrl(url);
  title.title = canonicalSiteUrl(url);

  const enabled = siteEnabled(site);
  const status = site ? (enabled ? (site.lastStatus || "PENDING") : "KAPALI") : "KAPALI";
  const browser = site?.browser || browserLabel();
  const cookies = site?.cookieCount ?? 0;
  const sync = site?.lastSync ? formatTime(site.lastSync) : "henüz eşitlenmedi";

  const meta = document.createElement("div");
  meta.className = "site-meta";
  meta.textContent = `${browser} • ${status} • ${cookies} cookie • ${sync}${isCurrent ? " • bu sekme" : ""}`;

  info.append(title, meta);

  const toggle = document.createElement("button");
  toggle.className = enabled ? "toggle-on" : "toggle-off";
  toggle.textContent = enabled ? "Kapat" : "Aç";
  toggle.onclick = async () => {
    try {
      $("siteStatus").textContent = "";
      await toggleSite(url);
      await render();
    } catch (error) {
      $("siteStatus").textContent = `HATA: ${error.message || error}`;
    }
  };

  head.append(info, toggle);
  row.append(head);
  return row;
}

async function render() {
  const state = await getState({pairedAt: "", profileLabel: "", sites: []});
  const browser = browserLabel();

  $("runtimeInfo").textContent = `${browser} • ${state.pairedAt ? "broker bağlı" : "broker bağlı değil"}`;
  $("pairSection").hidden = Boolean(state.pairedAt);
  $("siteSection").hidden = !state.pairedAt;

  if (!state.pairedAt) return;

  const container = $("sites");
  container.textContent = "";

  let currentUrl = "";
  try { currentUrl = await activeSiteUrl(); }
  catch { currentUrl = ""; }

  const rendered = new Set();

  if (currentUrl) {
    const currentSite = findSite(state.sites, currentUrl);
    container.append(siteRow(currentUrl, currentSite, true));
    rendered.add(canonicalSiteUrl(currentUrl));
  }

  for (const site of state.sites) {
    let url;
    try { url = canonicalSiteUrl(site.url); }
    catch { continue; }
    if (rendered.has(url)) continue;
    container.append(siteRow(url, site, false));
    rendered.add(url);
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
