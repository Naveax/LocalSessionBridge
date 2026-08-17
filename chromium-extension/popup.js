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
  return site.enabled !== false;
}

function permissionPattern(raw) {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Yalnız http/https URL.");
  return `${url.protocol}//${url.host}/*`;
}

function statusClass(status) {
  const value = String(status || "PENDING").toUpperCase();
  if (value === "READY") return "ready";
  if (value === "ERROR") return "error";
  if (value === "DISABLED") return "disabled";
  return "pending";
}

async function render() {
  const state = await getState({
    brokerUrl: DEFAULT_BROKER, profileLabel: "", pairedAt: "", sites: []
  });
  $("brokerUrl").value = state.brokerUrl;
  $("profileLabel").value = state.profileLabel;
  $("pairStatus").textContent = state.pairedAt ? `Eşleşti: ${state.pairedAt}` : "Eşleşmemiş";
  $("runtimeInfo").textContent = `Tarayıcı: ${browserLabel()} | Profil: ${state.profileLabel || "-"} | Broker: ${state.pairedAt ? "EŞLEŞTİ" : "EŞLEŞMEMİŞ"}`;

  const container = $("sites");
  container.textContent = "";

  for (const site of state.sites) {
    const enabled = siteEnabled(site);
    const item = document.createElement("div");
    item.className = "site";

    const head = document.createElement("div");
    head.className = "site-head";

    const titleWrap = document.createElement("div");
    titleWrap.className = "site-title";

    const title = document.createElement("strong");
    title.textContent = site.name;

    const pill = document.createElement("span");
    const status = enabled ? (site.lastStatus || "PENDING") : "DISABLED";
    pill.className = `pill ${statusClass(status)}`;
    pill.textContent = enabled ? String(status).toUpperCase() : "KAPALI";

    titleWrap.append(title, pill);

    const toggle = document.createElement("button");
    toggle.className = enabled ? "toggle-on" : "toggle-off";
    toggle.textContent = enabled ? "Kapat" : "Aç";
    toggle.onclick = async () => {
      try {
        const current = await getState({sites: []});
        const target = current.sites.find(x => x.name === site.name);
        if (!target) throw new Error("Kayıt bulunamadı.");
        target.enabled = !siteEnabled(target);
        target.lastStatus = target.enabled ? "PENDING" : "DISABLED";
        target.lastError = "";
        await setState({sites: current.sites});
        if (target.enabled) await api.runtime.sendMessage({type: "SYNC_ONE", name: target.name});
        await render();
      } catch (error) {
        $("addStatus").textContent = `HATA: ${error.message || error}`;
      }
    };

    head.append(titleWrap, toggle);

    const meta = document.createElement("div");
    meta.className = "muted";
    const siteBrowser = site.browser || browserLabel();
    const siteProfile = site.profileLabel || state.profileLabel || "-";
    const keepalive = Number(site.keepaliveMinutes || 0) > 0 ? `${site.keepaliveMinutes} dk` : "kapalı";
    meta.textContent = [
      `URL: ${site.url}`,
      `Tarayıcı: ${siteBrowser} | Profil: ${siteProfile}`,
      `Cookie: ${site.cookieCount ?? "?"} | Son eşitleme: ${site.lastSync || "-"}`,
      `Keep-alive: ${keepalive}${site.lastKeepaliveStatus ? ` | HTTP ${site.lastKeepaliveStatus}` : ""}`,
      site.lastError ? `Hata: ${site.lastError}` : ""
    ].filter(Boolean).join("\n");

    const actions = document.createElement("div");
    actions.className = "actions";

    const sync = document.createElement("button");
    sync.textContent = "Eşitle";
    sync.disabled = !enabled;
    sync.onclick = async () => {
      try {
        await api.runtime.sendMessage({type: "SYNC_ONE", name: site.name});
        await render();
      } catch (error) {
        $("addStatus").textContent = `HATA: ${error.message || error}`;
      }
    };

    const remove = document.createElement("button");
    remove.textContent = "Kaldır";
    remove.className = "danger";
    remove.onclick = async () => {
      const current = await getState({sites: []});
      await setState({sites: current.sites.filter(x => x.name !== site.name)});
      await render();
    };

    actions.append(sync, remove);
    item.append(head, meta, actions);
    container.append(item);
  }
}

$("pairButton").onclick = async () => {
  try {
    const brokerUrl = $("brokerUrl").value.trim().replace(/\/+$/, "");
    const label = $("profileLabel").value.trim();
    const code = $("pairCode").value.trim();
    const result = await api.runtime.sendMessage({
      type: "PAIR", payload: {brokerUrl, label, code}
    });
    $("pairStatus").textContent = `Eşleştirme başarılı: ${result.paired_at}`;
    await render();
  } catch (error) {
    $("pairStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("addButton").onclick = async () => {
  try {
    const name = $("siteName").value.trim();
    const url = new URL($("siteUrl").value.trim()).toString();
    if (!/^[A-Za-z0-9._-]{1,100}$/.test(name)) throw new Error("Kayıt adı geçersiz.");
    const granted = await api.permissions.request({origins: [permissionPattern(url)]});
    if (!granted) throw new Error("Host izni verilmedi.");
    const keepaliveUrl = $("keepaliveUrl").value.trim();
    if (keepaliveUrl && new URL(keepaliveUrl).origin !== new URL(url).origin) {
      throw new Error("Keep-alive aynı origin üzerinde olmalı.");
    }
    const keepaliveMinutes = Number($("keepaliveMinutes").value || 0);
    if (keepaliveMinutes !== 0 && keepaliveMinutes < 5) throw new Error("Keep-alive minimum 5 dakika.");
    const state = await getState({sites: [], profileLabel: ""});
    if (state.sites.some(site => site.name === name)) throw new Error("Bu kayıt adı zaten var.");
    state.sites.push({
      name,
      url,
      storeId: $("storeId").value.trim(),
      keepaliveUrl,
      keepaliveMinutes,
      enabled: true,
      browser: browserLabel(),
      profileLabel: state.profileLabel || "",
      lastStatus: "PENDING"
    });
    await setState({sites: state.sites});
    await api.runtime.sendMessage({type: "SYNC_ONE", name});
    $("addStatus").textContent = "Eklendi, açıldı ve eşitlendi.";
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("syncAllButton").onclick = async () => {
  try {
    await api.runtime.sendMessage({type: "SYNC_ALL"});
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("enableAllButton").onclick = async () => {
  try {
    const state = await getState({sites: []});
    for (const site of state.sites) {
      site.enabled = true;
      site.lastStatus = "PENDING";
      site.lastError = "";
    }
    await setState({sites: state.sites});
    await api.runtime.sendMessage({type: "SYNC_ALL"});
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("disableAllButton").onclick = async () => {
  try {
    const state = await getState({sites: []});
    for (const site of state.sites) {
      site.enabled = false;
      site.lastStatus = "DISABLED";
      site.lastError = "";
    }
    await setState({sites: state.sites});
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

render();
