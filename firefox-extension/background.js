const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
const ALARM = "ulsb-periodic-sync";
let debounceTimer = null;

async function getState(defaults) {
  return await api.storage.local.get(defaults);
}

async function setState(values) {
  await api.storage.local.set(values);
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
  return site.enabled !== false;
}

async function postJson(path, body, authenticated = true) {
  const state = await getState({
    brokerUrl: DEFAULT_BROKER,
    clientToken: "",
    clientId: ""
  });
  const headers = {
    "Content-Type": "application/json",
    "X-ULSB-Extension-Origin": api.runtime.getURL("").replace(/\/$/, "")
  };
  if (authenticated) {
    if (!state.clientToken || !state.clientId) {
      throw new Error("Broker eşleştirmesi yok.");
    }
    headers.Authorization = `Bearer ${state.clientToken}`;
    headers["X-ULSB-Client-ID"] = state.clientId;
  }
  const response = await fetch(`${state.brokerUrl}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store"
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function pairBroker(payload) {
  const state = await getState({clientId: ""});
  const clientId = state.clientId || crypto.randomUUID();
  await setState({brokerUrl: payload.brokerUrl, clientId});
  const result = await postJson("/v1/pair", {
    code: payload.code,
    client_id: clientId,
    label: payload.label,
    browser: browserLabel()
  }, false);
  await setState({
    clientId,
    clientToken: result.client_token,
    profileLabel: payload.label,
    pairedAt: result.paired_at
  });
  return result;
}

async function sites() {
  const state = await getState({sites: []});
  return Array.isArray(state.sites) ? state.sites : [];
}

async function saveSites(value) {
  await setState({sites: value});
}

async function maybeKeepalive(site) {
  const minutes = Number(site.keepaliveMinutes || 0);
  if (!site.keepaliveUrl || minutes < 5) return;
  const previous = site.lastKeepaliveAt ? Date.parse(site.lastKeepaliveAt) : 0;
  if (Date.now() - previous < minutes * 60000) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(site.keepaliveUrl, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "follow",
      signal: controller.signal
    });
    site.lastKeepaliveStatus = response.status;
    site.lastKeepaliveAt = new Date().toISOString();
  } finally {
    clearTimeout(timeout);
  }
}

async function syncSite(site) {
  if (!siteEnabled(site)) {
    site.lastStatus = "DISABLED";
    site.lastError = "";
    return;
  }

  await maybeKeepalive(site);
  const details = {url: site.url};
  if (site.storeId) details.storeId = site.storeId;
  const cookies = await api.cookies.getAll(details);
  cookies.sort((a, b) => {
    const diff = (b.path || "/").length - (a.path || "/").length;
    return diff || String(a.name).localeCompare(String(b.name));
  });
  const state = await getState({clientId: "", profileLabel: ""});
  const currentBrowser = browserLabel();
  const result = await postJson("/v1/push", {
    client_id: state.clientId,
    name: site.name,
    title: String(site.title || "").slice(0, 300),
    url: site.url,
    browser: currentBrowser,
    store_id: site.storeId || "",
    keepalive_url: site.keepaliveUrl || "",
    keepalive_minutes: Number(site.keepaliveMinutes || 0),
    last_keepalive_status: site.lastKeepaliveStatus ?? null,
    cookies: cookies.map(cookie => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      httpOnly: cookie.httpOnly,
      sameSite: cookie.sameSite,
      expirationDate: cookie.expirationDate,
      storeId: cookie.storeId,
      partitionKey: cookie.partitionKey
    }))
  });
  site.enabled = true;
  site.browser = currentBrowser;
  site.profileLabel = state.profileLabel || "";
  site.lastStatus = "READY";
  site.lastSync = new Date().toISOString();
  site.cookieCount = result.cookie_count;
  site.lastError = "";
}

async function syncAll() {
  const current = await sites();
  for (const site of current) {
    if (!siteEnabled(site)) {
      site.lastStatus = "DISABLED";
      site.lastError = "";
      continue;
    }
    try {
      await syncSite(site);
    } catch (error) {
      site.lastStatus = "ERROR";
      site.lastError = String(error.message || error);
      site.lastSync = new Date().toISOString();
    }
  }
  await saveSites(current);
  return current;
}

async function syncOne(name) {
  const current = await sites();
  const site = current.find(item => item.name === name);
  if (!site) throw new Error("Kayıt bulunamadı.");
  if (!siteEnabled(site)) {
    site.lastStatus = "DISABLED";
    site.lastError = "";
    await saveSites(current);
    return site;
  }
  try {
    await syncSite(site);
  } catch (error) {
    site.lastStatus = "ERROR";
    site.lastError = String(error.message || error);
  }
  await saveSites(current);
  return site;
}

api.runtime.onInstalled.addListener(async () => {
  await api.alarms.create(ALARM, {periodInMinutes: 1});
});

api.runtime.onStartup.addListener(async () => {
  await api.alarms.create(ALARM, {periodInMinutes: 1});
  await syncAll();
});

api.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === ALARM) await syncAll();
});

api.cookies.onChanged.addListener(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => syncAll(), 1200);
});

api.runtime.onMessage.addListener(message => {
  if (message?.type === "PAIR") return pairBroker(message.payload);
  if (message?.type === "SYNC_ALL") return syncAll();
  if (message?.type === "SYNC_ONE") return syncOne(message.name);
  return undefined;
});
